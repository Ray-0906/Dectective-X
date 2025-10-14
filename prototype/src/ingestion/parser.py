from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Iterable, List

import xmltodict

from src.config import DATA_DIR, SUSPICIOUS_TERMS

logger = logging.getLogger(__name__)


@dataclass
class ContactRecord:
    external_id: str
    name: str | None
    phone_number: str | None
    email: str | None
    source_app: str | None
    country: str | None = None


@dataclass
class MessageRecord:
    external_id: str
    sender_external_id: str
    receiver_external_id: str | None
    timestamp: datetime
    content: str
    app_name: str | None
    media_path: str | None
    keywords: list[str]


@dataclass
class CallRecord:
    external_id: str
    caller_external_id: str
    callee_external_id: str
    call_type: str
    start_time: datetime
    duration_seconds: int
    location: str | None


@dataclass
class LocationRecord:
    location_id: str
    contact_external_id: str
    latitude: float
    longitude: float
    timestamp: datetime
    accuracy_meters: float | None


@dataclass
class ParsedUFDR:
    contacts: list[ContactRecord]
    messages: list[MessageRecord]
    calls: list[CallRecord]
    locations: list[LocationRecord]


class UFDRParser:
    """Simple parser tailored for Cellebrite-style UFDR exports used in demo dataset."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DATA_DIR
        self._contact_lookup: dict[str, ContactRecord] = {}

    def parse(self) -> ParsedUFDR:
        contacts = self._parse_contacts()
        calls = self._parse_calls()
        locations = self._parse_locations()
        messages = self._parse_messages()
        return ParsedUFDR(contacts=contacts, messages=messages, calls=calls, locations=locations)

    def _parse_contacts(self) -> list[ContactRecord]:
        contacts: list[ContactRecord] = []
        path = self.root / "contacts.csv"
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                record = ContactRecord(
                    external_id=row["ContactID"],
                    name=row.get("Name") or None,
                    phone_number=_normalize_phone(row.get("PhoneNumber")),
                    email=row.get("Email") or None,
                    source_app=row.get("SourceApp") or None,
                    country=_determine_country(row.get("PhoneNumber")),
                )
                contacts.append(record)
                if record.name:
                    self._contact_lookup[record.name] = record
                if record.phone_number:
                    self._contact_lookup[record.phone_number] = record
        return contacts

    def _parse_calls(self) -> list[CallRecord]:
        records: list[CallRecord] = []
        path = self.root / "calls.csv"
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                caller = self._get_or_create_contact(row["CallerID"], row.get("CallerID"))
                callee = self._get_or_create_contact(row["CalleeID"], row.get("CalleeID"))
                record = CallRecord(
                    external_id=row["CallID"],
                    caller_external_id=caller.external_id,
                    callee_external_id=callee.external_id,
                    call_type=row.get("Type", "Unknown"),
                    start_time=_parse_datetime(row.get("StartTime")),
                    duration_seconds=int(row.get("DurationSeconds") or 0),
                    location=row.get("Location") or None,
                )
                records.append(record)
        return records

    def _parse_locations(self) -> list[LocationRecord]:
        records: list[LocationRecord] = []
        path = self.root / "locations.csv"
        if not path.exists():
            return records
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                contact = self._get_or_create_contact(row["ContactID"], row.get("ContactID"))
                records.append(
                    LocationRecord(
                        location_id=row["LocationID"],
                        contact_external_id=contact.external_id,
                        latitude=float(row["Latitude"]),
                        longitude=float(row["Longitude"]),
                        timestamp=_parse_datetime(row.get("Timestamp")),
                        accuracy_meters=float(row["AccuracyMeters"]) if row.get("AccuracyMeters") else None,
                    )
                )
        return records

    def _parse_messages(self) -> list[MessageRecord]:
        path = self.root / "messages.xml"
        with path.open("r", encoding="utf-8") as fh:
            doc = xmltodict.parse(fh.read())
        chats = doc["messages"]["chat"]
        if isinstance(chats, dict):
            chats = [chats]
        records: list[MessageRecord] = []
        for chat in chats:
            app = chat.get("@app") or None
            messages: Iterable[dict] = chat.get("message", [])
            if isinstance(messages, dict):
                messages = [messages]
            for message in messages:
                sender_name = message.get("sender") or message.get("@sender")
                receiver_name = message.get("receiver") or message.get("@receiver")
                sender_contact = self._get_or_create_contact(sender_name or "Unknown", sender_name)
                receiver_contact = self._get_or_create_contact(receiver_name, receiver_name) if receiver_name else None
                text = message.get("text", "").strip()
                keywords = _extract_keywords(text)
                records.append(
                    MessageRecord(
                        external_id=message.get("@id") or message.get("id") or _generate_message_id(len(records)),
                        sender_external_id=sender_contact.external_id,
                        receiver_external_id=receiver_contact.external_id if receiver_contact else None,
                        timestamp=_parse_datetime(message.get("timestamp") or message.get("@timestamp")),
                        content=text,
                        app_name=app,
                        media_path=_extract_media_path(message),
                        keywords=keywords,
                    )
                )
        return records

    def _get_or_create_contact(self, identifier: str | None, name_hint: str | None) -> ContactRecord:
        if identifier and identifier in self._contact_lookup:
            return self._contact_lookup[identifier]
        if name_hint and name_hint in self._contact_lookup:
            return self._contact_lookup[name_hint]
        # create synthetic contact entry
        synthetic_id = identifier or f"virtual_{len(self._contact_lookup) + 1}"
        record = ContactRecord(
            external_id=synthetic_id,
            name=name_hint,
            phone_number=_normalize_phone(identifier),
            email=None,
            source_app=None,
            country=_determine_country(identifier),
        )
        if record.name:
            self._contact_lookup[record.name] = record
        if record.phone_number:
            self._contact_lookup[record.phone_number] = record
        self._contact_lookup[record.external_id] = record
        return record


def _normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith("+"):
        return value
    if value.isdigit():
        return f"+{value}"
    return value


def _determine_country(phone: str | None) -> str | None:
    if not phone:
        return None
    normalized = _normalize_phone(phone)
    if not normalized:
        return None
    if normalized.startswith("+91"):
        return "India"
    if normalized.startswith("+44"):
        return "United Kingdom"
    if normalized.startswith("+1"):
        return "United States"
    return None


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        logger.warning("Missing timestamp for record; defaulting to current UTC time")
        return datetime.now(timezone.utc)
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.warning("Invalid timestamp '%s'; defaulting to current UTC time", value)
        return datetime.now(timezone.utc)


def _extract_keywords(text: str) -> list[str]:
    lowered = text.lower()
    return sorted({term for term in SUSPICIOUS_TERMS if term in lowered})


def _extract_media_path(message: dict) -> str | None:
    media = message.get("media")
    if not media:
        return None
    if isinstance(media, dict):
        return media.get("@file")
    return None


def _generate_message_id(sequence: int) -> str:
    return f"synthetic_msg_{sequence:04d}"
