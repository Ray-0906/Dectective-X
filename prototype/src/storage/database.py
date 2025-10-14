from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from src.config import DB_PATH


def _default_engine_url() -> str:
    return f"sqlite:///{DB_PATH}"  # SQLite is sufficient for hackathon prototype


engine = create_engine(_default_engine_url(), echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(64))
    device_make: Mapped[Optional[str]] = mapped_column(String(128))
    device_model: Mapped[Optional[str]] = mapped_column(String(128))
    owner_name: Mapped[Optional[str]] = mapped_column(String(128))

    contacts: Mapped[list[Contact]] = relationship(back_populates="device")  # type: ignore[name-defined]
    messages: Mapped[list[Message]] = relationship(back_populates="device")  # type: ignore[name-defined]
    calls: Mapped[list[Call]] = relationship(back_populates="device")  # type: ignore[name-defined]


class Contact(Base):
    __tablename__ = "contacts"

    contact_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(128))
    phone_number: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(128))
    source_app: Mapped[Optional[str]] = mapped_column(String(64))
    country: Mapped[Optional[str]] = mapped_column(String(64))
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.device_id"))

    device: Mapped[Device] = relationship(back_populates="contacts")
    sent_messages: Mapped[list[Message]] = relationship(back_populates="sender", foreign_keys="Message.sender_id")
    received_messages: Mapped[list[Message]] = relationship(back_populates="receiver", foreign_keys="Message.receiver_id")
    calls_made: Mapped[list[Call]] = relationship(back_populates="caller", foreign_keys="Call.caller_id")
    calls_received: Mapped[list[Call]] = relationship(back_populates="callee", foreign_keys="Call.callee_id")


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.contact_id"))
    receiver_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("contacts.contact_id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    content: Mapped[str] = mapped_column(String)
    app_name: Mapped[Optional[str]] = mapped_column(String(64))
    media_path: Mapped[Optional[str]] = mapped_column(String(256))
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.device_id"))

    sender: Mapped[Contact] = relationship(foreign_keys=[sender_id], back_populates="sent_messages")
    receiver: Mapped[Optional[Contact]] = relationship(foreign_keys=[receiver_id], back_populates="received_messages")
    device: Mapped[Device] = relationship(back_populates="messages")
    keywords: Mapped[list[Keyword]] = relationship(back_populates="message")  # type: ignore[name-defined]


class Call(Base):
    __tablename__ = "calls"

    call_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    caller_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.contact_id"))
    callee_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.contact_id"))
    call_type: Mapped[str] = mapped_column(String(16))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    location: Mapped[Optional[str]] = mapped_column(String(128))
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.device_id"))

    caller: Mapped[Contact] = relationship(foreign_keys=[caller_id], back_populates="calls_made")
    callee: Mapped[Contact] = relationship(foreign_keys=[callee_id], back_populates="calls_received")
    device: Mapped[Device] = relationship(back_populates="calls")


class Media(Base):
    __tablename__ = "media_files"

    media_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(256))
    file_type: Mapped[Optional[str]] = mapped_column(String(32))
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sha256_hash: Mapped[Optional[str]] = mapped_column(String(128))
    message_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("messages.message_id"))

    message: Mapped[Optional[Message]] = relationship(back_populates="media")  # type: ignore[attr-defined]


Message.media = relationship(Media, back_populates="message", uselist=False)  # type: ignore[attr-defined]


class Location(Base):
    __tablename__ = "locations"

    location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.contact_id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accuracy_meters: Mapped[Optional[float]] = mapped_column(Float)

    contact: Mapped[Contact] = relationship()


class Keyword(Base):
    __tablename__ = "keywords"

    keyword_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[Optional[str]] = mapped_column(String(64))
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey("messages.message_id"))

    message: Mapped[Message] = relationship(back_populates="keywords")


Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
