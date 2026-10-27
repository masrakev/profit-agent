"""Economic materiality: impact scope, bootstrap estimate, gating and severity."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import numpy as np
import pytest
from sqlalchemy import Engine

from app.causes.drivers import Driver
from app.causes.noise import DailyFigures
from app.db import tenant_transaction
from app.detection import pipeline
from app.detection.impact import (
    METHOD,
    MonthlyImpact,
    ads_on_out_of_stock,
    alert_level,
    estimate_monthly_impact,
    impact_scope,
)
from app.detection.incidents import EntityGraph
from app.detection.models import (
    OUT_OF_STOCK_NOTE,
    AlertLevel,
    EntityRef,
    Severity,
    Symptom,
    SymptomCategory,
)
from app.facts.model import FactKind
from app.facts.repository import get_facts
from app.settings import StoreSettingsRepository
from app.settings.models import Materiality
from bench.generator.load import load
from bench.scenarios.manifest import load_suite

P1, P2 = UUID(int=1), UUID(int=2)
C1 = UUID(int=11)
GRAPH = EntityGraph({C1: frozenset({P1})})
D = Decimal


def sym(detector: str, entity: EntityRef, note: str | None = None) -> Symptom:
    return Symptom(
        detector_id=detector,
        entity=entity,
        metric="m",
        category=SymptomCategory.PROFITABILITY,
        severity=Severity.MEDIUM,
        score=2.0,
        first_seen=date(2026, 8, 1),
        last_seen=date(2026, 8, 5),
        baseline_fact_ids=(1,),
        current_fact_ids=(2,),
        note=note,
    )


def test_scope_expands_campaigns_and_maps_store_symptoms() -> None:
    scope = impact_scope(
        [
            sym("campaign_cpa_cusum", EntityRef.campaign(C1)),
            sym("store_payment_fee_rate_z", EntityRef.store()),
        ],
        GRAPH,
    )
    assert scope.products == {P1}
    assert scope.campaigns == {C1}
    assert scope.store_drivers == {Driver.FEES}
    margin = impact_scope([sym("store_gross_margin_rate_cusum", EntityRef.store())], GRAPH)
    assert margin.store_drivers == {Driver.MIX, Driver.PRICE, Driver.UNIT_COST}


def figures(days: int = 84, cost_from: int = 56, extra_cost: float = 2.0) -> DailyFigures:
    rng = np.random.default_rng(5)
    units = rng.poisson(10, (2, days)).astype(np.float64)
    cost = np.where(np.arange(days) >= cost_from, 8.0 + extra_cost, 8.0)
    return DailyFigures(
        revenue=units * 20,
        units=units,
        cogs=units * np.vstack([cost, np.full(days, 8.0)]),
        fees=units * 1.0,
        refunds=np.zeros((2, days)),
        spend=np.full((1, days), 30.0),
        fixed=np.full(days, 5.0),
    )


def test_bootstrap_recovers_a_cost_increase() -> None:
    # P1 sells ~10 units/day; +$2 unit cost -> about -$20/day, -$600 per 30 days.
    scope = impact_scope([sym("product_unit_cost_z", EntityRef.product(P1))], GRAPH)
    impact = estimate_monthly_impact(
        figures(),
        [P1, P2],
        [C1],
        scope,
        baseline=(28, 56),
        current=(56, 84),
        rng=np.random.default_rng(1),
        resamples=500,
    )
    assert impact.p10 <= impact.p50 <= impact.p90
    assert D(-750) < impact.p50 < D(-450)
    assert impact.loss == -impact.p50
    again = estimate_monthly_impact(
        figures(),
        [P1, P2],
        [C1],
        scope,
        baseline=(28, 56),
        current=(56, 84),
        rng=np.random.default_rng(1),
        resamples=500,
    )
    assert again == impact  # seeded
    store_only = impact_scope([sym("store_gross_margin_rate_z", EntityRef.store())], GRAPH)
    store_impact = estimate_monthly_impact(
        figures(),
        [P1, P2],
        [C1],
        store_only,
        baseline=(28, 56),
        current=(56, 84),
        rng=np.random.default_rng(1),
        resamples=200,
    )
    assert store_impact.p50 < 0  # unit cost is among the margin drivers


@pytest.mark.parametrize(
    ("p50", "trailing", "out_of_stock", "expected"),
    [
        ("-1500", "10000", False, (AlertLevel.CRITICAL, True)),  # >= 10x absolute
        ("-400", "10000", False, (AlertLevel.HIGH, True)),  # >= 3x absolute
        ("-150", "1000", False, (AlertLevel.NORMAL, True)),
        ("-150", "10000", False, (AlertLevel.WATCHLIST, False)),  # below 3% of 10,000
        ("-80", "100", False, (AlertLevel.WATCHLIST, False)),  # below the absolute 100
        ("50", "100", False, (AlertLevel.WATCHLIST, False)),  # a gain is not a loss
        ("-150", "-500", False, (AlertLevel.NORMAL, True)),  # negative margin: relative is 0
        ("0", "100", True, (AlertLevel.CRITICAL, False)),  # ads on an empty shelf
    ],
)
def test_alert_levels(
    p50: str, trailing: str, out_of_stock: bool, expected: tuple[AlertLevel, bool]
) -> None:
    impact = MonthlyImpact(D(p50) - 10, D(p50), D(p50) + 10)
    assert (
        alert_level(impact, Materiality(), D(trailing), ads_on_out_of_stock=out_of_stock)
        == expected
    )


def test_out_of_stock_note() -> None:
    cover = "product_cover_below_lead_time"
    assert ads_on_out_of_stock([sym(cover, EntityRef.product(P1), OUT_OF_STOCK_NOTE)])
    assert not ads_on_out_of_stock([sym(cover, EntityRef.product(P1))])


@pytest.mark.db
def test_materiality_comes_from_store_settings(app_engine: Engine) -> None:
    manifest = next(
        # A different store from test_detection_pipeline's (store ids derive from the scenario).
        m
        for m in load_suite("dev")
        if m.scenario_id == "dev-mix_shift-03"
    )
    data = manifest.generate()
    load(app_engine, data, manifest.config)
    store = data.store.store_id
    default = pipeline.run_pipeline(app_engine, store)
    alerts = [i for i in default.incidents if i.is_alert]
    assert alerts
    assert alerts[0].candidates[0].family.value == "mix_shift"
    with tenant_transaction(app_engine, store) as conn:
        impacts = get_facts(conn, store, [alerts[0].monthly_impact_fact_id or 0], with_lineage=True)
        fact = next(iter(impacts.values()))
        assert fact.kind is FactKind.ESTIMATE
        assert fact.method == METHOD
        assert fact.p10 is not None
        assert fact.p90 is not None
        assert fact.p10 <= fact.p90
        assert fact.baseline is not None
        assert fact.baseline.end <= fact.period.start
        assert fact.lineage.parents
        repo = StoreSettingsRepository(conn)
        repo.save(
            repo.get_or_default(store).model_copy(
                update={"materiality": Materiality(absolute=D(10**9), relative=D("0.03"))}
            ),
            actor="test",
        )
    strict = pipeline.run_pipeline(app_engine, store)
    assert not [
        i
        for i in strict.incidents
        if i.is_alert
        and i.category is SymptomCategory.PROFITABILITY
        and i.alert is not AlertLevel.CRITICAL
    ]
    assert date(2026, 6, 1) + timedelta(days=0) == manifest.config.start_date
