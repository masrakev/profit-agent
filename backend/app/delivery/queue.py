"""Deliveries: one row per message and channel, written in the transaction that creates the
message (a briefing, an alert, a decision), so a message is never lost or sent twice.

- web: delivered at once (the web platform reads messages from the API);
- email: pending, sent by the worker; skipped, and recorded, when the store has no address;
- WhatsApp: pending, sent by the worker to the store's verified number; skipped, and recorded,
  when it has none. Goal progress and decision status (done, failed) go to WhatsApp only.
"""

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.settings.models import AlertChannel
from app.settings.repository import StoreSettingsRepository
from app.whatsapp.numbers import verified_number

NO_EMAIL = "no email address is set for this store"
NO_WHATSAPP = "no verified WhatsApp number for this store"


class Subject(StrEnum):
    BRIEFING = "briefing"
    ALERT = "alert"
    DECISION = "decision"
    GOAL_PROGRESS = "goal_progress"  # WhatsApp only: <goal id>:<day>
    DECISION_STATUS = "decision_status"  # WhatsApp only: <decision id>:<status>


def enqueue(
    conn: Connection,
    store_id: UUID,
    subject: Subject,
    subject_id: str,
    *,
    channels: Iterable[AlertChannel],
    recipient: str | None,
    available_at: datetime,
    now: datetime,
) -> list[UUID]:
    created: list[UUID] = []
    for channel in channels:
        status, provider, error, sent_at, to = "pending", None, None, None, recipient
        if channel is AlertChannel.WEB:
            status, provider, sent_at, to = "sent", "web", now, None
        elif channel is AlertChannel.EMAIL and recipient is None:
            status, error = "skipped", NO_EMAIL
        elif channel is AlertChannel.WHATSAPP:
            number = verified_number(conn, store_id)
            to = number.phone if number is not None else None
            if to is None:
                status, error = "skipped", NO_WHATSAPP
        row = conn.execute(
            text(
                "INSERT INTO deliveries (delivery_id, store_id, subject, subject_id, channel, "
                "recipient, status, available_at, provider, last_error, sent_at, created_at) "
                "VALUES (:d, :s, :sub, :sid, :c, :r, :st, :at, :p, :e, :sent, :now) "
                "ON CONFLICT (store_id, subject, subject_id, channel) DO NOTHING "
                "RETURNING delivery_id"
            ),
            {
                "d": uuid4(),
                "s": store_id,
                "sub": subject.value,
                "sid": subject_id,
                "c": channel.value,
                "r": to,
                "st": status,
                "at": available_at,
                "p": provider,
                "e": error,
                "sent": sent_at,
                "now": now,
            },
        ).scalar()
        if row is not None:
            created.append(row)
    return created


def notify(
    conn: Connection,
    store_id: UUID,
    subject: Subject,
    subject_id: str,
    *,
    available_at: datetime,
    now: datetime,
) -> list[UUID]:
    """Deliveries on the store's channels (its alert channels, for every kind of message)."""
    settings = StoreSettingsRepository(conn).get_or_default(store_id)
    return enqueue(
        conn,
        store_id,
        subject,
        subject_id,
        channels=settings.alert_channels,
        recipient=settings.notification_email,
        available_at=available_at,
        now=now,
    )


def notify_whatsapp(
    conn: Connection, store_id: UUID, subject: Subject, subject_id: str, *, now: datetime
) -> list[UUID]:
    """A WhatsApp-only message (goal progress, decision status), when WhatsApp is a channel."""
    settings = StoreSettingsRepository(conn).get_or_default(store_id)
    if AlertChannel.WHATSAPP not in settings.alert_channels:
        return []
    return enqueue(
        conn,
        store_id,
        subject,
        subject_id,
        channels=(AlertChannel.WHATSAPP,),
        recipient=None,
        available_at=now,
        now=now,
    )
