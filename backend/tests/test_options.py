"""Options by cause: catalogue, simulation and the recommendation rule."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.agent.contracts import ActionFamily
from app.decisions.options import (
    UNDERFUNDED_CAMPAIGN,
    Option,
    OptionKind,
    Reversibility,
    build_options,
    catalogue,
    monitor,
    recommend,
)
from app.twin import Scenario
from app.twin.model import Range, Simulation, TwinModel
from tests.test_twin import CAMPAIGN, OTHER, PROMOTED, product
from tests.test_twin import model as twin_model  # noqa: F401  (module fixture)

CAMPAIGN_ENTITY = f"campaign:{CAMPAIGN}"


def simulated(
    option_id: str, change: Range | None, kind: OptionKind = OptionKind.REDUCE_BUDGET
) -> Option:
    sim = Simulation(
        scenario=Scenario(),
        totals={},
        do_nothing={},
        change={} if change is None else {"net_profit": change},
        undefined_reason=None if change is not None else "unknown",
    )
    return Option(
        option_id,
        kind,
        ActionFamily.REDUCE_OR_REALLOCATE_BUDGET,
        CAMPAIGN_ENTITY,
        (),
        Reversibility.REVERSIBLE,
        (),
        (),
        simulation=sim,
    )


def test_recommendation_rule() -> None:
    floor = Decimal(50)
    options = [
        simulated("risky", Range(-200, 300, 600)),  # best median, downside beyond the floor
        simulated("safe", Range(-40, 100, 200)),
        simulated("safer", Range(10, 60, 90)),
        simulated("losing", Range(-10, -5, 30)),  # within the floor but no median gain
        simulated("undefined", None),
    ]
    assert recommend(options, floor)[0] == "safe"
    assert recommend(options[:1] + options[3:], floor) == (
        "",
        "no option beats doing nothing safely: monitor",
    )
    manual = replace(simulated("quality", None), kind=OptionKind.INVESTIGATE_PRODUCT_QUALITY)
    assert recommend([options[0], manual], floor)[0] == "quality"


def test_catalogue_by_cause(twin_model: TwinModel) -> None:  # noqa: F811
    kinds = {
        cause: [o.kind for o in catalogue(cause, CAMPAIGN_ENTITY, twin_model)]
        for cause in (
            "cpa_drift",
            "negative_campaign_profit",
            "cannibalization",
            UNDERFUNDED_CAMPAIGN,
            "tracking_break",
            "mix_shift",
        )
    }
    cut = [OptionKind.REDUCE_BUDGET, OptionKind.REDUCE_BUDGET, OptionKind.PAUSE_CAMPAIGN]
    assert kinds["cpa_drift"] == kinds["negative_campaign_profit"] == cut
    assert kinds["cannibalization"] == [*cut, OptionKind.INCREMENTALITY_TEST]
    assert kinds[UNDERFUNDED_CAMPAIGN] == [OptionKind.INCREASE_BUDGET] * 2
    assert kinds["tracking_break"] == [OptionKind.FIX_TRACKING]  # never a budget action
    assert kinds["mix_shift"] == []
    increase = catalogue(UNDERFUNDED_CAMPAIGN, CAMPAIGN_ENTITY, twin_model)
    assert [float(o.actions[0].change) for o in increase] == [0.1, 0.2]
    assert all(o.executable and o.reversibility is Reversibility.REVERSIBLE for o in increase)
    flags = {o.flags for o in catalogue("cannibalization", CAMPAIGN_ENTITY, twin_model)[:3]}
    assert flags == {("incrementality_test",)}
    by_product = {
        cause: [o.kind for o in catalogue(cause, f"product:{PROMOTED}", twin_model)]
        for cause in (
            "stockout_on_promoted",
            "supplier_cost_increase",
            "refund_spike",
            "fee_increase",
        )
    }
    assert by_product == {
        "stockout_on_promoted": [
            OptionKind.PAUSE_UNTIL_RESTOCK,
            OptionKind.REDUCE_BUDGET,
            OptionKind.PREPARE_REORDER,
        ],
        "supplier_cost_increase": [OptionKind.PREPARE_PRICE_CHANGE, OptionKind.REVIEW_SUPPLIER],
        "refund_spike": [OptionKind.INVESTIGATE_PRODUCT_QUALITY],
        "fee_increase": [],
    }
    quality = catalogue("refund_spike", f"product:{PROMOTED}", twin_model)[0]
    assert (quality.actions, quality.executable) == ((), False)
    assert catalogue("cpa_drift", "store", twin_model) == []


def test_stockout_pauses_the_promoting_campaigns_for_the_lead_time(
    twin_model: TwinModel,  # noqa: F811
) -> None:
    with_lead = replace(
        twin_model,
        products={**twin_model.products, PROMOTED: product(PROMOTED, lead_time_days=9)},
    )
    pause = catalogue("stockout_on_promoted", f"product:{PROMOTED}", with_lead)[0]
    assert [(a.entity, a.days) for a in pause.actions] == [(CAMPAIGN, 9)]
    default = catalogue("stockout_on_promoted", f"product:{PROMOTED}", twin_model)[0]
    assert default.actions[0].days == 14
    unpromoted = catalogue("stockout_on_promoted", f"product:{OTHER}", twin_model)
    assert [o.kind for o in unpromoted] == [OptionKind.PREPARE_REORDER]


def test_build_options_simulates_and_recommends(twin_model: TwinModel) -> None:  # noqa: F811
    built = build_options(twin_model, "cpa_drift", CAMPAIGN_ENTITY, floor_monthly=Decimal(100))
    assert built.floor == Decimal("46.67")
    assert all(o.simulation is not None and o.impact is not None for o in built.options)
    assert built.recommended in {o.option_id for o in built.options}
    chosen = built.option(built.recommended)
    if chosen.kind is not OptionKind.MONITOR:
        assert chosen.impact is not None
        assert chosen.impact.p10 >= -46.67
        assert chosen.impact.p50 > 0
    nothing = build_options(twin_model, "mix_shift", "store", floor_monthly=Decimal(100))
    assert [o.kind for o in nothing.options] == [OptionKind.MONITOR]
    assert nothing.recommended == monitor("mix_shift", "store").option_id
    with pytest.raises(StopIteration):
        nothing.option("missing")
