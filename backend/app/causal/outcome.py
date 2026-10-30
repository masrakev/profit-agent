"""Measure what an executed action earned (Task 4 B4, ADR 0018).

Treated series: the acted campaign's daily contribution after ads (its promoted products'
contribution margin minus its spend). Donors: every other campaign that shares no product with
it (same series), and every product it does not promote (daily contribution margin). The effect
over the observation window (default 7 days from the day the action took effect) is estimated by
synthetic control (`app.causal.control`), stored as an `estimate` fact with the campaign's exact
facts before and after as parents, next to the twin's prediction for the same window (an
estimate fact too, `predicted_fact_id`). The decision becomes `measured`; an abstention leaves it
`executed`, to be measured again later.
"""

import json
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import Connection, text

from app.causal.control import ControlResult, FloatArray, synthetic_control
from app.decisions.store import DecisionStatus, get, transition
from app.detection.series import StoreSeries, load_series
from app.domain.audit import append_audit
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.engine import FactEngine
from app.facts.model import Fact, FactKind, FactStatus, Lineage, ParentRef, Period, Scope, Unit
from app.twin import Action, Scenario, fit_twin, simulate
from app.twin.facts import input_facts, simulation_facts

METHOD = "synthetic_control_v1"
FORMULA = "outcome.effect.contribution_after_ads"
WINDOW_DAYS = 7
PRE_DAYS = 84  # history searched for the regime the action interrupts (the fit: 42 at most)
CENT = Decimal("0.01")


def _daily(values: list[Decimal]) -> FloatArray:
    return np.array([float(v) for v in values], dtype=np.float64)


def _campaign_series(series: StoreSeries, campaign: UUID) -> FloatArray:
    c = series.campaigns[campaign]
    out = -_daily(c.spend)
    for pid in c.promoted:
        p = series.products[pid]
        out += _daily(p.revenue) - _daily(p.cogs) - _daily(p.fees) - _daily(p.refunds)
    return out


def donor_matrix(series: StoreSeries, campaign: UUID) -> tuple[FloatArray, list[str]]:
    promoted = set(series.campaigns[campaign].promoted)
    columns: list[FloatArray] = []
    names: list[str] = []
    for cid, c in sorted(series.campaigns.items()):
        if cid != campaign and not promoted & set(c.promoted):
            columns.append(_campaign_series(series, cid))
            names.append(f"campaign:{cid}")
    for pid, p in sorted(series.products.items()):
        if pid not in promoted:
            columns.append(_daily(p.revenue) - _daily(p.cogs) - _daily(p.fees) - _daily(p.refunds))
            names.append(f"product:{pid}")
    matrix = np.column_stack(columns) if columns else np.zeros((series.days, 0))
    return matrix, names


def _decimal(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(CENT, rounding=ROUND_HALF_EVEN)


def _prediction(
    engine: FactEngine,
    store_id: UUID,
    decision_as_of: date,
    actions: list[dict[str, Any]],
    days: int,
) -> tuple[dict[str, str] | None, int | None]:
    """The twin's net-profit change for the approved option over the observation window, as
    the twin saw the store when the decision was proposed; persisted as an estimate fact."""
    try:
        model = fit_twin(engine.conn, store_id, as_of=decision_as_of)
    except ValueError:
        return None, None
    scenario = Scenario(
        actions=tuple(Action.model_validate(a) for a in actions), horizon_days=max(days, 7)
    )
    sim = simulate(model, scenario)
    if sim.change.get("net_profit") is None:
        return None, None
    fact = simulation_facts(engine, model, sim, input_facts(engine, model, sim))[
        "twin.change.net_profit"
    ]
    assert fact.p10 is not None
    assert fact.p50 is not None
    assert fact.p90 is not None
    quantiles = {"p10": str(fact.p10), "p50": str(fact.p50), "p90": str(fact.p90)}
    return quantiles, fact.id


def measure(
    conn: Connection,
    store_id: UUID,
    action_id: UUID,
    *,
    window_days: int = WINDOW_DAYS,
    seed: int | None = None,
) -> dict[str, Any]:
    """Measure one executed action; returns the outcome row's payload with its status."""
    action = conn.execute(
        text(
            "SELECT decision_id, option_id, campaign_id, kind, after_state FROM actions "
            "WHERE store_id = :s AND action_id = :a AND status = 'executed'"
        ),
        {"s": store_id, "a": action_id},
    ).first()
    if action is None:
        raise LookupError(f"no executed action {action_id}")
    effective = date.fromisoformat(str((action.after_state or {})["effective_date"]))
    decision = get(conn, store_id, action.decision_id)
    series = load_series(conn, store_id)
    split = series.index(effective)
    first = max(0, split - PRE_DAYS)
    target = _campaign_series(series, action.campaign_id)[first:]
    donors, names = donor_matrix(series, action.campaign_id)
    rng = np.random.default_rng(int(sha256_hex(canonical_json([str(action_id), seed]))[:16], 16))
    result: ControlResult = synthetic_control(
        target, donors[first:], split - first, window_days, rng
    )
    option = decision.option(action.option_id)
    engine = FactEngine(conn, store_id)
    predicted, predicted_fact_id = _prediction(
        engine, store_id, date.fromisoformat(decision.as_of), option.actions, window_days
    )
    payload: dict[str, Any] = {
        "reason": result.reason,
        "pre_r2": f"{result.pre_r2:.4f}" if result.pre_r2 is not None else None,
        "relative_error": (
            f"{result.relative_error:.4f}" if result.relative_error is not None else None
        ),
        "pre_days": result.pre_days,
        "donors": len(names),
        "top_donors": [
            names[i] for i in np.argsort(result.weights)[::-1][:5] if result.weights[i] > 0.01
        ]
        if result.weights
        else [],
        "predicted": predicted,
        "predicted_fact_id": predicted_fact_id,
    }
    window = Period.days(effective, effective + timedelta(days=window_days))
    fact_id = None
    if result.measured and result.effect is not None:
        scope = Scope.campaign(action.campaign_id)
        before = Period.days(effective - timedelta(days=window_days), effective)
        parents = [
            (f"{name}:{m}", engine.fact(m, scope, period))
            for name, period in (("before", before), ("after", window))
            for m in ("promoted_contribution_margin", "ad_spend")
        ]
        for _, parent in parents:
            engine.adopt(parent)
        p10, p50, p90 = (_decimal(x) for x in result.effect)
        fact = Fact(
            store_id=store_id,
            formula_id=FORMULA,
            formula_version=1,
            kind=FactKind.ESTIMATE,
            scope=scope,
            period=window,
            status=FactStatus.DEFINED,
            value=p50,
            p10=p10,
            p50=p50,
            p90=p90,
            method=METHOD,
            unit=Unit.MONEY,
            currency=decision.currency,
            inputs_hash=sha256_hex(
                canonical_json(
                    {
                        "action": str(action_id),
                        "method": METHOD,
                        "window": window_days,
                        "parents": [f.fact_hash for _, f in parents],
                    }
                )
            ),
            lineage=Lineage(
                parents=tuple(ParentRef(role=r, fact_hash=f.fact_hash) for r, f in parents)
            ),
        )
        fact_id = engine.persist(engine.adopt(fact)).id
        payload["effect"] = {"p10": str(p10), "p50": str(p50), "p90": str(p90)}
        payload["actual"] = str(_decimal(result.actual or 0.0))
        payload["counterfactual"] = str(_decimal(result.counterfactual or 0.0))
    status = "measured" if fact_id is not None else "abstained"
    conn.execute(
        text(
            "INSERT INTO outcomes (outcome_id, store_id, decision_id, action_id, status, method, "
            "window_start, window_end, effect_fact_id, payload) VALUES (:o, :s, :d, :a, :st, :m, "
            ":ws, :we, :f, CAST(:p AS jsonb))"
        ),
        {
            "o": uuid4(),
            "s": store_id,
            "d": action.decision_id,
            "a": action_id,
            "st": status,
            "m": METHOD,
            "ws": effective,
            "we": effective + timedelta(days=window_days),
            "f": fact_id,
            "p": json.dumps(payload),
        },
    )
    if status == "measured" and decision.status is DecisionStatus.EXECUTED:
        transition(conn, store_id, action.decision_id, DecisionStatus.MEASURED)
    append_audit(
        conn,
        store_id,
        actor="system:causal",
        action=f"outcome.{status}",
        payload={"action_id": str(action_id), "fact_id": fact_id, **payload},
    )
    return {"status": status, "effect_fact_id": fact_id, **payload}
