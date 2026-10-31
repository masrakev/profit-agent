"""Calibrated outcome intervals: the split-conformal widening (app/causal/calibration.py) and
its fit on dev runs (bench/outcome_calibration.py)."""

import json
import math
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.causal import calibration
from app.causal.calibration import action_key, conformal_quantile, expand, score, widen
from bench.outcome_calibration import CalibrationError, fit, main, report
from bench.outcome_validation import Case, Run


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    calibration.frozen.cache_clear()
    yield
    calibration.frozen.cache_clear()


def frozen_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, widening: dict[str, float]) -> None:
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps({"version": "test", "target": 0.8, "widening": widening}))
    monkeypatch.setattr(calibration, "FROZEN", path)
    calibration.frozen.cache_clear()


def test_scores_and_the_conformal_quantile() -> None:
    assert score((0.0, 5.0, 10.0), 5.0) == -0.5  # in the middle
    assert score((0.0, 5.0, 10.0), 15.0) == 0.5  # half a width above P90
    assert score((0.0, 5.0, 10.0), -20.0) == 2.0
    assert score((3.0, 3.0, 3.0), 3.0) == 0.0
    assert score((3.0, 3.0, 3.0), 4.0) == math.inf
    assert conformal_quantile([0.1, 0.4, 0.2, 0.3]) == 0.4  # rank ceil(5 x 0.8) = 4 of 4
    assert conformal_quantile([x / 10 for x in range(10, 0, -1)]) == 0.9  # rank 9 of 10
    assert conformal_quantile([-0.3, -0.2, -0.1, -0.4]) == 0.0  # never narrowed
    assert conformal_quantile([0.1, 0.2]) == math.inf  # too few for the target
    assert conformal_quantile([]) == math.inf


def test_action_keys() -> None:
    assert action_key("pause_campaign", None, None) == "pause_campaign"
    cut = action_key("change_budget", {"daily_budget_minor": 100}, {"daily_budget_minor": 70})
    raised = action_key("change_budget", {"daily_budget_minor": 100}, {"daily_budget_minor": 120})
    assert (cut, raised) == ("reduce_budget", "increase_budget")
    assert action_key("change_budget", None, {"daily_budget_minor": 120}) == "reduce_budget"


def test_the_frozen_widening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert expand((0.0, 4.0, 10.0), 0.5) == (-5.0, 4.0, 15.0)
    frozen_at(tmp_path, monkeypatch, {"pause_campaign": 0.5, "reduce_budget": 0.1})
    assert widen((0.0, 4.0, 10.0), "pause_campaign") == (-5.0, 4.0, 15.0)
    assert widen((0.0, 4.0, 10.0), "reduce_budget") == (-1.0, 4.0, 11.0)
    assert widen((0.0, 4.0, 10.0), "resume_campaign") == (-5.0, 4.0, 15.0)  # the widest
    frozen_at(tmp_path, monkeypatch, {})
    assert widen((0.0, 4.0, 10.0), "pause_campaign") == (0.0, 4.0, 10.0)


def test_the_committed_calibration_is_well_formed() -> None:
    data = calibration.frozen()
    assert data["target"] == calibration.TARGET
    assert all(q >= 0 for q in data["widening"].values())


def case(action: str, raw: tuple[float, float, float], truth: float, widening: float = 0.0) -> Case:
    return Case("dev-x", action, "measured", "measured", 0.2, raw, raw, truth, widening)


def runs() -> list[Run]:
    pauses = [case("pause", (-10.0, 0.0, 10.0), t) for t in (0.0, 5.0, 25.0, 30.0, 40.0)]
    cuts = [case("budget -30%", (-10.0, 0.0, 10.0), t) for t in (0.0, 1.0, 2.0, 3.0, 4.0)]
    withheld = Case("dev-y", "pause", "abstained", "weak", 0.7, None, (-1.0, 0.0, 1.0), 9.0)
    return [Run("a", "dev", [*pauses, withheld]), Run("b", "dev", cuts)]


def test_the_fit_per_action_kind() -> None:
    fitted = fit(runs())
    assert fitted["fitted_on"] == ["a", "b"]
    assert fitted["n"] == {"pause_campaign": 5, "reduce_budget": 5}
    # pauses: scores -0.5, -0.25, 0.75, 1.0, 1.5; rank ceil(6 x 0.8) = 5
    assert fitted["widening"] == {"pause_campaign": 1.5, "reduce_budget": 0.0}
    text = report(runs(), fitted)
    assert "| pause_campaign | 5 | 40% | 1.5000 | 4.00 | 100% | 0.750 |" in text
    assert "| reduce_budget | 5 | 100% | 0.0000 | 1.00 | 100% | -0.400 |" in text


def test_the_fit_refuses_other_suites_and_calibrated_runs() -> None:
    with pytest.raises(CalibrationError, match="dev scenarios only"):
        fit([Run("fresh", "outcomes_v1", runs()[0].cases)])
    with pytest.raises(CalibrationError, match="already calibrated"):
        fit([Run("again", "dev", [case("pause", (0.0, 1.0, 2.0), 1.0, widening=0.3)])])


def test_the_fit_is_written_and_frozen(tmp_path: Path) -> None:
    paths = []
    for r in runs():
        path = tmp_path / f"{r.run_id}.json"
        cases = [c.__dict__ for c in r.cases]
        path.write_text(json.dumps({"run_id": r.run_id, "suite": r.suite, "cases": cases}))
        paths.append(path)
    frozen = tmp_path / "frozen.json"
    argv = ["--from", str(paths[0]), "--from", str(paths[1]), "--frozen", str(frozen)]
    assert main([*argv, "--out", str(tmp_path)]) == 0
    written = json.loads(frozen.read_text(encoding="utf-8"))
    assert written["version"] == "conformal-v1"
    assert written["widening"]["pause_campaign"] == 1.5
    assert (
        (tmp_path / "outcome-calibration.md")
        .read_text(encoding="utf-8")
        .startswith("# Outcome calibration")
    )
