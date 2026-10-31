"""The lever library and the plan builder (app/goals/levers.py, app/goals/plan.py)."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import numpy as np
import pytest
from sqlalchemy import Engine

from app.db import tenant_transaction
from app.detection.series import ProductSeries, StoreSeries
from app.facts.model import Period, Scope
from app.goals import levers as lv
from app.goals.plan import build, combine, decision_steps, effect, plan_days, reach, search
from app.twin import Action, ActionKind, TwinModel, change_draws, fit_twin
from app.twin.fit import PRIOR_ELASTICITY, fit_curve
from app.twin.model import CampaignModel, Elasticity, ProductModel, Scenario
from bench.generator import generate
from bench.generator.load import load
from bench.scenarios.build import bench_config

AS_OF = date(2026, 10, 1)
WIN, LOSE, EMPTY = UUID(int=1), UUID(int=2), UUID(int=3)
P_WIN, P_LOSE, P_EMPTY, P_LOW = UUID(int=11), UUID(int=12), UUID(int=13), UUID(int=14)


def campaign(
    cid: UUID, promoted: tuple[UUID, ...], a: float, seed: int, b: float = 0.02
) -> CampaignModel:
    rng = np.random.default_rng(seed)
    spend = rng.uniform(40, 160, 60)
    purchases = a * (1 - np.exp(-b * spend)) + rng.normal(0, 0.3, 60)
    return CampaignModel(
        campaign_id=cid,
        promoted=promoted,
        mean_spend=100.0,
        spend_ratios=spend / spend.mean(),
        active_days=60,
        curve=fit_curve(spend, purchases, rng),
    )


def product(pid: UUID, **overrides: Any) -> ProductModel:
    base = ProductModel(
        product_id=pid,
        units_observed=420.0,
        ad_rate=3.0,
        net_price=50.0,
        unit_cost=20.0,
        fee_per_unit=2.0,
        refund_rate=0.05,
        units_per_line=1.0,
        on_hand=10_000.0,
        inflow_rate=10.0,
        elasticity=PRIOR_ELASTICITY,
        lead_time_days=10,
    )
    return replace(base, **overrides)


@pytest.fixture(scope="module")
def model() -> TwinModel:
    estimated = Elasticity(True, -3.0, -0.5, -1.5, 0.2)
    return TwinModel(
        store_id=UUID(int=99),
        currency="USD",
        as_of=AS_OF,
        window_days=42,
        products={
            P_WIN: product(P_WIN, net_price=80.0, unit_cost=20.0),
            P_LOSE: product(P_LOSE, net_price=30.0, unit_cost=24.0, elasticity=estimated),
            P_EMPTY: product(P_EMPTY, on_hand=0.0, inflow_rate=0.0, units_observed=0.0),
            P_LOW: product(P_LOW, on_hand=60.0, inflow_rate=0.0, elasticity=estimated),
        },
        campaigns={
            WIN: campaign(WIN, (P_WIN,), 20.0, 1, b=0.005),
            LOSE: campaign(LOSE, (P_LOSE,), 2.0, 2),
            EMPTY: campaign(EMPTY, (P_EMPTY,), 4.0, 3),
        },
        fixed_daily=50.0,
        fingerprint="plans",
    )


class FakeContext(lv.Context):
    """Facts from a dict: (metric, entity or None, which period) -> value."""

    values: dict[tuple[str, UUID | None, str], float]
    ids: dict[tuple[str, UUID | None, str], int]

    def _key(
        self, metric: str, scope: Scope, period: Period | None
    ) -> tuple[str, UUID | None, str]:
        which = "previous" if period == self.previous else "recent" if period == self.recent else ""
        return (metric, scope.id, which)

    def value(self, metric: str, scope: Scope, period: Period | None = None) -> float | None:
        return self.values.get(self._key(metric, scope, period))

    def id(self, metric: str, scope: Scope, period: Period | None = None) -> int:
        key = self._key(metric, scope, period)
        if key not in self.ids:
            self.ids[key] = 1000 + len(self.ids)
        return self.ids[key]

    def ref(self, metric: str, scope: Scope, period: Period | None = None) -> str:
        return "{{F" + str(self.id(metric, scope, period)) + "}}"


def fake(model: TwinModel, values: dict[tuple[str, UUID | None, str], float]) -> FakeContext:
    end = model.as_of
    ctx = FakeContext(
        model=model,
        horizon=60,
        cap=Decimal("0.30"),
        engine=None,  # type: ignore[arg-type]
        period=Period.days(end - timedelta(days=28), end),
        previous=Period.days(end - timedelta(days=28), end - timedelta(days=14)),
        recent=Period.days(end - timedelta(days=14), end),
        usual=frozenset({P_WIN, P_LOSE, P_EMPTY}),
    )
    ctx.values = values
    ctx.ids = {}
    return ctx


FACTS: dict[tuple[str, UUID | None, str], float] = {
    ("campaign_profit", WIN, ""): 900.0,
    ("campaign_profit", LOSE, ""): -400.0,
    ("campaign_profit", EMPTY, ""): -100.0,
    ("contribution_margin", P_WIN, ""): 3000.0,
    ("revenue", P_WIN, ""): 5000.0,
    ("contribution_margin", P_LOSE, ""): 300.0,
    ("revenue", P_LOSE, ""): 4000.0,
    ("contribution_margin", P_LOW, ""): 800.0,
    ("revenue", P_LOW, ""): 2000.0,
    ("units", P_LOW, ""): 280.0,
    ("inventory_cover_days", P_LOW, ""): 6.0,
    ("supplier_lead_time_days", P_LOW, ""): 10.0,
    ("units_on_hand", P_EMPTY, ""): 0.0,
    ("refund_rate", None, ""): 0.04,
    ("refund_rate", P_WIN, ""): 0.03,
    ("refund_rate", P_LOSE, ""): 0.12,
    ("refund_rate", P_LOW, ""): 0.05,
    ("cpa", WIN, "previous"): 10.0,
    ("cpa", WIN, "recent"): 13.0,
    ("cpa", LOSE, "previous"): 20.0,
    ("cpa", LOSE, "recent"): 21.0,
}


def test_each_lever_reads_its_preconditions(model: TwinModel) -> None:
    ctx = fake(model, FACTS)
    [move] = lv.reallocate_budget(ctx)
    assert move.kind == lv.DECISION
    assert (move.actions[0].entity, move.actions[0].change) == (LOSE, Decimal("-0.30"))
    assert move.actions[1].entity == WIN
    assert move.campaigns == {LOSE, WIN}
    assert "{{E:campaign:" in move.summary
    assert "{{F" in move.summary
    [scale] = lv.scale_profitable(ctx)
    assert scale.actions[0].entity == WIN
    assert Decimal("0") < scale.actions[0].change <= Decimal("0.3")
    [reorder] = lv.prevent_stockout(ctx)
    assert (reorder.kind, reorder.actions[0].kind) == (lv.MANUAL, ActionKind.RESTOCK_PRODUCT)
    assert reorder.actions[0].entity == P_LOW
    assert reorder.day == 0  # its stock covers less than its lead time: order now
    assert reorder.entities == (f"product:{P_LOW}",)
    [cut] = lv.cut_unsellable_spend(ctx)
    assert (cut.actions[0].kind, cut.actions[0].entity) == (ActionKind.PAUSE_CAMPAIGN, EMPTY)
    [shift] = lv.shift_to_margin(ctx)
    assert [a.entity for a in shift.actions] == [LOSE, WIN]
    [price] = lv.price_test(ctx)
    assert price.actions[0].entity == P_WIN  # the prior elasticity: never tested
    assert price.experiment is not None
    assert price.experiment.duration_days == 14
    [refund] = lv.refund_reduction(ctx)
    assert "{{E:product:" + str(P_LOSE) + "}}" in refund.summary
    [creative] = lv.creative_refresh(ctx)
    assert "{{E:campaign:" + str(WIN) + "}}" in creative.summary
    every = lv.candidates(ctx)
    assert {s.lever for s in every} == {lv_.name for lv_ in (*lv.LEVERS, *lv.EXPERIMENTS)}


def test_scaling_for_revenue_judges_sales_against_ad_spend(model: TwinModel) -> None:
    losing = {**FACTS, ("campaign_profit", WIN, ""): -50.0}
    assert lv.scale_profitable(fake(model, losing)) == []  # a profit goal: profitable only
    ctx = fake(model, losing)
    ctx.metric = "revenue"
    [scale] = lv.scale_profitable(ctx)  # sales grow faster than its ad spend
    assert scale.actions[0].entity == WIN
    assert "in sales than it costs in ads" in scale.summary
    # the losing campaign's next increase brings in less in sales than it costs: never scaled
    assert LOSE not in {a.entity for a in scale.actions}


def test_levers_stay_quiet_without_preconditions(model: TwinModel) -> None:
    calm = {k: v for k, v in FACTS.items() if k[0] != "cpa"}
    calm[("campaign_profit", LOSE, "")] = 100.0
    calm[("campaign_profit", EMPTY, "")] = 100.0
    calm[("refund_rate", P_LOSE, "")] = 0.04
    ctx = fake(model, calm)
    ctx.usual = frozenset(model.products)
    assert lv.reallocate_budget(ctx) == []
    assert lv.prevent_stockout(ctx) == []
    assert lv.refund_reduction(ctx) == []
    assert lv.creative_refresh(ctx) == []
    lone = replace(model, campaigns={WIN: model.campaigns[WIN]})
    assert lv.shift_to_margin(fake(lone, calm)) == []
    tested = replace(
        model,
        products={
            p: replace(m, elasticity=Elasticity(True, -3, -1, -2, 0.1))
            for p, m in model.products.items()
        },
    )
    assert lv.price_test(fake(tested, calm)) == []
    partly = replace(
        model,
        campaigns={
            **model.campaigns,
            EMPTY: replace(model.campaigns[EMPTY], promoted=(P_EMPTY, P_WIN)),
        },
    )
    [lower] = lv.cut_unsellable_spend(fake(partly, calm))
    assert (lower.actions[0].kind, lower.actions[0].change) == (
        ActionKind.CHANGE_BUDGET,
        Decimal("-0.30"),
    )


def test_usual_supply_from_the_stock_history(model: TwinModel) -> None:
    def history(stock: list[int | None]) -> ProductSeries:
        zeros = [Decimal(0)] * len(stock)
        return ProductSeries(
            P_LOW, 10, zeros, zeros, zeros, zeros, zeros, zeros, zeros, zeros, zeros, stock
        )

    series = StoreSeries(start=AS_OF - timedelta(days=60), days=60)
    series.products[P_LOW] = history([50] * 30 + [10] * 15 + [60] * 15)  # an arrival 15 days ago
    series.products[P_EMPTY] = history([0] * 60)
    supplied = lv.usual_supply(series, model)
    assert P_LOW in supplied  # stock arrived recently
    assert P_EMPTY not in supplied
    assert P_WIN in supplied  # no history, but its stock covers its lead time
    ctx = fake(model, FACTS)
    ctx.usual = supplied
    assert {a.entity for a in lv.usual_reorders(ctx)} == supplied


def test_restock_and_start_days_in_the_twin(model: TwinModel) -> None:
    low = (Action(kind=ActionKind.RESTOCK_PRODUCT, entity=P_LOW),)
    gained = change_draws(model, Scenario(actions=low, horizon_days=60))
    assert float(np.median(gained["units"])) > 0  # the supply no longer runs out
    late = (Action(kind=ActionKind.RESTOCK_PRODUCT, entity=P_LOW, start=50),)
    less = change_draws(model, Scenario(actions=late, horizon_days=60))
    assert np.median(less["units"]) < np.median(gained["units"])
    assert "start" not in Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=WIN).model_dump()
    later = Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=WIN, start=30)
    halfway = change_draws(model, Scenario(actions=(later,), horizon_days=60))
    whole = change_draws(model, Scenario(actions=(replace_start(later),), horizon_days=60))
    assert abs(np.median(halfway["ad_spend"])) < abs(np.median(whole["ad_spend"]))
    assert set(halfway) >= {"net_profit", "revenue"}
    unknown = (Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=UUID(int=404)),)
    assert change_draws(model, Scenario(actions=unknown, horizon_days=14)) == {}
    assert effect(model, unknown, "net_profit", 14).range() == (0.0, 0.0, 0.0)


def replace_start(action: Action) -> Action:
    return action.model_copy(update={"start": 0})


def test_the_greedy_search_and_the_plan(model: TwinModel) -> None:
    ctx = fake(model, FACTS)
    steps = lv.candidates(ctx)
    rng = np.random.default_rng(0)
    days = 60
    base = 60_000.0 + rng.normal(0.0, 3_000.0, (2000, days)).cumsum(axis=1) * 0.05
    paths = np.cumsum(np.full((2000, days), 1000.0), axis=1) + base - 60_000.0
    final = paths[:, -1]
    target = float(np.percentile(final, 60))
    best = search(model, final, steps, metric="net_profit", target=target, days=days, floor=1e9)
    assert best.steps
    assert all(s.kind != lv.EXPERIMENT for s in best.steps)
    assert best.probability >= reach(final, target)
    used = [c for s in best.steps for c in s.campaigns]
    assert len(used) == len(set(used))  # one change per campaign
    cautious = search(model, final, steps, metric="net_profit", target=target, days=days, floor=0)
    assert (
        cautious.low
        >= search(model, final, [], metric="net_profit", target=target, days=days, floor=0).low
    )
    plan = build(
        model,
        paths,
        steps,
        metric="net_profit",
        target=target,
        as_of=AS_OF,
        floor_monthly=Decimal(100),
    )
    assert plan.days == plan_days(60) == 60
    assert [m.day for m in plan.milestones] == [7, 14, 21, 28, 35, 42, 49, 56, 60]
    assert plan.milestones[0].date == AS_OF + timedelta(days=7)
    assert plan.probability_with[1] >= plan.probability_without[1]
    low, mid, high = plan.probability_with
    assert low <= mid <= high
    assert plan.alternatives is None
    assert {s.lever for s in plan.experiments} == {
        "price_test",
        "refund_reduction",
        "creative_refresh",
    }
    assert all(e[0] <= e[1] <= e[2] for _, e in plan.steps)
    assert decision_steps(plan) == [s for s, _ in plan.steps if s.kind == lv.DECISION]
    assert plan.dated(plan.steps[0][0]) == AS_OF + timedelta(days=plan.steps[0][0].day)
    assert len(plan.assumptions) == 5
    assert not plan.lowers_profit


def test_an_unlikely_goal_gets_alternatives(model: TwinModel) -> None:
    rng = np.random.default_rng(1)
    paths = np.cumsum(1000.0 + rng.normal(0.0, 400.0, (2000, 120)), axis=1)
    extended = np.cumsum(1000.0 + rng.normal(0.0, 400.0, (2000, 186)), axis=1)
    target = float(paths[:, -1].max()) * 1.3
    plan = build(
        model,
        paths,
        [],
        metric="revenue",
        target=target,
        as_of=AS_OF,
        floor_monthly=Decimal(100),
        extended=extended,
    )
    assert plan.days == 90  # the detailed part
    assert plan.milestones[-1].day == 90
    assert plan.verdict_with == "unlikely"
    alt = plan.alternatives
    assert alt is not None
    assert alt.target_70[1] < alt.target_50[1] < target
    assert alt.target_50[0] <= alt.target_50[1] <= alt.target_50[2]
    assert alt.deadline_days is not None
    assert 120 < alt.deadline_days <= 186
    far = build(
        model,
        paths,
        [],
        metric="revenue",
        target=target * 10,
        as_of=AS_OF,
        floor_monthly=Decimal(100),
        extended=extended,
    )
    assert far.alternatives is not None
    assert far.alternatives.deadline_days is None
    assert combine(np.array([1.0, 2.0, 3.0]), np.array([10.0])).tolist() == [11.0, 12.0, 13.0]


def test_a_revenue_plan_that_lowers_profit_says_so(model: TwinModel) -> None:
    ctx = fake(model, FACTS)
    risky = lv.Step(
        lever="scale_profitable",
        kind=lv.DECISION,
        day=0,
        actions=(Action(kind=ActionKind.CHANGE_BUDGET, entity=LOSE, change=Decimal("0.3")),),
        summary="",
        evidence=(),
    )
    assert ctx.horizon == 60
    paths = np.cumsum(np.full((500, 30), 1000.0), axis=1)
    target = float(paths[0, -1]) + 1.0  # only more sales reach it
    plan = build(
        model,
        paths,
        [risky],
        metric="revenue",
        target=target,
        as_of=AS_OF,
        floor_monthly=Decimal(10**9),
    )
    assert [s.lever for s, _ in plan.steps] == ["scale_profitable"]
    assert plan.lowers_profit  # more revenue from a campaign that loses money


@pytest.mark.db
def test_levers_on_a_store(app_engine: Engine) -> None:
    config = bench_config(434_343).model_copy(update={"days": 90})
    data = generate(config)
    load(app_engine, data, config)
    store = data.store.store_id
    with tenant_transaction(app_engine, store) as conn:
        model = fit_twin(conn, store)
        ctx = lv.context(conn, store, model, 60)
        steps = lv.candidates(ctx)
        evidence = {fid for s in steps for fid in s.evidence}
    assert ctx.cap == Decimal("0.30")
    assert ctx.usual
    assert all(fid > 0 for fid in evidence)
    assert all(s.summary for s in steps)
