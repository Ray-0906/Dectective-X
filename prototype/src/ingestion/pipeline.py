from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict

from src.config import DATA_DIR, DB_PATH, GRAPH_PATH, METADATA_PATH, VECTOR_INDEX_PATH
from src.ingestion.parser import UFDRParser
from src.storage.database import (
    Base,
    Call,
    Contact,
    Device,
    Keyword,
    Location,
    Media,
    Message,
    engine,
    session_scope,
)
from src.storage.graph_store import GraphStore
from src.storage.vector_store import VectorRecord, VectorStore


def reset_storage() -> None:
    engine.dispose()
    if DB_PATH.exists():
        DB_PATH.unlink()
    if VECTOR_INDEX_PATH.exists():
        VECTOR_INDEX_PATH.unlink()
    if METADATA_PATH.exists():
        METADATA_PATH.unlink()
    if GRAPH_PATH.exists():
        GRAPH_PATH.unlink()


def ingest(root: Path | None = None, case_id: str = "CASE-01", reset: bool = True) -> dict:
    if reset:
        reset_storage()
        # recreate tables after removing db
        Base.metadata.create_all(bind=engine)

    parser = UFDRParser(root)
    parsed = parser.parse()

    with session_scope() as session:
        device = Device(
            case_id=case_id,
            device_make="Samsung",
            device_model="Galaxy S21",
            owner_name="John Doe",
        )
        session.add(device)
        session.flush()

        contact_map: Dict[str, Contact] = {}
        for record in parsed.contacts:
            contact = Contact(
                external_id=record.external_id,
                name=record.name,
                phone_number=record.phone_number,
                email=record.email,
                source_app=record.source_app,
                country=record.country,
                device_id=device.device_id,
            )
            session.add(contact)
            session.flush()
            contact_map[record.external_id] = contact

        vector_records: list[VectorRecord] = []
        for record in parsed.messages:
            sender = contact_map.get(record.sender_external_id)
            receiver = contact_map.get(record.receiver_external_id) if record.receiver_external_id else None
            message = Message(
                external_id=record.external_id,
                sender_id=sender.contact_id if sender else None,
                receiver_id=receiver.contact_id if receiver else None,
                timestamp=record.timestamp,
                content=record.content,
                app_name=record.app_name,
                media_path=record.media_path,
                device_id=device.device_id,
            )
            session.add(message)
            session.flush()

            for term in record.keywords:
                keyword = Keyword(term=term, category="suspicious", message_id=message.message_id)
                session.add(keyword)
            if record.media_path:
                media = Media(
                    file_path=record.media_path,
                    file_type=Path(record.media_path).suffix.lstrip("."),
                    timestamp=record.timestamp,
                    message_id=message.message_id,
                )
                session.add(media)

            vector_records.append(
                VectorRecord(
                    message_id=message.message_id,
                    content=record.content,
                    sender=sender.name if sender else "Unknown",
                    timestamp=record.timestamp.isoformat(),
                    app_name=record.app_name,
                )
            )

        for record in parsed.calls:
            caller = contact_map.get(record.caller_external_id)
            callee = contact_map.get(record.callee_external_id)
            call = Call(
                external_id=record.external_id,
                caller_id=caller.contact_id if caller else None,
                callee_id=callee.contact_id if callee else None,
                call_type=record.call_type,
                start_time=record.start_time,
                duration_seconds=record.duration_seconds,
                location=record.location,
                device_id=device.device_id,
            )
            session.add(call)

        for record in parsed.locations:
            contact = contact_map.get(record.contact_external_id)
            location = Location(
                contact_id=contact.contact_id if contact else None,
                latitude=record.latitude,
                longitude=record.longitude,
                timestamp=record.timestamp,
                accuracy_meters=record.accuracy_meters,
            )
            session.add(location)

    # Build search index
    vector_store = VectorStore()
    vector_store.build(vector_records)

    # Build graph
    graph_store = GraphStore()
    for contact in contact_map.values():
        graph_store.add_person(contact.contact_id, contact.name, contact.phone_number)
    with session_scope() as session:
        messages = session.query(Message).all()
        for message in messages:
            keywords = [kw.term for kw in message.keywords]
            graph_store.add_message(
                message_id=message.message_id,
                sender_contact_id=message.sender_id,
                receiver_contact_id=message.receiver_id,
                timestamp=message.timestamp.isoformat(),
                content=message.content,
                keywords=keywords,
            )
        calls = session.query(Call).all()
        for call in calls:
            graph_store.add_call(
                call_id=call.call_id,
                caller_contact_id=call.caller_id,
                callee_contact_id=call.callee_id,
                start_time=call.start_time.isoformat(),
                duration_seconds=call.duration_seconds,
            )
        locations = session.query(Location).all()
        for location in locations:
            graph_store.add_location(
                location_id=location.location_id,
                contact_id=location.contact_id,
                latitude=location.latitude,
                longitude=location.longitude,
                timestamp=location.timestamp.isoformat(),
            )
    graph_store.save()

    return {
        "contacts": len(parsed.contacts),
        "messages": len(parsed.messages),
        "calls": len(parsed.calls),
        "locations": len(parsed.locations),
        "vector_records": len(vector_records),
    }


if __name__ == "__main__":
    result = ingest(root=DATA_DIR, reset=True)
    print(json.dumps({"ingested": result}, indent=2))
