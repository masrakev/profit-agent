"""Outcome validation against the truth (bench/outcome_validation.py)."""

import json
import os
from pathlib import Path

import pytest

from app.causal import control
from bench.outcome_validation import (
    Case,
    Run,
    load_run,
    main,
    markdown,
    merge,
    run,
    summarize,
    verdict,
)
from bench.scenarios.manifest import load_suite


def case(
    action: str,
    rel: float,
    est: tuple[float, float, float] | None,
    truth: float,
    widening: float = 0.0,
) -> Case:
    raw = est
    reported = None
    if est is not None and rel <= 0.5:
        p10, p50, p90 = est
        gap = widening * (p90 - p10)
        reported = (p10 - gap, p50, p90 + gap)
    return Case(
        scenario=f"dev-{action}-{rel}",
        action=action,
        status="measured" if reported else "abstained",
        reason="measured" if reported else "the pre-period fit is too weak",
        relative_error=rel,
        measured=reported,
        unthresholded=raw,
        truth=truth,
        widening=widening if reported else 0.0,
    )


CASES = [
    case("pause", 0.1, (-10.0, 0.0, 10.0), 5.0),  # covered, error -5
    case("pause", 0.3, (-10.0, 0.0, 10.0), 50.0),  # missed, error -50
    case("budget -30%", 0.2, (0.0, 20.0, 40.0), 30.0),  # covered, error -10
    case("budget +20%", 0.7, (-100.0, 0.0, 100.0), 10.0),  # withheld, covered, error -10
]


def test_summary_and_bands() -> None:
    s = summarize(CASES)
    assert (s["cases"], s["measured"], s["abstention_rate"]) == (4, 3, 0.25)
    assert s["abstained_because"] == {"the pre-period fit is too weak": 1}
    m = s["measured_intervals"]
    assert (m["n"], m["coverage"], m["bias"], m["mae"]) == (3, 0.667, -21.67, 21.67)
    assert s["raw_intervals"]["coverage"] == 0.667
    assert s["calibrated"] is False
    assert s["by_action"]["pause"]["coverage"] == 0.5
    assert s["by_action"]["budget +20%"] == {"n": 0, "raw_coverage": None}
    bands = {tuple(b["band"]): b["n"] for b in s["unthresholded_by_relative_error"]}
    assert bands == {(0.0, 0.25): 2, (0.25, 0.5): 1, (0.5, 1.0): 1, (1.0, float("inf")): 0}


def test_a_calibrated_run_is_reported_against_its_raw_intervals() -> None:
    widened = [case("pause", 0.3, (-10.0, 0.0, 10.0), 15.0, widening=0.5), *CASES[2:]]
    s = summarize(widened)
    assert widened[0].measured == (-20.0, 0.0, 20.0)
    assert s["calibrated"] is True
    assert (s["measured_intervals"]["coverage"], s["raw_intervals"]["coverage"]) == (1.0, 0.5)
    assert s["by_action"]["pause"] == {**s["by_action"]["pause"], "raw_coverage": 0.0}
    lines = verdict(s, widened)
    assert "100% of the time against the 80% target (50% without the calibration)" in lines[0]
    assert "the lowest is budget -30% (100%)" in lines[0]  # a tie: the first by name
    assert widened[2].calibrated() == widened[2].unthresholded  # withheld: no widening known


def test_the_verdict_reports_the_threshold_s_effect() -> None:
    lines = verdict(summarize(CASES), CASES)
    assert "67% of the time" in lines[0]
    assert "most for pause (50%)" in lines[0]
    assert lines[1].startswith("Threshold 0.5: it withholds 1 of 4 estimates (25%).")
    assert "no worse than those it reports (only 1 estimates above it)." in lines[1]
    worse = [*CASES[:3], case("budget +20%", 0.7, (100.0, 200.0, 300.0), 0.0)]
    assert "withholds are worse than those it reports" in verdict(summarize(worse), worse)[1]
    none = CASES[:3]
    assert "say nothing of its effect" in verdict(summarize(none), none)[1]
    good = [case("pause", 0.1, (-10.0, 0.0, 10.0), 5.0)]
    assert verdict(summarize(good), good)[0].endswith("the lowest is pause (100%).")


def test_saved_runs_are_merged_into_one_report(tmp_path: Path) -> None:
    paths = []
    for i, part in enumerate((CASES[:2], CASES[2:])):
        path = tmp_path / f"run{i}.json"
        cases = [c.__dict__ for c in part]
        path.write_text(json.dumps({"run_id": f"r{i}", "suite": "outcomes_v1", "cases": cases}))
        paths.append(path)
    first = load_run(paths[0])
    assert (first.run_id, first.suite, first.cases) == ("r0", "outcomes_v1", CASES[:2])
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"run_id": "x", "cases": [CASES[0].__dict__]}))
    assert load_run(legacy).suite == "dev"
    args = ["--from", str(paths[0]), "--from", str(paths[1]), "--out", str(tmp_path)]
    assert main([*args, "--report", "fresh.md"]) == 0
    text = (tmp_path / "fresh.md").read_text(encoding="utf-8")
    merged = merge([load_run(p) for p in paths])
    assert merged == Run("r0, r1", "outcomes_v1", CASES)
    assert text == markdown(merged, summarize(CASES))
    assert text.startswith("# Outcome validation (`outcomes_v1`)\n\nRuns `r0`, `r1`: 4 actions")
    assert "| dev-budget +20%-0.7 | budget +20% | abstained | 0.70 |" in text
    assert "| -100 / 100 | 10 |" in text
    assert "| 0.5 to 1.0 | 1 | 100% |" in text


@pytest.mark.db
def test_a_run_against_untreated_twins(
    database_urls: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One scenario, one action, with a threshold no fit passes: the withheld estimate is
    still made."""
    monkeypatch.setattr(control, "MAX_RELATIVE_ERROR", 0.0)
    test_db = os.environ.get("TEST_DATABASE_NAME", "profit_test")  # two runs never share them
    databases = (f"{test_db}_outcomes_treated", f"{test_db}_outcomes_control")
    every = len(load_suite("dev")) // 2  # stores 0 and `every`; part 2 of 2 is the second
    done = run(every, tmp_path, databases, action="budget -30%", part=(2, 2))
    assert done.run_id.startswith("outcome-validation-dev-cut-")
    assert done.run_id.endswith("-part2of2")
    [result] = done.cases
    assert result.scenario == load_suite("dev")[every].scenario_id
    assert result.action == "budget -30%"
    assert (result.status, result.measured) == ("abstained", None)
    assert result.relative_error is not None
    assert result.unthresholded is not None
    assert result.truth != 0  # the cut changed what the campaign contributed
    low, mid, high = result.unthresholded
    assert low <= mid <= high
    assert control.MAX_RELATIVE_ERROR == 0.0
    assert load_run(tmp_path / f"{done.run_id}.json") == done
