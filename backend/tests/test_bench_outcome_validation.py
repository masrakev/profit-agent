"""Outcome validation against the truth (bench/outcome_validation.py)."""

import json
from pathlib import Path

import pytest

from app.causal import control
from bench.outcome_validation import (
    ACTIONS,
    Case,
    load_cases,
    main,
    markdown,
    run,
    summarize,
    verdict,
)
from bench.scenarios.manifest import load_suite


def case(action: str, rel: float, est: tuple[float, float, float] | None, truth: float) -> Case:
    reported = est if rel < 0.5 else None
    return Case(
        scenario=f"dev-{action}-{rel}",
        action=action,
        status="measured" if reported else "abstained",
        reason="measured" if reported else "the pre-period fit is too weak",
        relative_error=rel,
        measured=reported,
        unthresholded=est,
        truth=truth,
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
    assert s["by_action"]["pause"]["coverage"] == 0.5
    assert s["by_action"]["budget +20%"] == {"n": 0}
    bands = {tuple(b["band"]): b["n"] for b in s["unthresholded_by_relative_error"]}
    assert bands == {(0.0, 0.25): 2, (0.25, 0.5): 1, (0.5, 1.0): 1, (1.0, float("inf")): 0}


def test_the_verdict_on_the_threshold() -> None:
    lines = verdict(summarize(CASES), CASES)
    assert "67% of the time" in lines[0]
    assert "most for pause (50%)" in lines[0]
    assert lines[1].startswith("Threshold 0.5: refuted on these runs. The 1 estimates")
    worse = [*CASES[:3], case("budget +20%", 0.7, (100.0, 200.0, 300.0), 0.0)]
    assert "supported on these runs" in verdict(summarize(worse), worse)[1]
    none = CASES[:3]
    assert "neither validate nor refute" in verdict(summarize(none), none)[1]
    good = [case("pause", 0.1, (-10.0, 0.0, 10.0), 5.0)]
    assert verdict(summarize(good), good)[0].endswith("against the 80% target.")


def test_the_report_is_rewritten_from_a_saved_run(tmp_path: Path) -> None:
    saved = tmp_path / "run.json"
    saved.write_text(
        json.dumps({"run_id": "outcome-validation-x", "cases": [c.__dict__ for c in CASES]})
    )
    run_id, cases = load_cases(saved)
    assert (run_id, cases) == ("outcome-validation-x", CASES)
    assert main(["--from", str(saved), "--out", str(tmp_path)]) == 0
    text = (tmp_path / "outcome-validation.md").read_text(encoding="utf-8")
    assert text == markdown(run_id, summarize(CASES), CASES)
    assert "| dev-budget +20%-0.7 | budget +20% | abstained | 0.70 |" in text
    assert "| 0.5 to 1.0 | 1 | 100% |" in text


@pytest.mark.db
def test_a_run_against_untreated_twins(
    database_urls: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One scenario, with a threshold no fit passes: the withheld estimate is still made."""
    monkeypatch.setattr(control, "MAX_RELATIVE_ERROR", 0.0)
    databases = ("profit_outcomes_treated_test", "profit_outcomes_control_test")
    run_id, cases = run(len(load_suite("dev")), tmp_path, databases)
    [result] = cases
    assert result.scenario == load_suite("dev")[0].scenario_id
    assert result.action == ACTIONS[0][0]
    assert (result.status, result.measured) == ("abstained", None)
    assert result.relative_error is not None
    assert result.unthresholded is not None
    assert result.truth < 0  # pausing the largest campaign loses what it contributed
    assert control.MAX_RELATIVE_ERROR == 0.0
    assert load_cases(next(tmp_path.glob("outcome-validation-*.json"))) == (run_id, cases)
