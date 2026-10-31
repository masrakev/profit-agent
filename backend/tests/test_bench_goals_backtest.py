"""The goal forecast backtest (bench/goals_backtest.py), on synthetic daily values."""

import json
import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import bench.goals_backtest as gb
from app.goals import forecast as fc
from bench.scenarios.build import bench_config
from bench.scenarios.manifest import ScenarioManifest

START = date(2025, 8, 26)


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    fc.frozen.cache_clear()
    yield
    fc.frozen.cache_clear()


def values(stores: int = 4) -> dict[str, tuple[date, dict[str, np.ndarray]]]:
    out = {}
    for k in range(stores):
        rng = np.random.default_rng(k)
        t = np.arange(400, dtype=np.float64)
        base = 1000.0 + (k - 1.5) * t + 100.0 * np.sin(t / 30.0)
        out[f"store-{k}"] = (
            START,
            {m: base * (1.0 + i) + rng.normal(0.0, 80.0, 400) for i, m in enumerate(fc.METRICS)},
        )
    return out


def test_naive_baseline() -> None:
    history = np.array([10.0, 12.0] * 20)
    (low, mid, high), m, sd = gb.naive(history, 9)
    assert (m, mid) == (11.0 * 9, 11.0 * 9)
    assert sd == pytest.approx(float(history[-28:].std(ddof=1)) * 3)
    assert (low, high) == pytest.approx((mid - gb.Z90 * sd, mid + gb.Z90 * sd))
    assert gb._normal_above(mid, mid, sd) == 0.5
    assert (gb._normal_above(5.0, 6.0, 0.0), gb._normal_above(7.0, 6.0, 0.0)) == (1.0, 0.0)


def test_cases_scores_and_calibration() -> None:
    cases = gb.all_cases(values(2), 91, None)
    per_store = 3 * (6 + 5 + 5 + 2)  # metrics x (cut, horizon) pairs that fit in 400 days
    assert len(cases) == 2 * per_store
    c = cases[0]
    assert (c.scenario, c.metric, c.cut, c.horizon, c.bucket) == (
        "store-0",
        "net_profit",
        150,
        30,
        30,
    )
    assert len(c.targets) == len(gb.AMBITIONS) == len(c.reached) == len(c.naive_p)
    assert c.finals.shape == (fc.DRAWS,)
    low, mid, high = c.interval(2.0)
    assert (mid, high - mid) == pytest.approx((c.raw[1], 2.0 * (c.raw[2] - c.raw[1])))
    assert mid - low == pytest.approx(2.0 * (c.raw[1] - c.raw[0]))
    inside = c.raw[0] <= c.truth <= c.raw[2]
    assert (c.score() <= 1.0) == inside
    assert gb.conformal([0.2, 0.9, 0.5, 0.1]) == 0.9
    assert gb.conformal([]) == 1.0
    scales = gb.fit_scales(cases)
    assert set(scales) == set(fc.METRICS)
    assert set(scales["revenue"]) == {"30", "60", "90", "180"}
    result = gb.evaluate(cases, scales)
    assert result["cases"] == len(cases)
    assert result["goals"] == len(cases) * len(gb.AMBITIONS)
    assert set(result["by_horizon"]) == {"30", "60", "90", "180"}
    assert result["by_horizon"]["30"]["coverage"] is not None
    assert 0 <= result["brier"] <= 1
    assert gb.coverage([], "model", scales) is None
    assert gb.brier([]) is None
    rows = gb.reliability([(0.05, False), (0.05, True), (1.0, True)])
    assert [(r["bucket"], r["n"], r["observed"]) for r in rows] == [
        ([0.0, 0.1], 2, 0.5),
        ([0.9, 1.0], 1, 1.0),
    ]
    assert gb.mean_error(rows) == pytest.approx((2 * 0.45 + 0.0) / 3)
    assert gb.mean_error([]) == 0.0
    assert result["by_horizon"]["180"]["reliability"]
    cv = gb.cross_validated(cases)
    assert cv["cases"] == len(cases)
    assert set(cv["coverage"]) == {"30", "60", "90", "180"}
    flagged = gb.poor(cases)
    assert all(set(v) <= {30, 60, 90, 180} for v in flagged.values())


def test_checks_name_every_target() -> None:
    result: dict[str, Any] = {
        "by_horizon": {"30": {"coverage": 0.8}, "60": {"coverage": 0.7}},
        "reliability": [{"bucket": [0.1, 0.2], "n": 50, "error": -0.12}],
        "brier": 0.1,
        "brier_naive": 0.2,
    }
    lines = gb.checks(result)
    assert lines[0].endswith("80% (target 75-85%): met.")
    assert lines[1].endswith("70% (target 75-85%): missed.")
    assert "missed (worst: 10%-20%, -12.0 points)" in lines[2]
    assert lines[3].endswith(": met.")
    result["reliability"] = [{"bucket": [0.1, 0.2], "n": 5, "error": -0.5}]
    assert gb.checks(result)[2].endswith(": met.")  # thin buckets are not judged


def test_the_backtest_fits_freezes_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gb, "load_values", lambda suite, database: values(4))
    monkeypatch.setattr(gb, "SETTINGS", ((91, None),))
    frozen = tmp_path / "calibration.json"
    frozen.write_text(json.dumps({"version": "uncalibrated", "scales": {}, "poor": {}}))
    args = ["--out", str(tmp_path), "--frozen", str(frozen)]
    assert gb.main(["--suite", "goals_dev", "--tune", "--fit", *args]) == 0
    calibration = json.loads(frozen.read_text(encoding="utf-8"))
    assert calibration["version"] == gb.VERSION
    assert calibration["settings"] == {"window": fc.FIT_DAYS, "half_life": fc.TREND_HALF_LIFE}
    assert set(calibration["scales"]) == set(fc.METRICS)
    dev = (tmp_path / "goals-backtest-dev.md").read_text(encoding="utf-8")
    assert dev.startswith("# Goal forecasts: backtest (`goals_dev`)")
    assert "| 91 days | linear |" in dev
    assert "| 180 days |" in dev.split("By horizon")[1]
    assert gb.main(["--suite", "goals_test", *args]) == 0
    test = (tmp_path / "goals-backtest.md").read_text(encoding="utf-8")
    assert "calibration `conformal-v1`" in test
    assert "Settings compared" not in test
    assert len(list(tmp_path.glob("goals-backtest-goals_*.json"))) == 2
    with pytest.raises(SystemExit):
        gb.main(["--suite", "goals_test", "--fit", *args])  # never tuned on the hold-out


def test_values_are_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gb, "CACHE", tmp_path)
    (tmp_path / "goals_dev.json").write_text(
        json.dumps({"s": {"start": "2025-08-26", "values": {"revenue": [1.0, 2.0]}}})
    )
    [(start, vals)] = gb.load_values("goals_dev", "unused").values()
    assert start == START
    assert vals["revenue"].tolist() == [1.0, 2.0]


@pytest.mark.db
def test_values_are_read_from_the_database(
    database_urls: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = bench_config(515_151).model_copy(update={"days": 60})
    manifest = ScenarioManifest(
        scenario_id="goals_dev-small", suite="goals_dev", description="small", config=config
    )
    monkeypatch.setattr(gb, "CACHE", tmp_path)
    monkeypatch.setattr(gb, "load_suite", lambda suite: [manifest])
    database = os.environ.get("TEST_DATABASE_NAME", "profit_test") + "_goals"
    [(start, vals)] = gb.load_values("goals_dev", database).values()
    assert start == config.start_date
    assert {len(v) for v in vals.values()} == {60}
    assert (tmp_path / "goals_dev.json").exists()
