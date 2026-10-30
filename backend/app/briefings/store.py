"""Persisted briefings (migration 0008). Use inside the store's tenant transaction."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.briefings.models import BriefingContent, BriefingKind
from app.domain.audit import append_audit


@dataclass(frozen=True)
class Narration:
    """How the narrative was written: by the model, or not at all (facts only)."""

    narrative: str | None
    prompt_version: str | None = None
    model: str | None = None
    attempts: int = 0
    fallback_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)

    @property
    def status(self) -> str:
        return "narrated" if self.narrative else "facts_only"


FACTS_ONLY = Narration(narrative=None)


@dataclass(frozen=True)
class BriefingRecord:
    briefing_id: UUID
    store_id: UUID
    kind: BriefingKind
    local_date: date
    status: str
    content: BriefingContent
    narration: Narration
    created_at: datetime


def save(
    conn: Connection,
    store_id: UUID,
    content: BriefingContent,
    narration: Narration,
    *,
    local_date: date,
) -> tuple[UUID, bool]:
    """Insert the briefing; `(id, False)` when one already exists for that kind and day."""
    briefing_id = uuid4()
    inserted = conn.execute(
        text(
            "INSERT INTO briefings (briefing_id, store_id, kind, local_date, period_start, "
            "period_end, status, content, narrative, fact_ids, prompt_version, model, attempts, "
            "fallback_reason, input_tokens, output_tokens, cost_usd) VALUES (:b, :s, :k, :d, "
            ":ps, :pe, :st, CAST(:c AS jsonb), :n, :f, :pv, :m, :a, :fr, :it, :ot, :cost) "
            "ON CONFLICT (store_id, kind, local_date) DO NOTHING RETURNING briefing_id"
        ),
        {
            "b": briefing_id,
            "s": store_id,
            "k": content.kind.value,
            "d": local_date,
            "ps": content.period_start,
            "pe": content.period_end,
            "st": narration.status,
            "c": json.dumps(content.model_dump(mode="json")),
            "n": narration.narrative,
            "f": list(content.fact_ids),
            "pv": narration.prompt_version,
            "m": narration.model,
            "a": narration.attempts,
            "fr": narration.fallback_reason,
            "it": narration.input_tokens,
            "ot": narration.output_tokens,
            "cost": narration.cost_usd,
        },
    ).scalar()
    if inserted is None:
        existing = conn.execute(
            text(
                "SELECT briefing_id FROM briefings WHERE store_id = :s AND kind = :k "
                "AND local_date = :d"
            ),
            {"s": store_id, "k": content.kind.value, "d": local_date},
        ).scalar_one()
        return existing, False
    append_audit(
        conn,
        store_id,
        actor="system:briefings",
        action="briefing.generated",
        payload={
            "briefing_id": str(briefing_id),
            "kind": content.kind.value,
            "local_date": local_date,
            "status": narration.status,
            "facts": len(content.fact_ids),
            "cost_usd": str(narration.cost_usd),
        },
    )
    return briefing_id, True


def exists(conn: Connection, store_id: UUID, kind: BriefingKind, local_date: date) -> bool:
    return bool(
        conn.execute(
            text("SELECT 1 FROM briefings WHERE store_id = :s AND kind = :k AND local_date = :d"),
            {"s": store_id, "k": kind.value, "d": local_date},
        ).scalar()
    )


def _record(r: Any) -> BriefingRecord:
    return BriefingRecord(
        briefing_id=r.briefing_id,
        store_id=r.store_id,
        kind=BriefingKind(r.kind),
        local_date=r.local_date,
        status=r.status,
        content=BriefingContent.model_validate(r.content),
        narration=Narration(
            narrative=r.narrative,
            prompt_version=r.prompt_version,
            model=r.model,
            attempts=r.attempts,
            fallback_reason=r.fallback_reason,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cost_usd=r.cost_usd,
        ),
        created_at=r.created_at,
    )


def get(conn: Connection, store_id: UUID, briefing_id: UUID) -> BriefingRecord | None:
    row = conn.execute(
        text("SELECT * FROM briefings WHERE store_id = :s AND briefing_id = :b"),
        {"s": store_id, "b": briefing_id},
    ).first()
    return None if row is None else _record(row)


def list_briefings(
    conn: Connection, store_id: UUID, *, kind: BriefingKind | None = None, limit: int = 50
) -> list[BriefingRecord]:
    rows = conn.execute(
        text(
            "SELECT * FROM briefings WHERE store_id = :s AND (CAST(:k AS text) IS NULL OR "
            "kind = :k) ORDER BY created_at DESC, briefing_id LIMIT :n"
        ),
        {"s": store_id, "k": kind.value if kind else None, "n": limit},
    ).all()
    return [_record(r) for r in rows]
