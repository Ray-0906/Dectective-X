from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency may be absent
    import google.generativeai as genai  # type: ignore
except ImportError:  # pragma: no cover
    genai = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QueryPlan:
    include_messages: Optional[bool] = None
    include_calls: Optional[bool] = None
    include_locations: Optional[bool] = None
    include_graph: Optional[bool] = None
    foreign_only: Optional[bool] = None
    person_names: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    time_after: Optional[str] = None
    result_limit: Optional[int] = None
    location_limit: Optional[int] = None


def plan_query(query: str) -> Optional[QueryPlan]:
    """Use Gemini to infer an intent plan from the natural language query."""

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not genai:
        return None

    model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")
    prompt = _build_prompt(query)

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        raw_text = _extract_text(response)
        payload = _load_plan_dict(raw_text)
        return _dict_to_plan(payload)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.warning("Gemini query planning failed: %s", exc)
        return None


def _build_prompt(query: str) -> str:
    safe_query = query.replace("\"", "\\\"")
    template = """
    You are an investigative assistant. Convert the analyst query into a JSON instruction that
    drives a forensic retrieval engine. Never include commentary or markdown fences—respond with
    JSON ONLY that conforms exactly to this schema:
    {
        "include_messages": true|false|null,
        "include_calls": true|false|null,
        "include_locations": true|false|null,
        "include_graph": true|false|null,
        "foreign_only": true|false|null,
        "person_names": ["<name>" ...],
        "topics": ["<keyword>" ...],
        "start_date": "<date phrase or ISO YYYY-MM-DD>"|null,
        "end_date": "<date phrase or ISO YYYY-MM-DD>"|null,
        "time_after": "<time like 22:00 or '10 pm'>"|null,
        "result_limit": <integer>|null,
        "location_limit": <integer>|null
    }

    Guidelines:
    - Set an include_* flag to true when the query clearly requests that evidence type.
    - Set an include_* flag to false when the query explicitly excludes it. Use null when uncertain.
    - Use lower-case keywords for topics.
    - Set foreign_only true when the query implies overseas/foreign/international filtering, else false or null.
    - Extract specific individuals or phone descriptors into person_names (even partial names).
    - For relative requests like "latest" or "last location", set location_limit to 1.
    - For explicit limits such as "top 3" or "first five", put the numeric value into result_limit.
    - Leave fields null when the query doesn't provide that information.

    Query: "{query}"
    """
    return dedent(template).strip().replace("{query}", safe_query)


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return text
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return ""
    parts: List[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []):
            value = getattr(part, "text", None)
            if value:
                parts.append(value)
    return "\n".join(parts)


def _load_plan_dict(raw_text: str) -> Dict[str, Any]:
    if not raw_text:
        raise ValueError("Empty response")
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Could not locate JSON object in response: {raw_text!r}")
    json_blob = raw_text[start : end + 1]
    return json.loads(json_blob)


def _dict_to_plan(data: Dict[str, Any]) -> QueryPlan:
    def _opt_bool(key: str) -> Optional[bool]:
        value = data.get(key)
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes"}:
                return True
            if lowered in {"false", "no"}:
                return False
        return None

    def _opt_int(key: str) -> Optional[int]:
        value = data.get(key)
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str):
            try:
                parsed = int(value)
                return parsed if parsed > 0 else None
            except ValueError:
                return None
        return None

    def _list_str(key: str) -> List[str]:
        value = data.get(key, [])
        if not isinstance(value, list):
            return []
        result: List[str] = []
        for item in value:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    result.append(cleaned)
        return result

    return QueryPlan(
        include_messages=_opt_bool("include_messages"),
        include_calls=_opt_bool("include_calls"),
        include_locations=_opt_bool("include_locations"),
        include_graph=_opt_bool("include_graph"),
        foreign_only=_opt_bool("foreign_only"),
        person_names=_list_str("person_names"),
        topics=[topic.lower() for topic in _list_str("topics")],
        start_date=_clean_str(data.get("start_date")),
        end_date=_clean_str(data.get("end_date")),
        time_after=_clean_str(data.get("time_after")),
        result_limit=_opt_int("result_limit"),
        location_limit=_opt_int("location_limit"),
    )


def _clean_str(value: Any) -> Optional[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None