from __future__ import annotations

import logging
import os
from textwrap import dedent
from typing import Any, Iterable, List, Mapping

try:  # pragma: no cover - optional dependency may be absent in tests
    import google.generativeai as genai  # type: ignore
except ImportError:  # pragma: no cover
    genai = None  # type: ignore

logger = logging.getLogger(__name__)

_REPORT_TEMPLATE = """# Investigation Summary\n\n## Scope\n- Query: {query}\n- Findings: {summary}\n\n## Communications\n{messages}\n\n## Call Activity\n{calls}\n\n## Location Trail\n{locations}\n\n## Network Insights\n{graph}\n"""


def generate_report(
    *,
    query: str,
    summary: str,
    messages: List[Mapping[str, Any]],
    calls: List[Mapping[str, Any]],
    locations: List[Mapping[str, Any]],
    graph_insights: List[str],
    contacts: Iterable[Mapping[str, Any]],
) -> str:
    """Produce a narrative report using Gemini when available, else a concise fallback."""

    payload = {
        "query": query,
        "summary": summary,
        "messages": list(messages),
        "calls": list(calls),
        "locations": list(locations),
        "graph_insights": list(graph_insights),
        "contacts": list(contacts),
    }

    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")

    if api_key and genai:  # pragma: no branch - simple guard
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            prompt = _build_prompt(payload)
            response = model.generate_content(prompt)
            text = getattr(response, "text", None)
            if text:
                return text.strip()
            if getattr(response, "candidates", None):
                candidate_text = "".join(
                    part.text
                    for candidate in response.candidates  # type: ignore[attr-defined]
                    for part in getattr(candidate, "content", {}).get("parts", [])
                    if getattr(part, "text", None)
                )
                if candidate_text:
                    return candidate_text.strip()
        except Exception as exc:  # pragma: no cover - network failure handled gracefully
            logger.warning("Gemini report generation failed: %s", exc)

    return _fallback_report(payload)


def _build_prompt(payload: Mapping[str, Any]) -> str:
    return dedent(
        f"""
        You are a digital forensics analyst. Draft a concise, evidence-backed narrative based on the data provided.
        Respond in markdown with sections for Summary, Key Individuals, Communications, Calls, Locations, and Recommendations.

        ## Original Query
        {payload['query']}

        ## High-Level Findings
        {payload['summary']}

        ## Messages
        {payload['messages']}

        ## Calls
        {payload['calls']}

        ## Locations
        {payload['locations']}

        ## Graph Insights
        {payload['graph_insights']}

        ## Contacts
        {payload['contacts']}
        """
    ).strip()


def _fallback_report(payload: Mapping[str, Any]) -> str:
    def _format_section(items: Iterable[Mapping[str, Any]], fields: List[str]) -> str:
        rows = []
        for item in items:
            parts = []
            for field in fields:
                value = item.get(field)
                if value is None or value == "":
                    continue
                parts.append(f"{field.replace('_', ' ').title()}: {value}")
            if parts:
                rows.append("- " + "; ".join(parts))
        return "\n".join(rows) if rows else "- No relevant entries found."

    messages_section = _format_section(
        payload.get("messages", []),
        ["timestamp", "sender", "receiver", "app", "content"],
    )
    calls_section = _format_section(
        payload.get("calls", []),
        ["timestamp", "caller", "callee", "type", "duration_seconds", "location"],
    )
    locations_section = _format_section(
        payload.get("locations", []),
        ["timestamp", "contact", "latitude", "longitude", "accuracy_meters"],
    )
    graph_section = "\n".join(f"- {insight}" for insight in payload.get("graph_insights", []) or ["No graph patterns surfaced."])

    return _REPORT_TEMPLATE.format(
        query=payload.get("query", ""),
        summary=payload.get("summary", ""),
        messages=messages_section,
        calls=calls_section,
        locations=locations_section,
        graph=graph_section,
    ).strip()


def generate_brief(
    *,
    query: str,
    summary: str,
    messages: List[Mapping[str, Any]],
    calls: List[Mapping[str, Any]],
    locations: List[Mapping[str, Any]],
    graph_insights: List[str],
) -> str:
    """Return a compact, conversational answer describing the findings."""

    payload = {
        "query": query,
        "summary": summary,
        "messages": list(messages),
        "calls": list(calls),
        "locations": list(locations),
        "graph_insights": list(graph_insights),
    }

    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")

    if api_key and genai:  # pragma: no branch
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            prompt = _build_brief_prompt(payload)
            response = model.generate_content(prompt)
            text = getattr(response, "text", None)
            if text:
                return text.strip()
            if getattr(response, "candidates", None):
                for candidate in response.candidates:  # type: ignore[attr-defined]
                    parts = getattr(candidate, "content", {}).get("parts", [])
                    for part in parts:
                        value = getattr(part, "text", None)
                        if value:
                            return value.strip()
        except Exception as exc:  # pragma: no cover
            logger.warning("Gemini brief generation failed: %s", exc)

    return _fallback_brief(payload)


def _build_brief_prompt(payload: Mapping[str, Any]) -> str:
    return dedent(
        f"""
        You are an investigative assistant. Write a concise answer (max 3 sentences) that directly addresses the analyst query
        using the available evidence. Mention specific contacts, times, or locations when relevant and highlight any risky or
        foreign activity. Respond with plain text only.

        ## Query
        {payload['query']}

        ## Summary
        {payload['summary']}

        ## Messages
        {payload['messages']}

        ## Calls
        {payload['calls']}

        ## Locations
        {payload['locations']}

        ## Graph Insights
        {payload['graph_insights']}
        """
    ).strip()


def _fallback_brief(payload: Mapping[str, Any]) -> str:
    parts: List[str] = []
    summary = payload.get("summary") or "No direct matches were found."
    parts.append(summary)

    messages = payload.get("messages") or []
    if messages:
        latest = messages[0]
        sender = latest.get("sender") or "an unknown sender"
        receiver = latest.get("receiver") or "their contact"
        timestamp = latest.get("timestamp")
        content = latest.get("content")
        snippet = f" Latest message from {sender} to {receiver}"
        if timestamp:
            snippet += f" on {timestamp}"
        if content:
            snippet += f" discusses {content[:80]}"
        parts.append(snippet + ".")

    locations = payload.get("locations") or []
    if locations:
        loc = locations[0]
        contact = loc.get("contact") or "an unknown contact"
        city = f"({loc.get('latitude')}, {loc.get('longitude')})"
        timestamp = loc.get("timestamp")
        parts.append(f" Most recent location fix for {contact} at {city}{' on ' + timestamp if timestamp else ''}.")

    calls = payload.get("calls") or []
    if calls:
        call = calls[0]
        caller = call.get("caller") or "Unknown caller"
        callee = call.get("callee") or "unknown callee"
        parts.append(f" Call activity includes {caller} speaking with {callee}.")

    graph_insights = payload.get("graph_insights") or []
    if graph_insights:
        parts.append(f" Graph highlight: {graph_insights[0]}.")

    return "".join(parts).strip()
