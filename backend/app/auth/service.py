"""Owners, sign-in links, sessions and API tokens (migration 0011, ADR 0020).

- A sign-in link is a random token, sent by email, valid 15 minutes, used once (consumed with
  one conditional UPDATE); at most `MAX_LINKS_PER_HOUR` are issued per address.
- Using it opens a session: a random session token (the HTTP-only cookie) and a random CSRF
  token (returned to the page, sent back in a header on every state-changing request); both are
  stored as SHA-256 digests only. A session lasts 14 days unless revoked.
- An API token belongs to one store, is shown once at creation and stored as a digest.

A principal is who calls: an owner (with the stores they belong to) or a store's API token.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

LINK_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=14)
MAX_LINKS_PER_HOUR = 5
TOKEN_PREFIX = "pa_"  # noqa: S105 - the public prefix of API tokens, not a secret


class AuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def digest(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()


def same(secret: str, stored: bytes) -> bool:
    return hmac.compare_digest(digest(secret), stored)


def normalize(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class Principal:
    kind: Literal["session", "token"]
    store_ids: frozenset[UUID]
    label: str  # the actor recorded in audit entries
    owner_id: UUID | None = None
    session_id: UUID | None = None
    token_id: UUID | None = None
    csrf_hash: bytes | None = None


@dataclass(frozen=True)
class Session:
    token: str  # the cookie
    csrf_token: str
    owner_id: UUID
    email: str
    expires_at: datetime


def _stores(conn: Connection, owner_id: UUID) -> frozenset[UUID]:
    return frozenset(
        conn.execute(
            text("SELECT store_id FROM auth.memberships WHERE owner_id = :o"), {"o": owner_id}
        ).scalars()
    )


def add_owner(engine: Engine, email: str, store_id: UUID) -> UUID:
    """The owner of `email` (created if new), now a member of the store."""
    address = normalize(email)
    with engine.begin() as conn:
        owner_id: UUID = conn.execute(
            text(
                "INSERT INTO auth.owners (owner_id, email) VALUES (:o, :e) "
                "ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING owner_id"
            ),
            {"o": uuid4(), "e": address},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO auth.memberships (owner_id, store_id) VALUES (:o, :s) "
                "ON CONFLICT DO NOTHING"
            ),
            {"o": owner_id, "s": store_id},
        )
    return owner_id


def request_link(engine: Engine, email: str, now: datetime) -> str | None:
    """A sign-in token for the address, or None (no such owner, or too many links lately).
    The caller answers the same either way, so addresses cannot be probed."""
    with engine.begin() as conn:
        owner_id = conn.execute(
            text("SELECT owner_id FROM auth.owners WHERE email = :e"), {"e": normalize(email)}
        ).scalar()
        if owner_id is None:
            return None
        recent = conn.execute(
            text(
                "SELECT count(*) FROM auth.login_links WHERE owner_id = :o AND created_at > :since"
            ),
            {"o": owner_id, "since": now - timedelta(hours=1)},
        ).scalar_one()
        if recent >= MAX_LINKS_PER_HOUR:
            return None
        token = secrets.token_urlsafe(32)
        conn.execute(
            text(
                "INSERT INTO auth.login_links (link_id, owner_id, token_hash, expires_at, "
                "created_at) VALUES (:l, :o, :h, :exp, :now)"
            ),
            {"l": uuid4(), "o": owner_id, "h": digest(token), "exp": now + LINK_TTL, "now": now},
        )
    return token


def open_session(engine: Engine, link_token: str, now: datetime) -> Session:
    """Use a sign-in link (once) and open a session."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "UPDATE auth.login_links l SET used_at = :now FROM auth.owners o "
                "WHERE l.token_hash = :h AND l.used_at IS NULL AND l.expires_at > :now "
                "AND o.owner_id = l.owner_id RETURNING l.owner_id, o.email"
            ),
            {"h": digest(link_token), "now": now},
        ).first()
        if row is None:
            known = conn.execute(
                text("SELECT used_at, expires_at FROM auth.login_links WHERE token_hash = :h"),
                {"h": digest(link_token)},
            ).first()
            if known is None:
                raise AuthError("invalid_link", "the sign-in link is not valid")
            if known.used_at is not None:
                raise AuthError("used_link", "the sign-in link was already used")
            raise AuthError("expired_link", "the sign-in link has expired")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires = now + SESSION_TTL
        conn.execute(
            text(
                "INSERT INTO auth.sessions (session_id, owner_id, token_hash, csrf_hash, "
                "created_at, expires_at, last_seen_at) VALUES (:s, :o, :t, :c, :now, :exp, :now)"
            ),
            {
                "s": uuid4(),
                "o": row.owner_id,
                "t": digest(token),
                "c": digest(csrf),
                "now": now,
                "exp": expires,
            },
        )
    return Session(token, csrf, row.owner_id, row.email, expires)


def session_principal(engine: Engine, session_token: str, now: datetime) -> Principal | None:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "UPDATE auth.sessions s SET last_seen_at = :now FROM auth.owners o "
                "WHERE s.token_hash = :h AND s.revoked_at IS NULL AND s.expires_at > :now "
                "AND o.owner_id = s.owner_id RETURNING s.session_id, s.owner_id, s.csrf_hash, "
                "o.email"
            ),
            {"h": digest(session_token), "now": now},
        ).first()
        if row is None:
            return None
        return Principal(
            kind="session",
            store_ids=_stores(conn, row.owner_id),
            label=f"owner:{row.email}",
            owner_id=row.owner_id,
            session_id=row.session_id,
            csrf_hash=bytes(row.csrf_hash),
        )


def revoke_session(engine: Engine, session_id: UUID, now: datetime) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE auth.sessions SET revoked_at = :now WHERE session_id = :s"),
            {"now": now, "s": session_id},
        )


@dataclass(frozen=True)
class TokenView:
    token_id: UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


def create_api_token(
    engine: Engine, store_id: UUID, name: str, created_by: UUID | None, now: datetime
) -> tuple[TokenView, str]:
    """The new token's view and the token itself (shown once, never stored)."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    view = TokenView(uuid4(), name, token[:10], now, None, None)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO auth.api_tokens (token_id, store_id, name, prefix, token_hash, "
                "created_by, created_at) VALUES (:t, :s, :n, :p, :h, :by, :now)"
            ),
            {
                "t": view.token_id,
                "s": store_id,
                "n": name,
                "p": view.prefix,
                "h": digest(token),
                "by": created_by,
                "now": now,
            },
        )
    return view, token


def list_api_tokens(engine: Engine, store_id: UUID) -> list[TokenView]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT token_id, name, prefix, created_at, last_used_at, revoked_at "
                "FROM auth.api_tokens WHERE store_id = :s ORDER BY created_at, token_id"
            ),
            {"s": store_id},
        ).all()
    return [TokenView(*r) for r in rows]


def revoke_api_token(engine: Engine, store_id: UUID, token_id: UUID, now: datetime) -> bool:
    with engine.begin() as conn:
        done = conn.execute(
            text(
                "UPDATE auth.api_tokens SET revoked_at = :now WHERE store_id = :s AND "
                "token_id = :t AND revoked_at IS NULL"
            ),
            {"now": now, "s": store_id, "t": token_id},
        ).rowcount
    return bool(done)


def token_principal(engine: Engine, token: str, now: datetime) -> Principal | None:
    if not token.startswith(TOKEN_PREFIX):
        return None
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "UPDATE auth.api_tokens SET last_used_at = :now WHERE token_hash = :h AND "
                "revoked_at IS NULL RETURNING token_id, store_id, prefix"
            ),
            {"h": digest(token), "now": now},
        ).first()
    if row is None:
        return None
    return Principal(
        kind="token",
        store_ids=frozenset({row.store_id}),
        label=f"token:{row.prefix}",
        token_id=row.token_id,
    )
