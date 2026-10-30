"""Split-conformal calibration of the twin's intervals (bench/twin/calibrate.py)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from bench.twin.calibrate import (
    conformal_factor,
    covered,
    fit_calibration,
    main,
    markdown,
    score,
    summarize,
)


def record(scenario: str, kind: str, metric: str, actual: float) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "variant": "do_nothing" if kind == "do_nothing" else "budget_-30%",
        "kind": kind,
        "metric": metric,
        "p10": 90.0,
        "p50": 100.0,
        "p90": 110.0,
        "actual": actual,
        "low_evidence": [],
    }


def test_scores_and_coverage() -> None:
    # Signed: negative inside the interval (so intervals that were too wide can narrow).
    assert score(record("s", "do_nothing", "units", 100)) == pytest.approx(-1.0)
    assert score(record("s", "do_nothing", "units", 115)) == pytest.approx(0.5)
    assert score(record("s", "do_nothing", "units", 80)) == pytest.approx(1.0)
    flat = {**record("s", "do_nothing", "units", 5), "p10": 5.0, "p90": 5.0}
    assert score(flat) == 0.0
    assert score({**flat, "actual": 6.0}) == float("inf")
    assert covered(record("s", "do_nothing", "units", 115), 0.5)
    assert not covered(record("s", "do_nothing", "units", 115), 0.0)


def test_conformal_factor_reaches_the_target() -> None:
    scores = [x / 10 for x in range(10)]  # 0.0 .. 0.9
    q = conformal_factor(scores, target=0.8)
    assert sum(s <= q for s in scores) / len(scores) >= 0.8
    assert conformal_factor([0.3]) == 0.3


def test_fit_and_summarize() -> None:
    records = [
        record(f"s{i:02d}", kind, metric, 100 + (i % 7) * 4)
        for i in range(20)
        for kind in ("do_nothing", "action")
        for metric in ("contribution_margin", "net_profit", "units", "ad_spend")
    ]
    cal = fit_calibration(records, version=4)
    assert cal.version == 4
    assert set(cal.do_nothing) == {"contribution_margin", "net_profit", "units", "ad_spend"}
    summary = summarize(records, cal)
    assert summary["overall"]["evaluation_scenarios"] == 10
    assert summary["overall"]["calibrated_coverage"] >= summary["overall"]["raw_coverage"]
    text = markdown(summary, cal, datetime(2026, 10, 29, tzinfo=UTC))
    assert "calibration v4" in text


def test_the_hold_out_is_only_checked() -> None:
    records = [record(f"s{i}", "do_nothing", "units", 100) for i in range(6)]
    cal = fit_calibration(records, version=2)
    every = summarize(records, cal, every_scenario=True)["overall"]
    assert (every["n_evaluation"], every["evaluation_scenarios"]) == (6, 6)
    text = markdown(summarize(records, cal, every_scenario=True), cal, datetime.now(UTC), "test_v3")
    assert "# Twin calibration (`test_v3`)" in text
    assert "nothing was refitted" in text
    with pytest.raises(SystemExit):
        main(["--suite", "test_v3"])  # fitting on the hold-out is refused
