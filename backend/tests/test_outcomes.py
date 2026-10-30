"""Outcome measurement: synthetic control and measuring executed actions."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pytest
from sqlalchemy import Engine, text

from app.causal.control import (
    project_simplex,
    regime_start,
    simplex_weights,
    synthetic_control,
)
from app.causal.outcome import measure
from app.db import tenant_transaction
from app.decisions.store import DecisionStatus, get
from app.facts.repository import get_facts
from bench.simulator import advance
from tests.action_helpers import Rig, actions, approved, option_set, simulator_store


def test_simplex_projection() -> None:
    w = project_simplex(np.array([0.5, 2.0, -1.0]))
    assert w.sum() == pytest.approx(1.0)
    assert (w >= 0).all()
    assert project_simplex(np.array([0.2, 0.3, 0.5])) == pytest.approx([0.2, 0.3, 0.5])


def test_synthetic_control_recovers_a_known_effect() -> None:
    rng = np.random.default_rng(0)
    days, split, window = 56, 49, 7
    donors = rng.normal(100, 10, size=(days, 4)) + np.linspace(0, 20, days)[:, None]
    target = 0.6 * donors[:, 0] + 0.4 * donors[:, 1] + 5 + rng.normal(0, 1, days)
    target[split:] += 10.0  # the action adds 10 a day
    w, b = simplex_weights(donors[:split], target[:split])
    assert w == pytest.approx([0.6, 0.4, 0, 0], abs=0.05)
    assert b == pytest.approx(5, abs=3)
    result = synthetic_control(target, donors, split, window, np.random.default_rng(1))
    assert result.measured
    assert result.effect is not None
    p10, p50, p90 = result.effect
    assert p10 < p50 < p90  # an 80% interval: on one draw, 70 may fall just outside it
    assert p50 == pytest.approx(70, abs=8)
    assert result.pre_r2 is not None
    assert result.pre_r2 > 0.9


def test_synthetic_control_abstains() -> None:
    rng = np.random.default_rng(2)
    donors = rng.normal(0, 1, size=(56, 3))
    noise = rng.normal(0, 1, 56)
    assert synthetic_control(noise, donors, 52, 7, rng).reason.startswith("too little post")
    assert "no untouched" in synthetic_control(noise, donors[:, :0], 49, 7, rng).reason
    assert "before the action" in synthetic_control(noise, donors, 10, 7, rng).reason
    weak = synthetic_control(noise, donors, 49, 7, rng)
    assert (weak.measured, weak.reason) == (False, "the pre-period fit is too weak")


@pytest.fixture(scope="module")
def sim(app_engine: Engine) -> dict[str, Any]:
    return simulator_store(app_engine, "dev-supplier_cost_increase-05")


@pytest.mark.db
def test_an_executed_pause_is_measured_after_its_window(
    app_engine: Engine, sim: dict[str, Any]
) -> None:
    campaign = sim["campaigns"][0]
    d = approved(app_engine, sim["id"], option_set(campaign, label="measure"))
    Rig(app_engine).executor().run_once()
    [action] = actions(app_engine, sim["id"], d.decision_id)
    assert advance(app_engine, sim["id"], 2) == 108
    with tenant_transaction(app_engine, sim["id"]) as conn:
        early = measure(conn, sim["id"], action.action_id)
    assert (early["status"], early["reason"]) == (
        "abstained",
        "too little post-decision history to measure the window",
    )
    advance(app_engine, sim["id"], 5)
    with tenant_transaction(app_engine, sim["id"]) as conn:
        spend_after = conn.execute(
            text(
                "SELECT coalesce(sum(spend), 0) FROM ad_metrics_daily WHERE store_id = :s AND "
                "campaign_id = :c AND metric_date >= :d"
            ),
            {"s": sim["id"], "c": campaign, "d": action.after_state["effective_date"]},
        ).scalar_one()
        outcome = measure(conn, sim["id"], action.action_id)
        status = get(conn, sim["id"], d.decision_id).status
        rows = (
            conn.execute(
                text("SELECT status FROM outcomes WHERE action_id = :a ORDER BY created_at"),
                {"a": action.action_id},
            )
            .scalars()
            .all()
        )
    assert spend_after == 0  # the simulator really paused the campaign
    assert outcome["predicted"] is not None
    with tenant_transaction(app_engine, sim["id"]) as conn:
        predicted = get_facts(conn, sim["id"], [outcome["predicted_fact_id"]])
    [fact] = predicted.values()
    assert fact.formula_id == "twin.change.net_profit"
    assert fact.p10 is not None
    assert fact.p90 is not None
    assert str(fact.p50) == outcome["predicted"]["p50"]
    assert fact.period.end - fact.period.start == timedelta(days=7)
    assert rows[0] == "abstained"
    if outcome["status"] == "measured":
        assert status is DecisionStatus.MEASURED
        effect = {k: Decimal(v) for k, v in outcome["effect"].items()}
        assert effect["p10"] <= effect["p50"] <= effect["p90"]
        assert outcome["effect_fact_id"] is not None
    else:
        assert status is DecisionStatus.EXECUTED
        assert outcome["reason"] == "the pre-period fit is too weak"
    with tenant_transaction(app_engine, sim["id"]) as conn, pytest.raises(LookupError):
        measure(conn, sim["id"], d.decision_id)


def test_the_fit_starts_at_the_last_break() -> None:
    rng = np.random.default_rng(3)
    step = np.r_[rng.normal(100, 2, 20), rng.normal(40, 2, 22)]
    assert regime_start(step, 7) == 20
    assert regime_start(rng.normal(50, 2, 42), 7) == 0
    late = np.r_[rng.normal(100, 2, 35), rng.normal(40, 2, 7)]
    assert regime_start(late, 7) == 0  # too little history after the break
    # A flat series (spend only) tracked closely is measured, whatever its R-squared.
    days, split = 56, 42
    donors = rng.normal(100, 10, size=(days, 3))
    flat = rng.normal(-48, 3, days)
    flat[split:] += 50
    result = synthetic_control(flat, donors, split, 7, rng)
    assert result.measured
    assert result.relative_error is not None
    assert result.relative_error < 0.5
    assert result.effect is not None
    assert result.effect[0] > 0
