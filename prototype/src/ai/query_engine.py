from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from typing import Any, Dict, List, Optional

from sqlalchemy import Select, select

from src.config import SUSPICIOUS_TERMS
from src.storage.database import Call, Contact, Message, session_scope
from src.storage.graph_store import GraphStore
from src.storage.vector_store import VectorRecord, VectorStore


@dataclass
class QueryResponse:
    query: str
    summary: str
    messages: list[dict[str, Any]]
    calls: list[dict[str, Any]]
    graph_insights: list[str]


class QueryEngine:
    def __init__(self) -> None:
        self.vector_store: VectorStore | None = VectorStore()
        self.graph_store: GraphStore | None = GraphStore()
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            self.vector_store.load()
        except FileNotFoundError:
            self.vector_store = None  # type: ignore[assignment]
        try:
            self.graph_store.load()
        except FileNotFoundError:
            self.graph_store = None  # type: ignore[assignment]

    def answer(self, query: str, limit: int = 5) -> QueryResponse:
        query_lower = query.lower()
        include_messages = any(term in query_lower for term in ["message", "chat", "text", "crypto", "btc"])
        include_calls = "call" in query_lower
        include_graph = any(term in query_lower for term in ["connection", "link", "network", "relationship"])
        foreign_only = any(term in query_lower for term in ["foreign", "international", "non-indian"])
        suspicious_terms = [term for term in SUSPICIOUS_TERMS if term in query_lower]
        time_filter = _extract_time_filter(query_lower)

        messages_payload: list[dict[str, Any]] = []
        calls_payload: list[dict[str, Any]] = []
        graph_payload: list[str] = []

        if include_messages and self.vector_store:
            candidates = self.vector_store.query(query_lower, k=limit)
            messages_payload = self._enrich_messages(candidates, foreign_only=foreign_only, time_filter=time_filter)

        if include_calls:
            calls_payload = self._query_calls(foreign_only=foreign_only, time_filter=time_filter, limit=limit)

        if include_graph and self.graph_store:
            graph_payload = self._graph_summary(limit=limit)

        summary = self._compose_summary(
            query=query,
            messages=messages_payload,
            calls=calls_payload,
            graph_insights=graph_payload,
            suspicious_terms=suspicious_terms,
        )

        return QueryResponse(
            query=query,
            summary=summary,
            messages=messages_payload,
            calls=calls_payload,
            graph_insights=graph_payload,
        )

    def _enrich_messages(
        self,
        candidates: List[VectorRecord],
        foreign_only: bool,
        time_filter: Optional[time],
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        with session_scope() as session:
            contact_lookup = {contact.contact_id: contact for contact in session.query(Contact).all()}
            message_ids = [candidate.message_id for candidate in candidates]
            stmt: Select = select(Message).where(Message.message_id.in_(message_ids)).order_by(Message.timestamp)
            messages = session.execute(stmt).scalars().all()
            for message in messages:
                sender = contact_lookup.get(message.sender_id)
                receiver = contact_lookup.get(message.receiver_id)
                if foreign_only:
                    participant_countries = {
                        getattr(sender, "country", None),
                        getattr(receiver, "country", None),
                    }
                    if not any(country and country != "India" for country in participant_countries):
                        continue
                if time_filter and message.timestamp.time() <= time_filter:
                    continue
                payload.append(
                    {
                        "message_id": message.message_id,
                        "timestamp": message.timestamp.isoformat(),
                        "app": message.app_name,
                        "sender": sender.name if sender else "Unknown",
                        "receiver": receiver.name if receiver else None,
                        "content": message.content,
                        "keywords": [kw.term for kw in message.keywords],
                    }
                )
        return payload

    def _query_calls(
        self,
        foreign_only: bool,
        time_filter: Optional[time],
        limit: int,
    ) -> list[dict[str, Any]]:
        with session_scope() as session:
            stmt = select(Call).order_by(Call.start_time.desc()).limit(limit)
            calls = session.execute(stmt).scalars().all()
            contact_lookup = {contact.contact_id: contact for contact in session.query(Contact).all()}
            payload: list[dict[str, Any]] = []
            for call in calls:
                caller = contact_lookup.get(call.caller_id)
                callee = contact_lookup.get(call.callee_id)
                if foreign_only:
                    countries = {getattr(caller, "country", None), getattr(callee, "country", None)}
                    if not any(country and country != "India" for country in countries):
                        continue
                if time_filter and call.start_time.time() <= time_filter:
                    continue
                payload.append(
                    {
                        "call_id": call.call_id,
                        "timestamp": call.start_time.isoformat(),
                        "caller": caller.name if caller else None,
                        "callee": callee.name if callee else None,
                        "duration_seconds": call.duration_seconds,
                        "type": call.call_type,
                        "location": call.location,
                    }
                )
        return payload

    def _graph_summary(self, limit: int) -> list[str]:
        if not self.graph_store:
            return []
        insights: list[str] = []
        graph = self.graph_store.graph
        for node in list(graph.nodes)[:limit]:
            neighbors = list(graph.neighbors(node))
            if neighbors:
                label = graph.nodes[node].get("label", str(node))
                neighbor_labels = [graph.nodes[neighbor].get("label", str(neighbor)) for neighbor in neighbors]
                insights.append(f"{label} connects to {', '.join(neighbor_labels[:5])}")
        return insights

    def _compose_summary(
        self,
        query: str,
        messages: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        graph_insights: list[str],
        suspicious_terms: list[str],
    ) -> str:
        components: list[str] = []
        if suspicious_terms:
            components.append(
                "Flagged terms: " + ", ".join(sorted(set(suspicious_terms)))
            )
        if messages:
            components.append(f"Found {len(messages)} relevant message(s).")
        if calls:
            components.append(f"Identified {len(calls)} matching call(s).")
        if graph_insights:
            components.append(f"Graph highlights: {graph_insights[0]}")
        if not components:
            components.append("No direct matches found in current dataset. Try a broader query or rerun ingestion.")
        return " ".join(components)


def _extract_time_filter(query: str) -> Optional[time]:
    match = re.search(r"after\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", query)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)
    if meridiem:
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
    hour = hour % 24
    minute = max(0, min(59, minute))
    return time(hour=hour, minute=minute)
