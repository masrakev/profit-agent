"""The store's journal: incidents, decisions, approvals, actions and outcomes in time order
(Task 4 B5, SPEC section 0: "journal").

Each entry names what it is about (`entities`, as references the API resolves to names): an
incident its campaigns and products, a decision its entity, an approval or an outcome its
decision's, an action its campaign. A budget change carries the daily budget before and after as
exact facts (`budget_before_fact_id`, `budget_after_fact_id`), made from the state the platform
read back; raw amounts never leave as plain numbers.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from app.causal.verdict import consistency, verdict_text
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.engine import FactEngine
from app.facts.model import Fact, FactKind, FactStatus, Period, Scope, Unit

BUDGET_BEFORE = "action.budget.before"
BUDGET_AFTER = "action.budget.after"
MINOR = Decimal(100)
CENT = Decimal("0.01")


class JournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    at: datetime
    kind: str  # incident | decision | approval | action | outcome
    id: str
    summary: dict[str, Any]
    entities: list[str] = []  # what it is about: references such as "campaign:<id>"


QUERIES = {
    "incident": (
        "SELECT updated_at AS at, incident_id AS id, jsonb_build_object('category', category, "
        "'alert', alert, 'first_seen', first_seen, 'last_seen', last_seen, 'entities', "
        "payload->'entities') AS summary FROM incidents WHERE store_id = :s"
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
        "effect_fact_id, 'predicted_fact_id', payload->'predicted_fact_id', 'reason', "
        "payload->>'reason', 'predicted', payload->'predicted', 'effect', payload->'effect') "
        "AS summary FROM outcomes WHERE store_id = :s"
    ),
}


def _outcome(summary: dict[str, Any]) -> dict[str, Any]:
    """An outcome says whether its prediction held (`verdict`, in words in `verdict_text`); the
    quantiles it was judged on stay in the outcome (facts carry the numbers)."""
    found = consistency(summary)
    out = {k: v for k, v in summary.items() if k not in ("predicted", "effect")}
    return {**out, "verdict": found.value if found else None, "verdict_text": verdict_text(found)}


def budget_fact(
    engine: FactEngine,
    store_id: UUID,
    currency: str,
    *,
    formula_id: str,
    action_id: str,
    campaign_id: UUID,
    day: date,
    minor: int,
) -> int:
    """The campaign's daily budget the platform read back around an action, as an exact fact
    (the same action and amount always give the same fact)."""
    fact = Fact(
        store_id=store_id,
        formula_id=formula_id,
        formula_version=1,
        kind=FactKind.EXACT,
        scope=Scope.campaign(campaign_id),
        period=Period.days(day, day + timedelta(days=1)),
        status=FactStatus.DEFINED,
        value=(Decimal(minor) / MINOR).quantize(CENT),
        unit=Unit.MONEY,
        currency=currency,
        inputs_hash=sha256_hex(
            canonical_json({"formula": formula_id, "action": action_id, "minor": minor})
        ),
    )
    found = engine.persist(engine.adopt(fact)).id
    assert found is not None
    return found


def _action(
    conn: Connection, store_id: UUID, currency: str, at: datetime, id_: str, s: dict[str, Any]
) -> dict[str, Any]:
    """A budget change's amounts become facts; the read-back states keep only their status."""
    before, after = s.get("before") or {}, s.get("after") or {}
    out = {
        **s,
        "before": {k: v for k, v in before.items() if k != "daily_budget_minor"} or None,
        "after": {k: v for k, v in after.items() if k != "daily_budget_minor"} or None,
    }
    if s.get("kind") != "change_budget" or s.get("campaign_id") is None:
        return out
    effective = after.get("effective_date")
    day = date.fromisoformat(str(effective)) if effective else at.date()
    engine = FactEngine(conn, store_id)
    for name, state, formula in (
        ("budget_before_fact_id", before, BUDGET_BEFORE),
        ("budget_after_fact_id", after, BUDGET_AFTER),
    ):
        minor = state.get("daily_budget_minor")
        out[name] = (
            None
            if minor is None
            else budget_fact(
                engine,
                store_id,
                currency,
                formula_id=formula,
                action_id=id_,
                campaign_id=UUID(str(s["campaign_id"])),
                day=day,
                minor=int(minor),
            )
        )
    return out


def _entities(kind: str, summary: dict[str, Any], decided: dict[str, str]) -> list[str]:
    if kind == "incident":
        return [
            f"{e['kind']}:{e['id']}"
            for e in summary.get("entities") or []
            if e.get("kind") and e.get("id")
        ]
    if kind == "decision":
        entity = str(summary.get("entity") or "")
        return [entity] if ":" in entity else []
    if kind == "action" and summary.get("campaign_id"):
        return [f"campaign:{summary['campaign_id']}"]
    entity = decided.get(str(summary.get("decision_id")), "")
    return [entity] if ":" in entity else []


def journal(conn: Connection, store_id: UUID, limit: int = 500) -> list[JournalEntry]:
    found = conn.execute(
        text("SELECT currency FROM stores WHERE store_id = :s"), {"s": store_id}
    ).scalar()
    if found is None:  # no such store (or not visible to this tenant): nothing happened in it
        return []
    currency = str(found)
    decided = {
        str(d): str(e)
        for d, e in conn.execute(
            text("SELECT decision_id, entity FROM decisions WHERE store_id = :s"), {"s": store_id}
        )
    }
    entries = []
    for kind, sql in QUERIES.items():
        for row in conn.execute(text(sql), {"s": store_id}):
            summary = dict(row.summary)
            entities = _entities(kind, summary, decided)
            if kind == "outcome":
                summary = _outcome(summary)
            elif kind == "action":
                summary = _action(conn, store_id, currency, row.at, row.id, summary)
            elif kind == "incident":
                summary.pop("entities", None)
            entries.append(
                JournalEntry(at=row.at, kind=kind, id=row.id, summary=summary, entities=entities)
            )
    entries.sort(key=lambda e: (e.at, list(QUERIES).index(e.kind)))
    return entries[-limit:]
