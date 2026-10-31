"""Goal forecasts, the probability of reaching a target and its verdict (app/goals)."""

import json
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import Engine, text

from app.db import tenant_transaction
from app.detection.series import load_series
from app.facts.engine import FactEngine
from app.facts.model import FactKind, Period, Scope, Unit
from app.goals import forecast as fc
from app.goals.feasibility import (
    assess,
    assess_store,
    bucket,
    checkpoints,
    low_evidence,
    verdict,
)
from app.goals.forecast import calibrate, daily_values, fit, forecast, scale, simulate
from app.verifier import verify
from bench.generator import generate
from bench.generator.load import load
from bench.scenarios.build import bench_config

START = date(2026, 1, 5)  # a Monday
DOW = np.array([0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0])


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    fc.frozen.cache_clear()
    yield
    fc.frozen.cache_clear()


def frozen_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **data: Any) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({"version": "test", "target": 0.8, "scales": {}, **data}))
    monkeypatch.setattr(fc, "FROZEN", path)
    fc.frozen.cache_clear()


def series(days: int, slope: float = 1.0, noise: float = 20.0, seed: int = 1) -> np.ndarray:
    t = np.arange(days, dtype=np.float64)
    rng = np.random.default_rng(seed)
    return 1000.0 + slope * t + DOW[t.astype(int) % 7] + rng.normal(0.0, noise, days)


def truth(days: int, horizon: int, slope: float = 1.0) -> float:
    t = np.arange(days, days + horizon)
    return float((1000.0 + slope * t + DOW[t % 7]).sum())


def test_the_forecast_follows_trend_and_weekday() -> None:
    f = forecast(series(200), START, "revenue", 60, seed=3, half_life=None, calibrated=False)
    assert (f.as_of, f.history_days, f.horizon, f.calibration) == (
        START + timedelta(days=200),
        200,
        60,
        "uncalibrated",
    )
    for day in (30, 60):
        low, mid, high = f.quantiles(day)
        assert low < mid < high
        assert mid == pytest.approx(truth(200, day), rel=0.01)
    width = [f.quantiles(d)[2] - f.quantiles(d)[0] for d in (7, 30, 60)]
    assert width[0] < width[1] < width[2]  # uncertainty grows with the horizon
    again = forecast(series(200), START, "revenue", 60, seed=3, half_life=None, calibrated=False)
    assert np.array_equal(again.paths, f.paths)  # seeded
    assert f.level == pytest.approx(float(np.abs(series(200)[-fc.FIT_DAYS :]).mean()))


def test_the_weekday_of_future_days() -> None:
    values = series(99, slope=0.0, noise=0.0)  # day 99 is a Monday again
    f = fit(values, START, window=91)
    daily = np.diff(simulate(f, 7, np.random.default_rng(0), draws=10), axis=1, prepend=0.0)
    assert daily[0] == pytest.approx(1000.0 + DOW[np.arange(99, 106) % 7])


def test_a_damped_trend_grows_less() -> None:
    linear = forecast(
        series(200, slope=5.0), START, "revenue", 90, seed=1, half_life=None, calibrated=False
    )
    damped = forecast(
        series(200, slope=5.0), START, "revenue", 90, seed=1, half_life=30.0, calibrated=False
    )
    flat = forecast(
        series(200, slope=5.0), START, "revenue", 90, seed=1, half_life=0.0, calibrated=False
    )
    medians = [g.quantiles(90)[1] for g in (flat, damped, linear)]
    assert medians[0] < medians[1] < medians[2]
    assert medians[2] == pytest.approx(truth(200, 90, slope=5.0), rel=0.01)


def test_forecast_limits() -> None:
    with pytest.raises(ValueError, match="at least 28"):
        forecast(series(20), START, "revenue", 30, seed=1)
    for horizon in (0, 187):
        with pytest.raises(ValueError, match="between 1 and 186"):
            forecast(series(60), START, "revenue", horizon, seed=1)


def test_the_frozen_calibration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frozen_at(tmp_path, monkeypatch, scales={"revenue": {"30": 1.5, "60": 2.0}})
    assert (scale("revenue", 10), scale("revenue", 45), scale("revenue", 100)) == (1.5, 1.75, 2.0)
    assert scale("net_profit", 45) == 1.0
    raw = forecast(series(120), START, "revenue", 30, seed=2, calibrated=False)
    cal = forecast(series(120), START, "revenue", 30, seed=2)
    assert cal.calibration == "test"
    (r10, r50, r90), (c10, c50, c90) = raw.quantiles(30), cal.quantiles(30)
    assert c50 == pytest.approx(r50)
    assert c90 - c10 == pytest.approx(1.5 * (r90 - r10), rel=1e-6)
    assert np.allclose(calibrate(raw.paths, "net_profit"), raw.paths)


def test_verdicts_and_buckets() -> None:
    cases = [(0.7, "likely"), (0.6999, "possible"), (0.4, "possible"), (0.3999, "stretch")]
    cases += [(0.15, "stretch"), (0.1499, "unlikely"), (0.0, "unlikely"), (1.0, "likely")]
    assert [verdict(p) for p, _ in cases] == [v for _, v in cases]
    assert [bucket(h) for h in (1, 30, 31, 90, 91, 180, 186)] == [30, 30, 60, 90, 180, 180, 180]


def test_probability_gap_and_low_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frozen_at(tmp_path, monkeypatch, poor={"revenue": [60]})
    f = forecast(series(50), START, "revenue", 60, seed=4)
    low, mid, high = f.quantiles(60)
    easy, hard, even = assess(f, low * 0.5, 1), assess(f, high * 2, 1), assess(f, mid, 1)
    assert (easy.probability, easy.verdict) == (1.0, "likely")
    assert (hard.probability, hard.verdict) == (0.0, "unlikely")
    assert even.probability == pytest.approx(0.5, abs=0.01)
    assert even.probability_range[0] < even.probability < even.probability_range[2]
    assert even.gap == pytest.approx((mid - high, 0.0, mid - low))
    assert even.forecast_range == (low, mid, high)
    assert even.deadline == START + timedelta(days=110)
    assert (even.shows_point, even.shown_probability, even.checkpoints) == (
        True,
        even.probability,
        (),
    )
    reasons = low_evidence(f)
    assert reasons[0] == "the goal's horizon is longer than the store's history"
    assert "revenue this far ahead were poorly calibrated" in reasons[1]
    assert not any(verify(r) for r in reasons)  # they reach the owner's text: no numbers
    assert low_evidence(forecast(series(200), START, "revenue", 30, seed=4)) == ()


def test_beyond_90_days_a_probability_is_a_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen_at(tmp_path, monkeypatch)
    f = forecast(series(200), START, "revenue", 182, seed=5)
    even = assess(f, f.quantiles(182)[1], 1)
    assert (even.shows_point, even.shown_probability) == (False, None)
    low, point, high = even.probability_range
    assert (low, high) == pytest.approx((point - 0.15, point + 0.15))
    assert even.verdict_band == ("stretch", "possible")
    assert even.checkpoints == (90, 180, 182)
    assert (checkpoints(90), checkpoints(91)) == ((), (90, 91))
    assert low_evidence(f)[0].startswith("past a quarter, probabilities were overconfident")
    assert not any(verify(r) for r in low_evidence(f))
    sure = assess(f, f.quantiles(182)[0] * 0.1, 1)
    assert sure.probability_range == (0.85, 1.0, 1.0)
    assert sure.verdict_band == ("likely", "likely")


@pytest.fixture(scope="module")
def store(app_engine: Engine) -> Any:
    config = bench_config(424_242).model_copy(update={"days": 90})
    data = generate(config)
    load(app_engine, data, config)
    return data.store.store_id


@pytest.mark.db
def test_daily_values_add_up_to_the_facts(app_engine: Engine, store: Any) -> None:
    with tenant_transaction(app_engine, store) as conn:
        s = load_series(conn, store)
        engine = FactEngine(conn, store)
        period = Period.days(s.start + timedelta(days=20), s.start + timedelta(days=48))
        for metric in fc.METRICS:
            window = sum(daily_values(s, metric)[20:48], Decimal(0))
            fact = engine.fact(metric, Scope.store(), period).value
            assert fact is not None
            if metric == "net_profit":  # fixed costs are prorated per day: division rounding
                assert abs(window - fact) < Decimal("1e-12")
            else:
                assert window == fact
    with pytest.raises(ValueError, match="no forecast for units"):
        daily_values(s, "units")


@pytest.mark.db
def test_a_goal_is_assessed_with_its_facts(app_engine: Engine, store: Any) -> None:
    with tenant_transaction(app_engine, store) as conn:
        end = conn.execute(
            text("SELECT max(ordered_at)::date + 1 FROM orders WHERE store_id = :s"), {"s": store}
        ).scalar_one()
        deadline = end + timedelta(days=45)
        done = assess_store(conn, store, "net_profit", Decimal("1000000"), deadline, currency="USD")
        again = assess_store(
            conn, store, "net_profit", Decimal("1000000"), deadline, currency="USD"
        )
    f = done.feasibility
    assert (f.verdict, f.probability, f.deadline) == ("unlikely", 0.0, deadline)
    assert sorted(done.forecast) == list(range(1, 46))
    last = done.forecast[45]
    assert (last.kind, last.formula_id, last.unit) == (
        FactKind.ESTIMATE,
        "goal.forecast.net_profit",
        Unit.MONEY,
    )
    assert last.method is not None
    assert last.method.startswith("goal_trend_block_bootstrap_v1;calibration ")
    assert last.period.end.date() == deadline
    assert last.p10 is not None
    assert last.p90 is not None
    assert last.p10 < last.p90
    assert len(last.lineage.parents) == 1
    assert done.probability.unit is Unit.RATIO
    assert done.probability.currency is None
    assert done.probability.value == Decimal("0.0000")
    assert done.gap.value is not None
    assert done.gap.value == Decimal("1000000") - last.p50  # type: ignore[operator]
    assert again.probability.id == done.probability.id  # the same facts, not new ones
    assert again.forecast[45].id == last.id
