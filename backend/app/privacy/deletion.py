"""Delete a store and everything of it (ADR 0021).

The database part is one SECURITY DEFINER function (`delete_store`, migration 0013), run in
the store's own tenant transaction: every row of every tenant table, the store, its owner
memberships and API tokens (they cascade). Outside the database: recorded model exchanges
(cassettes) that name the store. Model traces live in `investigation_steps` (deleted with the
rest); the spend ledger names no store. The deletion is recorded in `control.store_deletions`.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine, text

from app.db import tenant_transaction


@dataclass(frozen=True)
class Deletion:
    store_id: UUID
    rows: dict[str, int]
    cassettes: int


def remove_cassettes(directory: Path, store_id: UUID) -> int:
    """Delete recorded exchanges that name the store (synthetic stores only ever have any)."""
    if not directory.exists():
        return 0
    removed = 0
    needle = str(store_id)
    for path in sorted(directory.rglob("*.json")):
        if needle in path.read_text(encoding="utf-8", errors="replace"):
            path.unlink()
            removed += 1
    return removed


def delete_store(engine: Engine, store_id: UUID, *, actor: str, cassette_dir: Path) -> Deletion:
    with tenant_transaction(engine, store_id) as conn:
        counts = conn.execute(
            text("SELECT delete_store(:s, :a)"), {"s": store_id, "a": actor}
        ).scalar_one()
    rows = {
        str(k): int(v)
        for k, v in (counts if isinstance(counts, dict) else json.loads(counts)).items()
    }
    return Deletion(store_id, rows, remove_cassettes(cassette_dir, store_id))
