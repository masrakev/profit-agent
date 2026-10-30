"""Export everything a store has: one JSON Lines file per tenant table, in a zip (ADR 0021).

Tables are found at run time (every public table with a `store_id`), so a new one is never
missed, and read under the store's row-level security. Owners and API tokens are included as
metadata; secrets are not: token digests, the encrypted platform tokens.
"""

import base64
import io
import json
import zipfile
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import IO, Any
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from app.db import tenant_transaction
from app.domain.audit import append_audit

SECRET_COLUMNS = {"store_connections": {"wrapped_key", "key_nonce", "ciphertext", "nonce"}}
FORMAT_VERSION = 1


def _json(value: Any) -> Any:
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes | memoryview):
        return base64.b64encode(bytes(value)).decode()
    raise TypeError(f"cannot export {type(value).__name__}")


def tenant_tables(conn: Connection) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT c.table_name FROM information_schema.columns c JOIN "
                "information_schema.tables t ON t.table_schema = c.table_schema AND "
                "t.table_name = c.table_name WHERE c.table_schema = 'public' AND "
                "c.column_name = 'store_id' AND t.table_type = 'BASE TABLE' ORDER BY 1"
            )
        ).scalars()
    )


def _rows(conn: Connection, table: str) -> Iterator[dict[str, Any]]:
    hidden = SECRET_COLUMNS.get(table, set())
    query = text(f'SELECT * FROM "{table}"').execution_options(stream_results=True)
    result = conn.execute(query)
    try:
        for row in result.mappings():
            yield {k: v for k, v in row.items() if k not in hidden}
    finally:
        result.close()


def write_export(
    engine: Engine, store_id: UUID, out: IO[bytes], *, actor: str, now: datetime
) -> dict[str, int]:
    """Write the store's archive to `out`; returns the number of rows per table."""
    counts: dict[str, int] = {}
    with (
        tenant_transaction(engine, store_id) as conn,
        zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive,
    ):
        for table in tenant_tables(conn):
            buffer = io.StringIO()
            n = 0
            for row in _rows(conn, table):
                buffer.write(json.dumps(row, default=_json, sort_keys=True) + "\n")
                n += 1
            counts[table] = n
            archive.writestr(f"{table}.jsonl", buffer.getvalue())
        owners = conn.execute(
            text(
                "SELECT o.email, m.role, m.created_at FROM auth.memberships m JOIN auth.owners o "
                "ON o.owner_id = m.owner_id WHERE m.store_id = :s ORDER BY o.email"
            ),
            {"s": store_id},
        ).mappings()
        tokens = conn.execute(
            text(
                "SELECT name, prefix, created_at, last_used_at, revoked_at FROM auth.api_tokens "
                "WHERE store_id = :s ORDER BY created_at"
            ),
            {"s": store_id},
        ).mappings()
        archive.writestr(
            "access.json",
            json.dumps(
                {"owners": [dict(r) for r in owners], "api_tokens": [dict(r) for r in tokens]},
                default=_json,
                indent=2,
            ),
        )
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format_version": FORMAT_VERSION,
                    "store_id": str(store_id),
                    "exported_at": now.isoformat(),
                    "rows": counts,
                    "secrets_excluded": [
                        "auth token digests",
                        "encrypted platform tokens (store_connections)",
                    ],
                },
                indent=2,
            ),
        )
        append_audit(
            conn,
            store_id,
            actor=actor,
            action="store.exported",
            payload={"tables": len(counts), "rows": sum(counts.values())},
            occurred_at=now,
        )
    return counts
