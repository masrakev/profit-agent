"""Audit tools (run_sensitivity, check_reconciliation, get_method) on a golden scenario."""

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from app.agent.tools import ToolContext
from app.agent.tools import audit as audit_module
from app.db import tenant_transaction
from app.detection.models import Candidate, EntityRef, FaultFamily
from tests.test_agent_tools import call, error, fact_views, numbers_outside_facts

pytestmark = pytest.mark.db


@pytest.fixture
def store(golden_stockout: dict[str, Any]) -> dict[str, Any]:
    return golden_stockout


@pytest.fixture
def ctx(app_engine: Engine, store: dict[str, Any]) -> Iterator[ToolContext]:
    with tenant_transaction(app_engine, store["id"]) as conn:
        yield ToolContext.open(conn, store["id"])


def test_run_sensitivity(ctx: ToolContext, store: dict[str, Any]) -> None:
    view = call(ctx, "run_sensitivity", incident_id=store["incident"])
    assert view["version"] == "sensitivity_v1"
    names = [v["name"] for v in view["variants"]]
    assert names == [
        "reference",
        "baseline_minus_7",
        "baseline_plus_7",
        "window_14",
        "window_28",
        "window_42",
    ]
    reference = view["variants"][0]
    assert reference["valid"]
    # The reference variant is the pipeline's own computation: the very same impact fact.
    assert reference["expected_monthly_impact"]["fact_id"] == store["impact_fact"]
    assert reference["top_cause_family"] == "stockout_on_promoted"
    valid = [v for v in view["variants"] if v["valid"]]
    assert len(valid) >= 4
    for v in valid:
        assert v["baseline"]["end_exclusive"] <= v["current"]["start"]
        assert v["expected_monthly_impact"]["kind"] == "estimate"
    assert view["stable"] is (view["unstable_because"] == [])
    assert {f["fact_id"] for f in fact_views(view)} <= ctx.seen_fact_ids
    assert numbers_outside_facts(view) == []
    assert error(ctx, "run_sensitivity", {"incident_id": "inc-000000000000"}) == "not_found"


def test_sensitivity_stability_is_decided_by_code(
    ctx: ToolContext, store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = audit_module.rank_candidates
    calls = {"n": 0}

    def flip_on_third(*args: Any) -> list[Candidate]:
        calls["n"] += 1
        ranked = real(*args)
        if calls["n"] == 3:  # the baseline_plus_7 variant ranks another cause first
            return [
                Candidate(
                    family=FaultFamily.CPA_DRIFT,
                    entity=EntityRef.campaign(store["campaign"]),
                    score=9.0,
                    evidence=("test",),
                ),
                *ranked,
            ]
        return ranked

    monkeypatch.setattr(audit_module, "rank_candidates", flip_on_third)
    view = call(ctx, "run_sensitivity", incident_id=store["incident"])
    assert view["stable"] is False
    assert "top cause differs in baseline_plus_7 from reference" in view["unstable_because"]


def test_check_reconciliation(ctx: ToolContext, store: dict[str, Any]) -> None:
    period = {"start": ctx.data_end - timedelta(days=28), "end": ctx.data_end}
    view = call(ctx, "check_reconciliation", scope={"kind": "store", "id": None}, period=period)
    assert [m["metric"] for m in view["money"]] == [
        "revenue",
        "cogs",
        "fees",
        "refunds",
        "contribution_margin",
    ]
    for m in view["money"]:
        expected = Decimal(m["store_total"]["value"]) - Decimal(m["products_sum"]["value"])
        assert Decimal(m["gap"]["value"]) == expected
        assert m["gap"]["metric"] == "derived.gap"
    gaps_zero = all(Decimal(m["gap"]["value"]) == 0 for m in view["money"])
    assert view["products_reconcile"] is gaps_zero
    assert view["purchases"]
    for p in view["purchases"]:
        attributed = Decimal(p["attributed_purchases"]["value"])
        orders = Decimal(p["orders_with_promoted_products"]["value"])
        assert Decimal(p["gap"]["value"]) == attributed - orders
        assert p["over_attributed"] is (attributed > orders)
        assert p["attributed_per_order"]["unit"] == "ratio"
    one = call(
        ctx,
        "check_reconciliation",
        period=period,
        scope={"kind": "campaign", "id": str(store["campaign"])},
    )
    assert (one["money"], len(one["purchases"]), one["products_reconcile"]) == ([], 1, None)
    assert numbers_outside_facts(view) == []
    assert (
        error(
            ctx,
            "check_reconciliation",
            {"period": period, "scope": {"kind": "campaign", "id": str(uuid4())}},
        )
        == "not_found"
    )
    assert (
        error(
            ctx,
            "check_reconciliation",
            {"period": period, "scope": {"kind": "product", "id": str(uuid4())}},
        )
        == "unsupported_scope"
    )


def test_get_method(ctx: ToolContext, store: dict[str, Any]) -> None:
    incident = call(ctx, "get_method", incident_id=store["incident"])
    assert (incident["kind"], incident["thresholds_version"]) == ("incident", "v1")
    assert (
        incident["attribution_baseline"]["end_exclusive"]
        <= incident["attribution_current"]["start"]
    )
    cover = next(
        d for d in incident["detectors"] if d["detector"] == "product_cover_below_lead_time"
    )
    assert cover["sections"] == ["inventory_cover"]
    assert {p["name"] for p in cover["parameters"]} >= {"inventory_cover.persist_days"}
    assert all(isinstance(p["value"], str) for d in incident["detectors"] for p in d["parameters"])
    impact = call(ctx, "get_method", fact_id=store["impact_fact"])
    assert impact["formula"] == "expected_monthly_impact"
    assert impact["estimate_method"] == "block_bootstrap_shapley_v1"
    assert "bootstrap" in impact["description"]
    assert impact["parent_roles"] == ["symptom_fact"]
    period = {"start": ctx.data_end - timedelta(days=28), "end": ctx.data_end}
    net = call(
        ctx, "get_facts", metric="net_profit", scope={"kind": "store", "id": None}, period=period
    )["fact"]
    registered = call(ctx, "get_method", fact_id=net["fact_id"])
    assert (registered["formula"], registered["formula_version"]) == ("net_profit", "v1")
    assert registered["inputs"] == ["contribution_after_ads", "fixed_costs"]
    assert numbers_outside_facts(incident) == []
    assert error(ctx, "get_method", {"fact_id": 999999999}) == "not_found"
    assert error(ctx, "get_method", {}) == "invalid_arguments"
    assert error(ctx, "get_method", {"fact_id": 1, "incident_id": store["incident"]}) == (
        "invalid_arguments"
    )
    assert error(ctx, "get_method", {"incident_id": "inc-000000000000"}) == "not_found"
