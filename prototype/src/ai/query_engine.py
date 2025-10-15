from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable, List, Optional, Set, Tuple

import dateparser
from dateparser.search import search_dates
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import selectinload

from src.ai.query_planner import QueryPlan, plan_query
from src.ai.report_generator import generate_brief, generate_report
from src.config import LOCAL_TIMEZONE, LOCAL_TIMEZONE_NAME, SUSPICIOUS_TERMS
from src.storage.database import Call, Contact, Location, Message, session_scope
from src.storage.graph_store import GraphStore
from src.storage.vector_store import VectorRecord, VectorStore

logger = logging.getLogger(__name__)

def _format_local_iso(timestamp: datetime) -> str:
    return timestamp.astimezone(LOCAL_TIMEZONE).isoformat()

STOP_WORDS: Set[str] = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "to",
    "for",
    "about",
    "show",
    "me",
    "list",
    "of",
    "any",
    "there",
    "where",
    "what",
    "which",
    "who",
    "when",
    "and",
    "or",
    "with",
    "from",
    "last",
    "day",
    "days",
    "week",
    "weeks",
    "month",
    "months",
    "information",
    "info",
    "messages",
    "message",
    "calls",
    "call",
    "person",
    "people",
    "contact",
    "contacts",
    "location",
    "locations",
    "visit",
    "visited",
    "on",
    "in",
    "after",
    "before",
    "between",
    "range",
    "today",
    "yesterday",
    "recent",
    "recently",
    "this",
    "that",
    "these",
    "those",
    "someone",
    "anyone",
    "everyone",
    "tell",
    "give",
    "details",
    "report",
}

LOCATION_TERMS = {"location", "locations", "visit", "visited", "where", "travel", "movement", "route"}
CALL_TERMS = {"call", "called", "spoke", "dial", "conversation"}
MESSAGE_TERMS = {"message", "messages", "chat", "text", "information", "topic", "note"}
GRAPH_TERMS = {"connection", "connections", "network", "relationship", "link"}
FOREIGN_TERMS = {"foreign", "international", "non-indian", "overseas"}


@dataclass
class QueryResponse:
    query: str
    summary: str
    messages: list[dict[str, Any]]
    calls: list[dict[str, Any]]
    locations: list[dict[str, Any]]
    graph_insights: list[str]
    report: str
    narrative: str


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

        with session_scope() as session:
            contacts = session.query(Contact).all()
        contact_lookup = {contact.contact_id: contact for contact in contacts}

        person_ids = _detect_person_ids(query_lower, contacts)
        foreign_only = any(term in query_lower for term in FOREIGN_TERMS)
        suspicious_terms = [term for term in SUSPICIOUS_TERMS if term in query_lower]
        topic_terms = _extract_topic_terms(query_lower, suspicious_terms, contact_lookup, person_ids)
        time_filter = _extract_time_filter(query_lower)
        date_range = _extract_date_range(query)

        include_locations = bool(LOCATION_TERMS.intersection(query_lower.split())) or "location" in query_lower
        include_calls = bool(CALL_TERMS.intersection(query_lower.split())) or "call" in query_lower
        include_graph = bool(GRAPH_TERMS.intersection(query_lower.split()))
        include_messages = True if include_calls or include_locations else bool(MESSAGE_TERMS.intersection(query_lower.split()))
        if not include_messages and not include_calls and not include_locations:
            include_messages = True

        message_limit = limit
        call_limit = limit
        location_limit = limit

        plan: QueryPlan | None = plan_query(query)
        if plan:
            if plan.include_messages is not None:
                include_messages = plan.include_messages
            if plan.include_calls is not None:
                include_calls = plan.include_calls
            if plan.include_locations is not None:
                include_locations = plan.include_locations
            if plan.include_graph:
                include_graph = True
            if plan.foreign_only:
                foreign_only = True
            if plan.person_names:
                person_ids.update(_match_contacts_by_name(plan.person_names, contacts))
            if plan.topics:
                topic_terms.update({topic.lower() for topic in plan.topics})
            if plan.result_limit:
                message_limit = call_limit = location_limit = max(1, plan.result_limit)
            if plan.location_limit:
                location_limit = max(1, plan.location_limit)
            if plan.start_date or plan.end_date:
                parsed_start = _parse_date_fragment(plan.start_date) if plan.start_date else None
                parsed_end = _parse_date_fragment(plan.end_date) if plan.end_date else None
                if parsed_start or parsed_end:
                    date_range = _normalize_range(parsed_start or date_range[0], parsed_end or date_range[1])
            if plan.time_after:
                parsed_time = _parse_time_of_day(plan.time_after)
                if parsed_time:
                    time_filter = parsed_time

        if not (include_messages or include_calls or include_locations):
            include_messages = True

        messages_payload: list[dict[str, Any]] = []
        calls_payload: list[dict[str, Any]] = []
        locations_payload: list[dict[str, Any]] = []
        graph_payload: list[str] = []

        if include_messages:
            messages_payload = self._collect_messages(
                query_text=query,
                contact_lookup=contact_lookup,
                person_ids=person_ids,
                foreign_only=foreign_only,
                date_range=date_range,
                time_filter=time_filter,
                topic_terms=topic_terms,
                limit=message_limit,
            )

        if include_calls:
            calls_payload = self._query_calls(
                contact_lookup=contact_lookup,
                person_ids=person_ids,
                foreign_only=foreign_only,
                date_range=date_range,
                time_filter=time_filter,
                limit=call_limit,
            )

        if include_locations:
            locations_payload = self._query_locations(
                contact_lookup=contact_lookup,
                person_ids=person_ids,
                date_range=date_range,
                time_filter=time_filter,
                limit=location_limit,
            )

        if include_graph and self.graph_store:
            graph_payload = self._graph_summary(limit=limit)

        summary = self._compose_summary(
            query=query,
            messages=messages_payload,
            calls=calls_payload,
            locations=locations_payload,
            graph_insights=graph_payload,
            suspicious_terms=suspicious_terms,
        )

        report = generate_report(
            query=query,
            summary=summary,
            messages=messages_payload,
            calls=calls_payload,
            locations=locations_payload,
            graph_insights=graph_payload,
            contacts=[
                {
                    "contact_id": contact.contact_id,
                    "name": contact.name,
                    "phone_number": contact.phone_number,
                    "country": contact.country,
                }
                for contact in contacts
            ],
        )

        narrative = generate_brief(
            query=query,
            summary=summary,
            messages=messages_payload,
            calls=calls_payload,
            locations=locations_payload,
            graph_insights=graph_payload,
        )

        return QueryResponse(
            query=query,
            summary=summary,
            messages=messages_payload,
            calls=calls_payload,
            locations=locations_payload,
            graph_insights=graph_payload,
            report=report,
            narrative=narrative,
        )

    def _collect_messages(
        self,
        query_text: str,
        contact_lookup: dict[int, Contact],
        person_ids: Set[int],
        foreign_only: bool,
        date_range: Tuple[Optional[datetime], Optional[datetime]],
        time_filter: Optional[time],
        topic_terms: Set[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        candidates: list[VectorRecord] = []
        if self.vector_store:
            try:
                candidates = self.vector_store.query(query_text, k=max(limit * 3, 10))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Vector query failed: %s", exc)
        if candidates:
            results = self._enrich_messages(
                candidates=candidates,
                contact_lookup=contact_lookup,
                person_ids=person_ids,
                foreign_only=foreign_only,
                date_range=date_range,
                time_filter=time_filter,
                topic_terms=topic_terms,
                limit=limit,
            )
        if not results:
            results = self._fallback_message_search(
                query_text=query_text,
                contact_lookup=contact_lookup,
                person_ids=person_ids,
                foreign_only=foreign_only,
                date_range=date_range,
                time_filter=time_filter,
                topic_terms=topic_terms,
                limit=limit,
            )
        return results[:limit]

    def _enrich_messages(
        self,
        candidates: List[VectorRecord],
        contact_lookup: dict[int, Contact],
        person_ids: Set[int],
        foreign_only: bool,
        date_range: Tuple[Optional[datetime], Optional[datetime]],
        time_filter: Optional[time],
        topic_terms: Set[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        message_ids = [candidate.message_id for candidate in candidates]
        if not message_ids:
            return []
        with session_scope() as session:
            stmt: Select = (
                select(Message)
                .where(Message.message_id.in_(message_ids))
                .options(selectinload(Message.keywords))
            )
            start, end = date_range
            if start:
                stmt = stmt.where(Message.timestamp >= start)
            if end:
                stmt = stmt.where(Message.timestamp <= end)
            if person_ids:
                stmt = stmt.where(or_(Message.sender_id.in_(person_ids), Message.receiver_id.in_(person_ids)))
            stmt = stmt.order_by(Message.timestamp.desc())
            records = session.execute(stmt).scalars().all()

        ranking = {message_id: index for index, message_id in enumerate(message_ids)}
        records.sort(key=lambda message: ranking.get(message.message_id, len(ranking)))

        payload: list[dict[str, Any]] = []
        for message in records:
            if not _timestamp_in_range(message.timestamp, date_range):
                continue
            if time_filter and message.timestamp.time() <= time_filter:
                continue
            sender = contact_lookup.get(message.sender_id)
            receiver = contact_lookup.get(message.receiver_id)
            if foreign_only:
                countries = {
                    getattr(sender, "country", None),
                    getattr(receiver, "country", None),
                }
                if not any(country and country != "India" for country in countries):
                    continue
            content_lower = message.content.lower()
            if topic_terms and not any(term in content_lower for term in topic_terms.union(set(k for k in SUSPICIOUS_TERMS))):
                continue
            payload.append(
                {
                    "message_id": message.message_id,
                    "timestamp": _format_local_iso(message.timestamp),
                    "app": message.app_name,
                    "sender": sender.name if sender else "Unknown",
                    "receiver": receiver.name if receiver else None,
                    "content": message.content,
                    "keywords": [kw.term for kw in message.keywords],
                }
            )
            if len(payload) >= limit:
                break
        return payload

    def _fallback_message_search(
        self,
        query_text: str,
        contact_lookup: dict[int, Contact],
        person_ids: Set[int],
        foreign_only: bool,
        date_range: Tuple[Optional[datetime], Optional[datetime]],
        time_filter: Optional[time],
        topic_terms: Set[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        tokens = topic_terms or _extract_topic_terms(query_text.lower(), [], contact_lookup, person_ids)
        with session_scope() as session:
            stmt = (
                select(Message)
                .order_by(Message.timestamp.desc())
                .limit(200)
                .options(selectinload(Message.keywords))
            )
            start, end = date_range
            if start:
                stmt = stmt.where(Message.timestamp >= start)
            if end:
                stmt = stmt.where(Message.timestamp <= end)
            if person_ids:
                stmt = stmt.where(or_(Message.sender_id.in_(person_ids), Message.receiver_id.in_(person_ids)))
            results = session.execute(stmt).scalars().all()

        payload: list[dict[str, Any]] = []
        for message in results:
            if not _timestamp_in_range(message.timestamp, date_range):
                continue
            if time_filter and message.timestamp.time() <= time_filter:
                continue
            sender = contact_lookup.get(message.sender_id)
            receiver = contact_lookup.get(message.receiver_id)
            if foreign_only:
                countries = {
                    getattr(sender, "country", None),
                    getattr(receiver, "country", None),
                }
                if not any(country and country != "India" for country in countries):
                    continue
            content_lower = message.content.lower()
            search_terms = set(tokens).union(SUSPICIOUS_TERMS)
            if tokens and not any(term in content_lower for term in search_terms):
                continue
            payload.append(
                {
                    "message_id": message.message_id,
                    "timestamp": _format_local_iso(message.timestamp),
                    "app": message.app_name,
                    "sender": sender.name if sender else "Unknown",
                    "receiver": receiver.name if receiver else None,
                    "content": message.content,
                    "keywords": [kw.term for kw in message.keywords],
                }
            )
            if len(payload) >= limit:
                break
        return payload

    def _query_calls(
        self,
        contact_lookup: dict[int, Contact],
        person_ids: Set[int],
        foreign_only: bool,
        date_range: Tuple[Optional[datetime], Optional[datetime]],
        time_filter: Optional[time],
        limit: int,
    ) -> list[dict[str, Any]]:
        with session_scope() as session:
            stmt = select(Call).order_by(Call.start_time.desc()).limit(200)
            start, end = date_range
            if start:
                stmt = stmt.where(Call.start_time >= start)
            if end:
                stmt = stmt.where(Call.start_time <= end)
            if person_ids:
                stmt = stmt.where(or_(Call.caller_id.in_(person_ids), Call.callee_id.in_(person_ids)))
            calls = session.execute(stmt).scalars().all()

        payload: list[dict[str, Any]] = []
        for call in calls:
            if not _timestamp_in_range(call.start_time, date_range):
                continue
            if time_filter and call.start_time.time() <= time_filter:
                continue
            caller = contact_lookup.get(call.caller_id)
            callee = contact_lookup.get(call.callee_id)
            if foreign_only:
                countries = {getattr(caller, "country", None), getattr(callee, "country", None)}
                if not any(country and country != "India" for country in countries):
                    continue
            payload.append(
                {
                    "call_id": call.call_id,
                    "timestamp": _format_local_iso(call.start_time),
                    "caller": caller.name if caller else None,
                    "callee": callee.name if callee else None,
                    "duration_seconds": call.duration_seconds,
                    "type": call.call_type,
                    "location": call.location,
                }
            )
            if len(payload) >= limit:
                break
        return payload

    def _query_locations(
        self,
        contact_lookup: dict[int, Contact],
        person_ids: Set[int],
        date_range: Tuple[Optional[datetime], Optional[datetime]],
        time_filter: Optional[time],
        limit: int,
    ) -> list[dict[str, Any]]:
        with session_scope() as session:
            stmt = select(Location).order_by(Location.timestamp.desc()).limit(200)
            start, end = date_range
            if start:
                stmt = stmt.where(Location.timestamp >= start)
            if end:
                stmt = stmt.where(Location.timestamp <= end)
            if person_ids:
                stmt = stmt.where(Location.contact_id.in_(person_ids))
            locations = session.execute(stmt).scalars().all()

        payload: list[dict[str, Any]] = []
        for location in locations:
            if not _timestamp_in_range(location.timestamp, date_range):
                continue
            if time_filter and location.timestamp.time() <= time_filter:
                continue
            contact = contact_lookup.get(location.contact_id)
            payload.append(
                {
                    "location_id": location.location_id,
                    "timestamp": _format_local_iso(location.timestamp),
                    "contact": contact.name if contact else None,
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "accuracy_meters": location.accuracy_meters,
                }
            )
            if len(payload) >= limit:
                break
        return payload

    def _graph_summary(self, limit: int) -> list[str]:
        if not self.graph_store:
            return []
        insights: list[str] = []
        graph = self.graph_store.graph
        for node in list(graph.nodes)[: limit * 2]:
            neighbors = list(graph.neighbors(node))
            if not neighbors:
                continue
            label = graph.nodes[node].get("label", str(node))
            neighbor_labels = [graph.nodes[neighbor].get("label", str(neighbor)) for neighbor in neighbors]
            insights.append(f"{label} connects to {', '.join(neighbor_labels[:5])}")
            if len(insights) >= limit:
                break
        return insights

    def _compose_summary(
        self,
        query: str,
        messages: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        locations: list[dict[str, Any]],
        graph_insights: list[str],
        suspicious_terms: list[str],
    ) -> str:
        components: list[str] = []
        if suspicious_terms:
            components.append("Flagged terms: " + ", ".join(sorted(set(suspicious_terms))))
        if messages:
            components.append(f"Found {len(messages)} relevant message(s).")
        if calls:
            components.append(f"Identified {len(calls)} matching call(s).")
        if locations:
            components.append(f"Collected {len(locations)} location record(s).")
        if graph_insights:
            components.append(f"Graph highlights: {graph_insights[0]}")
        if not components:
            components.append("No direct matches found in current dataset. Try adjusting the timeframe or rerunning ingestion.")
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


def _extract_date_range(query: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    text = query.lower()
    now = datetime.now(LOCAL_TIMEZONE)

    match = re.search(r"last\s+(\d+)\s+(day|days|week|weeks|month|months)", text)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        days = value
        if "week" in unit:
            days = value * 7
        elif "month" in unit:
            days = value * 30
        start = now - timedelta(days=days)
        return _normalize_range(start, now)

    between_match = re.search(r"(?:between|from)\s+([\w\s,/-]+?)\s+(?:and|to)\s+([\w\s,/-]+)", text)
    if between_match:
        first = _parse_date_fragment(between_match.group(1))
        second = _parse_date_fragment(between_match.group(2))
        return _normalize_range(first, second)

    results = search_dates(query, settings={"TIMEZONE": LOCAL_TIMEZONE_NAME, "RETURN_AS_TIMEZONE_AWARE": True})
    if results:
        parsed_dates = [
            dt
            for fragment, dt in results
            if not _looks_like_time_only(fragment) and not _looks_like_noise_fragment(fragment)
        ]
        if parsed_dates:
            if len(parsed_dates) == 1:
                return _normalize_range(parsed_dates[0], parsed_dates[0])
            return _normalize_range(min(parsed_dates), max(parsed_dates))

    return (None, None)


def _parse_date_fragment(fragment: str) -> Optional[datetime]:
    fragment = fragment.strip()
    if not fragment:
        return None
    parsed = dateparser.parse(
        fragment,
        settings={
            "TIMEZONE": LOCAL_TIMEZONE_NAME,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DAY_OF_MONTH": "first",
        },
    )
    return parsed


def _normalize_range(start: Optional[datetime], end: Optional[datetime]) -> Tuple[Optional[datetime], Optional[datetime]]:
    if not start and not end:
        return (None, None)
    if start and not start.tzinfo:
        start = start.replace(tzinfo=LOCAL_TIMEZONE)
    if end and not end.tzinfo:
        end = end.replace(tzinfo=LOCAL_TIMEZONE)
    if start and not end:
        end = start
    if end and not start:
        start = end
    if not start or not end:
        return (None, None)
    local_start = start.astimezone(LOCAL_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = end.astimezone(LOCAL_TIMEZONE).replace(hour=23, minute=59, second=59, microsecond=999999)
    if local_start > local_end:
        local_start, local_end = local_end, local_start
    return (local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc))


def _timestamp_in_range(timestamp: datetime, date_range: Tuple[Optional[datetime], Optional[datetime]]) -> bool:
    start, end = date_range
    stamp = timestamp.astimezone(timezone.utc)
    if start and stamp < start:
        return False
    if end and stamp > end:
        return False
    return True


def _extract_topic_terms(
    query_lower: str,
    suspicious_terms: Iterable[str],
    contact_lookup: dict[int, Contact],
    person_ids: Set[int],
) -> Set[str]:
    tokens = set(re.findall(r"[a-z0-9]{3,}", query_lower))
    tokens.difference_update(STOP_WORDS)
    tokens.update(term for term in suspicious_terms)
    tokens.difference_update(FOREIGN_TERMS)
    tokens.difference_update(LOCATION_TERMS)
    tokens.difference_update(CALL_TERMS)
    tokens.difference_update(GRAPH_TERMS)
    person_names = {
        token
        for contact_id in person_ids
        for token in _contact_tokens(contact_lookup.get(contact_id))
    }
    tokens.difference_update(person_names)
    return tokens


def _looks_like_time_only(fragment: str) -> bool:
    snippet = fragment.strip().lower()
    return bool(re.fullmatch(r"(?:after|before|around|at)?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)", snippet))


def _looks_like_noise_fragment(fragment: str) -> bool:
    snippet = fragment.strip().lower()
    if len(snippet) <= 2:
        return True
    return snippet in {"me", "yo", "tu", "il"}


def _detect_person_ids(query_lower: str, contacts: Iterable[Contact]) -> Set[int]:
    ids: Set[int] = set()
    for contact in contacts:
        for token in _contact_tokens(contact):
            if token and token in query_lower:
                ids.add(contact.contact_id)
                break
    return ids


def _contact_tokens(contact: Optional[Contact]) -> Set[str]:
    if not contact:
        return set()
    tokens: Set[str] = set()
    if contact.name:
        lowered = contact.name.lower()
        tokens.add(lowered)
        for part in lowered.split():
            if len(part) >= 3:
                tokens.add(part)
    if contact.phone_number:
        phone = contact.phone_number.lower()
        tokens.add(phone)
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 6:
            tokens.add(digits)
    return tokens


def _match_contacts_by_name(names: Iterable[str], contacts: Iterable[Contact]) -> Set[int]:
    target_tokens: List[Set[str]] = []
    for name in names:
        lowered = name.strip().lower()
        if not lowered:
            continue
        token_set = set(re.findall(r"[a-z0-9]{3,}", lowered))
        token_set.add(lowered)
        target_tokens.append(token_set)
    if not target_tokens:
        return set()

    matched: Set[int] = set()
    for contact in contacts:
        contact_tokens = _contact_tokens(contact)
        if not contact_tokens:
            continue
        for token_set in target_tokens:
            if token_set.intersection(contact_tokens):
                matched.add(contact.contact_id)
                break
    return matched


def _parse_time_of_day(text: str) -> Optional[time]:
    snippet = text.strip().lower()
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", snippet)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    hour = max(0, min(hour % 24, 23))
    minute = max(0, min(minute, 59))
    return time(hour=hour, minute=minute)
