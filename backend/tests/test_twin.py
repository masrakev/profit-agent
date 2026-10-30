"""Store twin: curve fitting, elasticity rule, Monte Carlo and calibration."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import pytest
from sqlalchemy import Engine

from app.db import tenant_transaction
from app.facts.engine import FactEngine
from app.facts.model import FactKind, Unit
from app.facts.repository import get_facts
from app.twin import Action, ActionKind, Scenario, fit_twin, simulate
from app.twin.calibration import Calibration, load_calibration, widen
from app.twin.facts import input_facts, simulation_facts
from app.twin.fit import PRIOR_ELASTICITY, _elasticity, fit_curve, profile_fit
from app.twin.model import CampaignModel, Elasticity, ProductModel, Range, TwinModel
from bench.generator.load import load
from bench.scenarios.manifest import load_suite

RAW = Calibration.identity()
METRIC_NAMES = ("contribution_margin", "net_profit", "units", "ad_spend")
CAMPAIGN = UUID(int=1)
PROMOTED, OTHER = UUID(int=10), UUID(int=11)


def curve_campaign(rng: np.random.Generator) -> CampaignModel:
    spend = rng.uniform(40, 160, 60)
    purchases = 8.0 * (1 - np.exp(-0.02 * spend)) + rng.normal(0, 0.3, 60)
    return CampaignModel(
        campaign_id=CAMPAIGN,
        promoted=(PROMOTED,),
        mean_spend=100.0,
        spend_ratios=spend / spend.mean(),
        active_days=60,
        curve=fit_curve(spend, purchases, rng),
    )


def product(pid: UUID, **overrides: Any) -> ProductModel:
    base = ProductModel(
        product_id=pid,
        units_observed=420.0,
        ad_rate=6.0,
        net_price=50.0,
        unit_cost=20.0,
        fee_per_unit=2.0,
        refund_rate=0.05,
        units_per_line=1.1,
        on_hand=None,
        inflow_rate=0.0,
        elasticity=PRIOR_ELASTICITY,
    )
    return replace(base, **overrides)


def run(model: TwinModel, kind: ActionKind, **fields: Any) -> Any:
    return simulate(model, Scenario(actions=(Action(kind=kind, **fields),)), calibration=RAW)


@pytest.fixture(scope="module")
def model() -> TwinModel:
    rng = np.random.default_rng(3)
    return TwinModel(
        store_id=UUID(int=99),
        currency="USD",
        as_of=date(2026, 10, 1),
        window_days=42,
        products={PROMOTED: product(PROMOTED), OTHER: product(OTHER, ad_rate=0.0)},
        campaigns={CAMPAIGN: curve_campaign(rng)},
        fixed_daily=100.0,
        fingerprint="test",
    )


def test_profile_fit_recovers_the_curve() -> None:
    spend = np.linspace(10, 300, 50)
    a, b, sigma = profile_fit(spend[None, :], 9.0 * (1 - np.exp(-0.02 * spend))[None, :])
    assert a[0] == pytest.approx(9.0, rel=0.05)
    assert b[0] == pytest.approx(0.02, rel=0.1)
    assert sigma[0] < 0.1
    flat = profile_fit(spend[None, :], np.zeros((1, 50)))
    assert flat[0][0] == 0.0


def test_bootstrap_is_seeded() -> None:
    first = curve_campaign(np.random.default_rng(5)).curve
    again = curve_campaign(np.random.default_rng(5)).curve
    assert first is not None
    assert again is not None
    assert np.array_equal(first.a, again.a)
    assert len(first.a) == 500


def test_elasticity_needs_real_list_price_changes() -> None:
    assert _elasticity([]) is PRIOR_ELASTICITY
    same_price = [(19.99, 3.0)] * 30
    assert _elasticity(same_price) is PRIOR_ELASTICITY
    small_change = [(20.0, 3.0)] * 10 + [(20.5, 3.0)] * 10
    assert _elasticity(small_change) is PRIOR_ELASTICITY
    too_few_days = [(20.0, 3.0)] * 10 + [(25.0, 2.0)] * 3
    assert _elasticity(too_few_days) is PRIOR_ELASTICITY
    days = [(20.0, 6.0 + d % 2) for d in range(14)] + [(25.0, 3.0 + d % 2) for d in range(14)]
    estimated = _elasticity(days)
    assert estimated.estimated
    assert -6.0 <= estimated.mean < -1.0


def test_doing_nothing_changes_nothing(model: TwinModel) -> None:
    sim = simulate(model, Scenario(), calibration=RAW)
    assert sim.undefined_reason is None
    assert all(r == Range(0.0, 0.0, 0.0) for r in sim.change.values())
    assert sim.totals == sim.do_nothing
    assert (
        sim.totals["net_profit"].p10 < sim.totals["net_profit"].p50 < sim.totals["net_profit"].p90
    )
    assert simulate(model, Scenario(), calibration=RAW) == sim  # deterministic


def test_budget_actions_move_spend_and_sales(model: TwinModel) -> None:
    cut = run(model, ActionKind.CHANGE_BUDGET, entity=CAMPAIGN, change=Decimal("-0.3"))
    assert cut.change["ad_spend"].p50 == pytest.approx(-0.3 * 14 * 100, rel=0.1)
    assert cut.change["units"].p50 < 0
    assert cut.low_evidence == ()  # within the spend range the curve was fitted on
    doubled = run(model, ActionKind.CHANGE_BUDGET, entity=CAMPAIGN, change=Decimal(1))
    assert doubled.low_evidence == (
        "spend outside the observed range: the response curve is extrapolated",
    )
    paused = run(model, ActionKind.PAUSE_CAMPAIGN, entity=CAMPAIGN)
    assert paused.totals["ad_spend"].p90 == pytest.approx(0.0)
    assert paused.change["units"].p90 < cut.change["units"].p50
    week = run(model, ActionKind.PAUSE_CAMPAIGN, entity=CAMPAIGN, days=7)
    assert week.change["ad_spend"].p50 == pytest.approx(paused.change["ad_spend"].p50 / 2, rel=0.15)
    everything = run(model, ActionKind.CHANGE_ALL_AD_SPEND, change=Decimal("-0.3"))
    assert everything.change["ad_spend"].p50 == pytest.approx(cut.change["ad_spend"].p50, rel=0.01)


def test_price_changes_use_the_elasticity(model: TwinModel) -> None:
    def discount(m: TwinModel) -> Any:
        action = Action(kind=ActionKind.CHANGE_PRICE, entity=OTHER, change=Decimal("-0.2"))
        return simulate(m, Scenario(actions=(action,)), calibration=RAW)

    prior = discount(model)
    assert prior.low_evidence == (
        "price response from the prior: the list price never changed enough",
    )
    assert prior.change["units"].p10 > 0  # cheaper sells more, whatever the elasticity
    known = Elasticity(estimated=True, low=-6.0, high=0.0, mean=-2.0, sd=0.1)
    estimated = discount(
        replace(model, products={**model.products, OTHER: product(OTHER, elasticity=known)})
    )
    assert estimated.low_evidence == ()
    width = estimated.change["units"].p90 - estimated.change["units"].p10
    assert width < prior.change["units"].p90 - prior.change["units"].p10


def test_stock_caps_sales_and_new_campaigns(model: TwinModel) -> None:
    empty = product(OTHER, on_hand=0.0, inflow_rate=0.0, ad_rate=0.0)
    out_of_stock = replace(model, products={**model.products, OTHER: empty})
    launch = Action(kind=ActionKind.LAUNCH_CAMPAIGN, entity=OTHER, daily_budget=Decimal(50))
    sim = simulate(out_of_stock, Scenario(actions=(launch,)), calibration=RAW)
    assert sim.change["units"] == Range(0.0, 0.0, 0.0)
    assert sim.change["net_profit"].p50 == pytest.approx(-50 * 14, rel=0.01)
    assert "borrowed" in sim.low_evidence[0]
    in_stock = simulate(model, Scenario(actions=(launch,)), calibration=RAW)
    assert in_stock.change["units"].p50 > 0
    no_curves = replace(model, campaigns={})
    assert simulate(no_curves, Scenario(actions=(launch,)), calibration=RAW).undefined_reason


def test_undefined_scenarios(model: TwinModel) -> None:
    unknown = Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=UUID(int=7))
    assert simulate(model, Scenario(actions=(unknown,))).undefined_reason == (
        "unknown pause_campaign entity"
    )
    short = replace(
        model.campaigns[CAMPAIGN], curve=None, undefined_reason="fewer than 14 days of spend"
    )
    weak = replace(model, campaigns={CAMPAIGN: short})
    sim = simulate(
        weak, Scenario(actions=(Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=CAMPAIGN),))
    )
    assert (sim.undefined_reason, sim.totals) == ("fewer than 14 days of spend", {})


def test_calibration_widens_intervals(model: TwinModel, tmp_path: Path) -> None:
    assert widen(Range(10, 20, 40), 0.5) == Range(2.5, 20, 47.5)
    assert widen(Range(10, 20, 40), -0.5) == Range(17.5, 20, 32.5)
    cal = Calibration(
        version=3,
        method="m",
        do_nothing=dict.fromkeys(METRIC_NAMES, -0.5),
        action=dict.fromkeys(METRIC_NAMES, 0.4),
    )
    assert cal.change_factor("units") == 0.4
    assert cal.factor("units", action=False) == -0.5
    raw = simulate(model, Scenario(), calibration=RAW)
    calibrated = simulate(model, Scenario(), calibration=cal)
    assert calibrated.calibration_version == 3
    assert calibrated.totals["units"] == widen(raw.totals["units"], -0.5)
    path = tmp_path / "calibration.toml"
    path.write_text(
        'version = 2\nmethod = "split_conformal_v1"\n[do_nothing]\n'
        + "".join(
            f"{m} = 0.1\n" for m in ("contribution_margin", "net_profit", "units", "ad_spend")
        )
        + "[action]\n"
        + "".join(
            f"{m} = 0.2\n" for m in ("contribution_margin", "net_profit", "units", "ad_spend")
        ),
        encoding="utf-8",
    )
    loaded = load_calibration(path)
    assert (loaded.version, loaded.factor("ad_spend", action=True)) == (2, 0.2)
    assert load_calibration(tmp_path / "missing.toml") == RAW


@pytest.fixture(scope="module")
def own_store(app_engine: Engine) -> dict[str, Any]:
    """A stockout store of the twin tests' own: no other test writes to it, so the twin's view
    of it can be compared exactly with what was generated."""
    manifest = next(m for m in load_suite("dev") if m.scenario_id == "dev-stockout_on_promoted-02")
    data = manifest.generate()
    load(app_engine, data, manifest.config)
    label = manifest.labels[0]
    return {
        "id": data.store.store_id,
        "products": [p.id for p in data.products],
        "product": next(e.id for e in label.entities if e.kind.value == "product"),
    }


@pytest.mark.db
def test_fit_on_a_store(app_engine: Engine, own_store: dict[str, Any]) -> None:
    store = own_store["id"]
    with tenant_transaction(app_engine, store) as conn:
        model = fit_twin(conn, store)
        earlier = fit_twin(conn, store, as_of=model.as_of - timedelta(days=14))
        with pytest.raises(ValueError, match="no data"):
            fit_twin(conn, store, as_of=date(2000, 1, 1))
    assert earlier.as_of == model.as_of - timedelta(days=14)
    assert earlier.fingerprint != model.fingerprint
    assert set(model.products) == set(own_store["products"])
    stockout = model.products[own_store["product"]]
    assert stockout.on_hand == 0
    assert not stockout.elasticity.estimated  # bench list prices never change
    assert any(c.curve is not None for c in model.campaigns.values())
    launch = Action(kind=ActionKind.LAUNCH_CAMPAIGN, entity=own_store["product"])
    sim = simulate(model, Scenario(actions=(launch,)), calibration=RAW)
    assert sim.change["net_profit"].p90 < 0  # pure spend on a product that cannot be sold


@pytest.mark.db
def test_simulations_become_estimate_facts(app_engine: Engine, own_store: dict[str, Any]) -> None:
    store = own_store["id"]
    with tenant_transaction(app_engine, store) as conn:
        engine = FactEngine(conn, store)
        model = fit_twin(conn, store)
        launch = Action(kind=ActionKind.LAUNCH_CAMPAIGN, entity=own_store["product"])
        sim = simulate(model, Scenario(actions=(launch,)))
        facts = simulation_facts(engine, model, sim, input_facts(engine, model, sim))
        again = simulation_facts(engine, model, sim, input_facts(engine, model, sim))
        parents = get_facts(conn, store, [facts["twin.change.net_profit"].id or 0])
        unknown = Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=UUID(int=5))
        broken = simulate(model, Scenario(actions=(unknown,)))
        undefined = simulation_facts(engine, model, broken, input_facts(engine, model, broken))
    assert len(facts) == 12
    change = facts["twin.change.net_profit"]
    assert change.kind is FactKind.ESTIMATE
    assert change.p10 is not None
    assert change.p90 is not None
    assert change.p10 <= change.value <= change.p90
    assert change.period.start.date() == model.as_of
    assert change.method == f"twin_monte_carlo_v1;calibration v{sim.calibration_version}"
    assert {p.role for p in change.lineage.parents} >= {
        "store:contribution_margin",
        "product:units",
    }
    assert facts["twin.units"].unit is Unit.COUNT
    assert facts["twin.units"].currency is None
    assert again["twin.change.net_profit"].id == change.id  # same inputs, same fact
    assert parents
    assert undefined["twin.change.net_profit"].undefined_reason == "unknown pause_campaign entity"
