"""Persist and read an investigation's step trace (migration 0012).

Each step is written in its own short tenant transaction, as it happens, so another connection
(the events stream) sees it at once.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from app.agent.steps import Sink, Step
from app.db import tenant_transaction

FINAL = frozenset({"done", "failed"})


def recorder(engine: Engine, store_id: UUID, investigation_id: UUID) -> Sink:
    seq = 0

    def record(step: Step) -> None:
        nonlocal seq
        seq += 1
        with tenant_transaction(engine, store_id) as conn:
            conn.execute(
                text(
                    "INSERT INTO investigation_steps (store_id, investigation_id, seq, kind, "
                    "name, detail) VALUES (:s, :i, :n, :k, :name, CAST(:d AS jsonb))"
                ),
                {
                    "s": store_id,
                    "i": investigation_id,
                    "n": seq,
                    "k": step.kind,
                    "name": step.name,
                    "d": json.dumps(step.detail, default=str),
                },
            )

    return record


@dataclass(frozen=True)
class StoredStep:
    seq: int
    kind: str
    name: str | None
    detail: dict[str, Any]
    created_at: datetime


def steps_after(
    conn: Connection, store_id: UUID, investigation_id: UUID, after: int = 0
) -> list[StoredStep]:
    rows = conn.execute(
        text(
            "SELECT seq, kind, name, detail, created_at FROM investigation_steps WHERE "
            "store_id = :s AND investigation_id = :i AND seq > :after ORDER BY seq"
        ),
        {"s": store_id, "i": investigation_id, "after": after},
    ).all()
    return [StoredStep(r.seq, r.kind, r.name, dict(r.detail), r.created_at) for r in rows]
