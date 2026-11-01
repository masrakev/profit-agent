"""WhatsApp reply buttons that decide (ADR 0027): signed, single use, one store, 24 hours.

A reply button's id is at most 256 characters, too short for an email approval link's token, so
a button carries a short one: its kind, the id of a link row and an HMAC over the store, the kind
and that id, keyed with the signing secret (`APPROVAL_LINK_SECRET`) and cut to 128 bits.

- `d.<link>.<mac>`: approve a decision's option. The row is an `approval_links` row, the email
  links' own: it names the decision, the option and the verdict, expires after 24 hours, is
  consumed once, and an option beyond the spending caps is never decided from it (the owner gets
  a link to the web confirmation page instead).
- `g.<link>.<mac>`: confirm a goal (a `goal_links` row, 24 hours, once). Confirming a goal
  commits no money: its plan's steps still each need their own approval.
- `o.<decision>`: see a decision's options. Unsigned: it decides nothing and only replies.

A token is bound to its store: one shown to another store's owner, forged, or edited fails its
check before any row is read.
"""

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.decisions.store import LinkClaims, Verdict, create_link, read_link

LINK_TTL = timedelta(hours=24)
Kind = Literal["d", "g", "o"]


class ButtonError(Exception):
    """Not a button of ours, or not this store's."""


@dataclass(frozen=True)
class Button:
    kind: Kind
    ref: UUID  # the link row (d, g) or the decision (o)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _mac(secret: str, store_id: UUID, kind: str, ref: UUID) -> str:
    message = f"wa:{kind}:{store_id}:{ref}".encode()
    return _b64(hmac.new(secret.encode(), message, hashlib.sha256).digest()[:16])


def _signed(secret: str, store_id: UUID, kind: Kind, ref: UUID) -> str:
    return f"{kind}.{_b64(ref.bytes)}.{_mac(secret, store_id, kind, ref)}"


def approve_button(
    conn: Connection,
    store_id: UUID,
    decision_id: UUID,
    option_id: str,
    *,
    secret: str,
    now: datetime | None = None,
) -> str:
    """A new single-use approval link for the option, as a button id."""
    now = now or datetime.now(UTC)
    token = create_link(
        conn, store_id, decision_id, option_id, Verdict.APPROVED, secret=secret, now=now
    )
    return _signed(secret, store_id, "d", read_link(token, secret=secret, now=now).link_id)


def goal_button(
    conn: Connection, store_id: UUID, goal_id: UUID, *, secret: str, now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    link_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO goal_links (link_id, store_id, goal_id, expires_at, created_at) "
            "VALUES (:l, :s, :g, :exp, :now)"
        ),
        {"l": link_id, "s": store_id, "g": goal_id, "exp": now + LINK_TTL, "now": now},
    )
    return _signed(secret, store_id, "g", link_id)


def options_button(decision_id: UUID) -> str:
    return f"o.{_b64(decision_id.bytes)}"


def parse(button_id: str, store_id: UUID, *, secret: str) -> Button:
    """The button, if it is ours and this store's; `ButtonError` otherwise."""
    parts = button_id.split(".")
    try:
        kind, ref = parts[0], UUID(bytes=_unb64(parts[1]))
    except (IndexError, ValueError) as exc:
        raise ButtonError("not a button of ours") from exc
    if kind == "o" and len(parts) == 2:
        return Button("o", ref)
    if kind not in ("d", "g") or len(parts) != 3:
        raise ButtonError("not a button of ours")
    if not hmac.compare_digest(parts[2], _mac(secret, store_id, kind, ref)):
        raise ButtonError("the button's signature does not match")
    return Button("d" if kind == "d" else "g", ref)


@dataclass(frozen=True)
class GoalLink:
    link_id: UUID
    goal_id: UUID


def consume_goal_link(
    conn: Connection, store_id: UUID, link_id: UUID, now: datetime | None = None
) -> GoalLink | None:
    """Mark the goal link used, once; None when it was already used, has expired or is none."""
    row = conn.execute(
        text(
            "UPDATE goal_links SET used_at = :now WHERE store_id = :s AND link_id = :l "
            "AND used_at IS NULL AND expires_at > :now RETURNING link_id, goal_id"
        ),
        {"now": now or datetime.now(UTC), "s": store_id, "l": link_id},
    ).first()
    return None if row is None else GoalLink(row.link_id, row.goal_id)


def approval_claims(conn: Connection, store_id: UUID, link_id: UUID) -> LinkClaims | None:
    """The approval link a `d` button names, as an email link's claims (its row decides)."""
    row = conn.execute(
        text(
            "SELECT link_id, store_id, decision_id, option_id, verdict, expires_at "
            "FROM approval_links WHERE store_id = :s AND link_id = :l"
        ),
        {"s": store_id, "l": link_id},
    ).first()
    if row is None:
        return None
    return LinkClaims(
        link_id=row.link_id,
        store_id=row.store_id,
        decision_id=row.decision_id,
        option_id=row.option_id,
        verdict=Verdict(row.verdict),
        expires_at=row.expires_at,
    )
