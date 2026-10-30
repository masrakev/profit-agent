"""A store's platform connections (Meta, Shopify): account id and an encrypted access token.

The token is sealed before it reaches the database and opened only where it is used (the
executor's Meta adapter for that store); it is never returned by the API or exported.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, text

from app.config import Settings
from app.privacy.crypto import CryptoError, MasterKey, Sealed, open_sealed, seal

PROVIDERS = ("meta", "shopify")


def master_key(settings: Settings) -> MasterKey:
    if settings.token_encryption_key is None:
        raise CryptoError("TOKEN_ENCRYPTION_KEY is not set: platform tokens cannot be stored")
    return MasterKey.from_base64(
        settings.token_encryption_key_id, settings.token_encryption_key.get_secret_value()
    )


@dataclass(frozen=True)
class ConnectionView:
    provider: str
    account_id: str
    key_id: str
    created_at: datetime
    updated_at: datetime


def save_connection(
    conn: Connection,
    store_id: UUID,
    provider: str,
    account_id: str,
    token: str,
    master: MasterKey,
    now: datetime,
) -> ConnectionView:
    sealed = seal(master, store_id, provider, token)
    row = conn.execute(
        text(
            "INSERT INTO store_connections (store_id, provider, account_id, key_id, wrapped_key, "
            "key_nonce, ciphertext, nonce, created_at, updated_at) VALUES (:s, :p, :a, :k, :w, "
            ":kn, :c, :n, :now, :now) ON CONFLICT (store_id, provider) DO UPDATE SET "
            "account_id = EXCLUDED.account_id, key_id = EXCLUDED.key_id, wrapped_key = "
            "EXCLUDED.wrapped_key, key_nonce = EXCLUDED.key_nonce, ciphertext = "
            "EXCLUDED.ciphertext, nonce = EXCLUDED.nonce, updated_at = EXCLUDED.updated_at "
            "RETURNING created_at, updated_at"
        ),
        {
            "s": store_id,
            "p": provider,
            "a": account_id,
            "k": sealed.key_id,
            "w": sealed.wrapped_key,
            "kn": sealed.key_nonce,
            "c": sealed.ciphertext,
            "n": sealed.nonce,
            "now": now,
        },
    ).one()
    return ConnectionView(provider, account_id, sealed.key_id, row.created_at, row.updated_at)


def list_connections(conn: Connection, store_id: UUID) -> list[ConnectionView]:
    rows = conn.execute(
        text(
            "SELECT provider, account_id, key_id, created_at, updated_at FROM store_connections "
            "WHERE store_id = :s ORDER BY provider"
        ),
        {"s": store_id},
    ).all()
    return [ConnectionView(*r) for r in rows]


def delete_connection(conn: Connection, store_id: UUID, provider: str) -> bool:
    return bool(
        conn.execute(
            text("DELETE FROM store_connections WHERE store_id = :s AND provider = :p"),
            {"s": store_id, "p": provider},
        ).rowcount
    )


def credentials(
    conn: Connection, store_id: UUID, provider: str, master: MasterKey
) -> tuple[str, str] | None:
    """(account id, access token) for the store's connection, decrypted; None without one."""
    row = conn.execute(
        text(
            "SELECT account_id, key_id, wrapped_key, key_nonce, ciphertext, nonce FROM "
            "store_connections WHERE store_id = :s AND provider = :p"
        ),
        {"s": store_id, "p": provider},
    ).first()
    if row is None:
        return None
    sealed = Sealed(
        row.key_id,
        bytes(row.wrapped_key),
        bytes(row.key_nonce),
        bytes(row.ciphertext),
        bytes(row.nonce),
    )
    return row.account_id, open_sealed(master, store_id, provider, sealed)
