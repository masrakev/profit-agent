"""Fit the outcome calibration (Task 5): a split-conformal widening per action kind.

    uv run python -m bench.outcome_calibration --from <dev run>.json --from ...
        # writes backend/app/causal/outcome_calibration.json (frozen) and
        # bench/reports/outcome-calibration.md

Fitted on dev decision scenarios only: a run on another suite is refused, and so is a run
whose intervals were already calibrated. For each action kind, the reported estimates' raw
intervals and the truth give the scores of `app.causal.calibration`; the widening is their
split-conformal quantile. Once written, the widening is frozen: the validation on fresh
scenarios (`outcomes_v1`, bench/outcome_validation.py) runs with it and is reported once.
"""

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from app.causal import calibration
from app.causal.calibration import TARGET, conformal_quantile, expand, score
from bench.outcome_validation import KEYS, Run, load_run, merge
from bench.runner.report import REPORT_DIR

VERSION = "conformal-v1"


class CalibrationError(ValueError):
    pass


def _up(x: float) -> float:
    """Rounded up to 4 decimals: rounding never narrows the interval below the fit."""
    return math.ceil(x * 10_000) / 10_000 if math.isfinite(x) else x


def scores(runs: list[Run]) -> dict[str, list[tuple[float, tuple[float, float, float], float]]]:
    """Per action kind: (score, raw interval, truth) of every reported estimate."""
    out: dict[str, list[tuple[float, tuple[float, float, float], float]]] = {}
    for run in runs:
        if run.suite != "dev":
            raise CalibrationError(f"{run.run_id}: the calibration is fitted on dev scenarios only")
        for c in run.cases:
            if c.measured is None or c.unthresholded is None:
                continue
            if c.widening:
                raise CalibrationError(f"{run.run_id}: its intervals are already calibrated")
            raw = c.unthresholded
            out.setdefault(KEYS[c.action], []).append((score(raw, c.truth), raw, c.truth))
    return dict(sorted(out.items()))


def fit(runs: list[Run]) -> dict[str, Any]:
    by_key = scores(runs)
    return {
        "version": VERSION,
        "target": TARGET,
        "fitted_on": [r.run_id for r in runs],
        "n": {k: len(v) for k, v in by_key.items()},
        "widening": {k: _up(conformal_quantile([s for s, _, _ in v])) for k, v in by_key.items()},
    }


def _coverage(rows: list[tuple[float, tuple[float, float, float], float]], q: float) -> float:
    inside = 0
    for _, raw, truth in rows:
        low, _, high = expand(raw, q)
        inside += low <= truth <= high
    return inside / len(rows)


def report(runs: list[Run], fitted: dict[str, Any]) -> str:
    by_key = scores(runs)
    cases = merge(runs).cases
    lines = [
        "# Outcome calibration",
        "",
        f"Fitted by `uv run python -m bench.outcome_calibration` on {len(cases)} dev decision "
        "scenarios (" + ", ".join(f"`{r}`" for r in fitted["fitted_on"]) + "): every dev store, "
        "each action executed 14 days before the data end and measured after 7 days, against "
        "the same store without the action. Frozen in "
        f"`backend/app/causal/outcome_calibration.json` (`{fitted['version']}`) before the "
        "validation on fresh scenarios.",
        "",
        "Score of a reported estimate: max(P10 - truth, truth - P90) / (P90 - P10). Widening: "
        f"the split-conformal quantile of the scores, rank ceil((n + 1) x {TARGET}), never "
        "negative; the interval becomes [P10 - q w, P90 + q w], the median unchanged.",
        "",
        "| Action kind | Reported estimates | Coverage before | Widening q | Interval width x | "
        "Coverage after (in sample) | Median score |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, rows in by_key.items():
        q = fitted["widening"][key]
        lines.append(
            f"| {key} | {len(rows)} | {_coverage(rows, 0.0):.0%} | {q:.4f} | {1 + 2 * q:.2f} | "
            f"{_coverage(rows, q):.0%} | {statistics.median(s for s, _, _ in rows):.3f} |"
        )
    lines += [
        "",
        "In-sample coverage is at least the target by construction; what the widening is worth "
        "is measured once, on fresh stores (`bench/reports/outcome-validation-fresh.md`). A kind "
        "with no fit (a resume) gets the widest widening.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit the outcome calibration on dev runs")
    parser.add_argument("--from", dest="saved", type=Path, action="append", required=True)
    parser.add_argument("--frozen", type=Path, default=calibration.FROZEN)
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    runs = [load_run(p) for p in args.saved]
    fitted = fit(runs)
    args.frozen.write_text(json.dumps(fitted, indent=2) + "\n", encoding="utf-8", newline="\n")
    calibration.frozen.cache_clear()
    text = report(runs, fitted)
    (args.out / "outcome-calibration.md").write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
