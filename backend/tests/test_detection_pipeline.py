"""Daily series and the detection pipeline against PostgreSQL."""

import json
from datetime import date

import pytest
from sqlalchemy import Engine

from app.db import tenant_transaction
from app.detection import pipeline
from app.detection.config import default_config
from app.detection.models import FaultFamily
from app.detection.series import load_series
from app.facts.engine import FactEngine
from app.facts.model import Period, Scope
from app.facts.repository import get_facts
from bench.generator.load import load
from bench.scenarios.manifest import load_suite
from tests.conftest import create_store
from tests.test_profit_attribution import _cost_increase_store

pytestmark = pytest.mark.db


def test_daily_series_reconcile_with_facts(app_engine: Engine) -> None:
    store, a, _ = _cost_increase_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        series = load_series(conn, store)
        engine = FactEngine(conn, store)
        window = Period.days(date(2026, 2, 1), date(2026, 2, 15))
        lo, hi = series.index(date(2026, 2, 1)), series.index(date(2026, 2, 15))
        assert (
            sum(series.products[a].revenue[lo:hi])
            == engine.fact("revenue", Scope.product(a), window).value
        )
        assert sum(series.total("cogs")[lo:hi]) == engine.fact("cogs", Scope.store(), window).value
        fixed = engine.fact("fixed_costs", Scope.store(), window).value
        assert fixed == 0
        assert sum(series.fixed_costs[lo:hi]) == fixed
        assert series.campaigns_promoting(a) == []
    empty = create_store(app_engine)
    with tenant_transaction(app_engine, empty) as conn:
        assert load_series(conn, empty).days == 0


def test_attribution_windows() -> None:
    from app.detection.series import StoreSeries

    series = StoreSeries(start=date(2026, 6, 1), days=120)
    cfg = default_config()
    base, cur = pipeline.attribution_windows(series, date(2026, 8, 10), cfg)  # day 70
    assert (base.end.date() - series.start).days == 63  # 7 days before first seen
    assert (cur.end - cur.start) == (base.end - base.start)
    assert (cur.end - cur.start).days % 7 == 0
    late_base, late_cur = pipeline.attribution_windows(series, date(2026, 9, 25), cfg)
    assert (late_cur.end - late_cur.start).days == 42  # too little room: last adjacent windows
    assert late_base.end == late_cur.start


def test_pipeline_finds_a_supplier_cost_increase_end_to_end(
    app_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = next(
        m for m in load_suite("dev") if m.scenario_id == "dev-supplier_cost_increase-03"
    )
    data = manifest.generate()
    load(app_engine, data, manifest.config)
    store = data.store.store_id
    result = pipeline.run_pipeline(app_engine, store)
    label = manifest.labels[0]
    top = result.incidents[0].candidates[0]
    assert top.family is FaultFamily.SUPPLIER_COST_INCREASE
    assert top.entity in label.entities
    assert result.attribution is not None
    assert result.thresholds_version == 1
    referenced = {i for s in result.symptoms for i in (*s.baseline_fact_ids, *s.current_fact_ids)}
    with tenant_transaction(app_engine, store) as conn:
        assert set(get_facts(conn, store, referenced)) == referenced  # every symptom is backed

    assert pipeline.main(["--store", str(store)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["incidents"][0]["candidates"][0]["family"] == "supplier_cost_increase"


def test_pipeline_on_an_empty_store(app_engine: Engine) -> None:
    store = create_store(app_engine)
    result = pipeline.run_pipeline(app_engine, store)
    assert result.incidents == []
    assert result.attribution is None
