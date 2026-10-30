"""The store's journal: incidents, decisions, approvals, actions and outcomes in time order
(Task 4 B5, SPEC section 0: "journal")."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text


class JournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    at: datetime
    kind: str  # incident | decision | approval | action | outcome
    id: str
    summary: dict[str, Any]


QUERIES = {
    "incident": (
        "SELECT updated_at AS at, incident_id AS id, jsonb_build_object('category', category, "
        "'alert', alert, 'first_seen', first_seen, 'last_seen', last_seen) AS summary "
        "FROM incidents WHERE store_id = :s"
    ),
    "decision": (
        "SELECT created_at AS at, decision_id::text AS id, jsonb_build_object('cause', cause, "
        "'entity', entity, 'status', status, 'recommended', recommended_option_id, "
        "'incident_id', incident_id) AS summary FROM decisions WHERE store_id = :s"
    ),
    "approval": (
        "SELECT created_at AS at, approval_id::text AS id, jsonb_build_object('decision_id', "
        "decision_id, 'verdict', verdict, 'option_id', option_id, 'channel', channel, 'actor', "
        "actor) AS summary FROM approvals WHERE store_id = :s"
    ),
    "action": (
        "SELECT COALESCE(executed_at, created_at) AS at, action_id::text AS id, "
        "jsonb_build_object('decision_id', decision_id, 'kind', kind, 'campaign_id', "
        "campaign_id, 'provider', provider, 'status', status, 'rollback_of', rollback_of, "
        "'before', before_state, 'after', after_state, 'error', last_error) AS summary "
        "FROM actions WHERE store_id = :s"
    ),
    "outcome": (
        "SELECT created_at AS at, outcome_id::text AS id, jsonb_build_object('decision_id', "
        "decision_id, 'action_id', action_id, 'status', status, 'method', method, "
        "'window_start', window_start, 'window_end', window_end, 'effect_fact_id', "
        "effect_fact_id, 'reason', payload->>'reason') AS summary FROM outcomes WHERE store_id = :s"
    ),
}


def journal(conn: Connection, store_id: UUID, limit: int = 500) -> list[JournalEntry]:
    entries = [
        JournalEntry(at=row.at, kind=kind, id=row.id, summary=dict(row.summary))
        for kind, sql in QUERIES.items()
        for row in conn.execute(text(sql), {"s": store_id})
    ]
    entries.sort(key=lambda e: (e.at, list(QUERIES).index(e.kind)))
    return entries[-limit:]
