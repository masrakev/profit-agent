"""The owner's WhatsApp number: verified by a code before it may act (Task 8 part B, ADR 0027).

1. The owner enters the number in the store's settings; saving a new one makes it `pending`
   (a changed number starts over, a removed one is forgotten).
2. On request, a six-digit code is sent to it on WhatsApp: at most three an hour, each valid ten
   minutes, kept only as an HMAC digest keyed with the server's secret.
3. The owner types the code on the web: five attempts, then a new code is needed. A verified
   number belongs to one store only.

Only a verified number interacts with a store: the webhook finds the store from the sender with
`store_for` (no tenant is known before), and every other sender gets one polite refusal. The
24-hour customer service window opens when the owner writes (`touch_inbound`).
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from app.domain.audit import append_audit

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 3
WINDOW = timedelta(hours=24)


class NumberError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class NumberState:
    phone: str  # digits, as WhatsApp writes it
    verified: bool
    verified_at: datetime | None
    code_expires_at: datetime | None
    last_inbound_at: datetime | None

    @property
    def e164(self) -> str:
        return f"+{self.phone}"

    def window_open(self, now: datetime) -> bool:
        return self.last_inbound_at is not None and now - self.last_inbound_at < WINDOW


def digits(e164: str) -> str:
    return e164.removeprefix("+")


def _digest(secret: str, store_id: UUID, phone: str, code: str) -> bytes:
    return hmac.new(secret.encode(), f"{store_id}:{phone}:{code}".encode(), hashlib.sha256).digest()


def state(conn: Connection, store_id: UUID) -> NumberState | None:
    row = conn.execute(
        text(
            "SELECT phone, status, verified_at, code_expires_at, last_inbound_at "
            "FROM whatsapp_numbers WHERE store_id = :s"
        ),
        {"s": store_id},
    ).first()
    if row is None:
        return None
    return NumberState(
        row.phone, row.status == "verified", row.verified_at, row.code_expires_at,
        row.last_inbound_at,
    )  # fmt: skip


def sync_number(conn: Connection, store_id: UUID, e164: str | None) -> None:
    """After the settings are saved: a new number is pending, a removed one forgotten."""
    current = state(conn, store_id)
    if e164 is None:
        if current is not None:
            conn.execute(text("DELETE FROM whatsapp_numbers WHERE store_id = :s"), {"s": store_id})
        return
    if current is not None and current.phone == digits(e164):
        return
    conn.execute(
        text(
            "INSERT INTO whatsapp_numbers (store_id, phone, status) VALUES (:s, :p, 'pending') "
            "ON CONFLICT (store_id) DO UPDATE SET phone = :p, status = 'pending', "
            "code_hash = NULL, code_expires_at = NULL, code_attempts = 0, verified_at = NULL, "
            "last_inbound_at = NULL, updated_at = now()"
        ),
        {"s": store_id, "p": digits(e164)},
    )


def start(conn: Connection, store_id: UUID, *, secret: str, now: datetime) -> tuple[str, str]:
    """A new code for the store's number: (the number's digits, the code). Not stored."""
    row = conn.execute(
        text(
            "SELECT phone, status, codes_sent, last_code_at FROM whatsapp_numbers "
            "WHERE store_id = :s FOR UPDATE"
        ),
        {"s": store_id},
    ).first()
    if row is None:
        raise NumberError(409, "no_number", "set a WhatsApp number in the settings first")
    if row.status == "verified":
        raise NumberError(409, "already_verified", "this number is already verified")
    recent = row.last_code_at is not None and now - row.last_code_at < timedelta(hours=1)
    sent = row.codes_sent if recent else 0
    if sent >= MAX_CODES_PER_HOUR:
        raise NumberError(429, "too_many_codes", "three codes an hour at most: try again later")
    code = f"{secrets.randbelow(10**6):06d}"
    conn.execute(
        text(
            "UPDATE whatsapp_numbers SET code_hash = :h, code_expires_at = :exp, "
            "code_attempts = 0, codes_sent = :n, last_code_at = :now, updated_at = :now "
            "WHERE store_id = :s"
        ),
        {
            "h": _digest(secret, store_id, row.phone, code),
            "exp": now + CODE_TTL,
            "n": sent + 1,
            "now": now,
            "s": store_id,
        },
    )
    return row.phone, code


def confirm(
    conn: Connection, store_id: UUID, code: str, *, secret: str, actor: str, now: datetime
) -> NumberState | NumberError:
    """The verified number, or, for a wrong code, the error to raise once the failed attempt is
    committed (other refusals raise at once)."""
    row = conn.execute(
        text(
            "SELECT phone, status, code_hash, code_expires_at, code_attempts "
            "FROM whatsapp_numbers WHERE store_id = :s FOR UPDATE"
        ),
        {"s": store_id},
    ).first()
    if row is None:
        raise NumberError(409, "no_number", "set a WhatsApp number in the settings first")
    if row.status == "verified":
        raise NumberError(409, "already_verified", "this number is already verified")
    if row.code_hash is None or row.code_expires_at is None or row.code_expires_at <= now:
        raise NumberError(422, "expired_code", "the code has expired: ask for a new one")
    if row.code_attempts >= MAX_ATTEMPTS:
        raise NumberError(422, "too_many_attempts", "too many attempts: ask for a new code")
    if not hmac.compare_digest(bytes(row.code_hash), _digest(secret, store_id, row.phone, code)):
        conn.execute(
            text(
                "UPDATE whatsapp_numbers SET code_attempts = code_attempts + 1 WHERE store_id = :s"
            ),
            {"s": store_id},
        )
        return NumberError(422, "invalid_code", "the code does not match")
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    "UPDATE whatsapp_numbers SET status = 'verified', verified_at = :now, "
                    "code_hash = NULL, code_expires_at = NULL, updated_at = :now "
                    "WHERE store_id = :s"
                ),
                {"now": now, "s": store_id},
            )
    except IntegrityError as exc:
        raise NumberError(
            409, "number_taken", "this number is already verified for another store"
        ) from exc
    append_audit(
        conn,
        store_id,
        actor=actor,
        action="whatsapp.number_verified",
        payload={"number_ends_with": row.phone[-4:]},
        occurred_at=now,
    )
    found = state(conn, store_id)
    assert found is not None
    return found


def store_for(engine: Engine, phone: str) -> UUID | None:
    """The store whose verified number wrote, if any (no tenant is known before)."""
    with engine.connect() as conn:
        found: UUID | None = conn.execute(
            text("SELECT whatsapp_store_for(:p)"), {"p": phone}
        ).scalar()
    return found


def verified_number(conn: Connection, store_id: UUID) -> NumberState | None:
    found = state(conn, store_id)
    return found if found is not None and found.verified else None


def touch_inbound(conn: Connection, store_id: UUID, now: datetime | None = None) -> None:
    """The owner wrote: the 24-hour window is open from now."""
    conn.execute(
        text("UPDATE whatsapp_numbers SET last_inbound_at = :now WHERE store_id = :s"),
        {"now": now or datetime.now(UTC), "s": store_id},
    )
