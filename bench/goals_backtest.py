"""Backtest the goal forecasts against what happened (Task 6 A4, ADR 0023).

    uv run python -m bench.goals_backtest --suite goals_dev --tune --fit
        # compares forecast settings by cross-validation, fits the calibration with the frozen
        # settings and writes it (backend/app/goals/calibration.json); goals-backtest-dev.md
    uv run python -m bench.goals_backtest --suite goals_test
        # once, with everything frozen: bench/reports/goals-backtest.md

Each store of the suite is generated and loaded, and its daily series read as in production.
Its history is cut at several days; from each cut the net profit, contribution margin and
revenue are forecast 30, 60, 90 and 180 days ahead (when the data goes that far) and compared
with what happened.

Goals: at each cut and horizon, targets of varied ambition are set around the store's run
rate at the cut (the last 28 days' mean, times the horizon), from 40% below to 40% above it
(in units of the run rate's absolute level). They are set from what the owner knows at the
cut, not from the outcome: targets placed around the realised outcome would decide whether
each is reached by construction and bias the reliability curve. For each target: the
predicted probability and whether it was reached.

The naive baseline is the last-period run rate: the mean of the last 28 days times the
horizon, with a normal spread from those days' standard deviation times the square root of
the horizon.
"""

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.config import repo_path
from app.db import make_engine, tenant_transaction
from app.detection.series import load_series
from app.domain.hashing import canonical_json, sha256_hex
from app.goals import forecast as fc
from app.goals.feasibility import bucket
from app.goals.forecast import BUCKETS, METRICS, FloatArray
from app.observability import configure_logging
from bench.generator.load import load
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR
from bench.scenarios.manifest import Suite, load_suite

CUTS = (150, 190, 230, 270, 310, 350)  # days of history at each forecast
AMBITIONS = (-0.4, -0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2, 0.4)
RUN_RATE_DAYS = 28
TARGET = 0.8
COVERAGE_BAND = (0.75, 0.85)
RELIABILITY_TOLERANCE = 0.10
THIN = 20  # reliability buckets with fewer goals are reported, not judged
Z90 = 1.2815515655446004  # standard normal 90th percentile
VERSION = "conformal-v1"
CACHE = repo_path("data/goals")
# Settings compared on goals_dev (fit window in days, trend half-life in days or None).
SETTINGS = (
    (42, None),
    (56, None),
    (70, None),
    (91, None),
    (182, None),
    (364, None),
    (56, 60.0),
    (56, 120.0),
    (70, 60.0),
    (91, 60.0),
    (182, 60.0),
    (182, 0.0),
    (364, 0.0),
)


@dataclass
class Case:
    scenario: str
    metric: str
    cut: int
    horizon: int
    truth: float
    raw: tuple[float, float, float]  # the forecast's P10, P50, P90 before calibration
    naive: tuple[float, float, float]
    targets: list[float]
    reached: list[bool]
    naive_p: list[float]
    finals: FloatArray = field(repr=False)  # raw cumulative draws at the horizon

    @property
    def bucket(self) -> int:
        return bucket(self.horizon)

    def interval(self, s: float) -> tuple[float, float, float]:
        p10, p50, p90 = self.raw
        return (p50 + s * (p10 - p50), p50, p50 + s * (p90 - p50))

    def probabilities(self, s: float) -> list[float]:
        median = float(np.median(self.finals))
        scaled = median + s * (self.finals - median)
        return [float((scaled >= t).mean()) for t in self.targets]

    def score(self) -> float:
        """How far out of its raw P10-P90 the truth fell, in units of the side it fell on."""
        p10, p50, p90 = self.raw
        low, high = max(p50 - p10, 1e-9), max(p90 - p50, 1e-9)
        return max((p50 - self.truth) / low, (self.truth - p50) / high)


def _seed(*parts: object) -> int:
    return int(sha256_hex(canonical_json([str(p) for p in parts]))[:16], 16)


# --- data ---------------------------------------------------------------------------------------


def load_values(suite: Suite, database: str) -> dict[str, tuple[date, dict[str, FloatArray]]]:
    """Per scenario: its first day and the daily values of each metric, cached in data/goals."""
    cache = CACHE / f"{suite}.json"
    if cache.exists():
        raw = json.loads(cache.read_text(encoding="utf-8"))
        return {
            k: (date.fromisoformat(v["start"]), {m: np.array(x) for m, x in v["values"].items()})
            for k, v in raw.items()
        }
    engine = make_engine(prepare_database(database))
    out: dict[str, tuple[date, dict[str, FloatArray]]] = {}
    for manifest in load_suite(suite):
        data = manifest.generate()
        load(engine, data, manifest.config)
        with tenant_transaction(engine, data.store.store_id) as conn:
            series = load_series(conn, data.store.store_id)
        out[manifest.scenario_id] = (
            series.start,
            {m: np.array([float(v) for v in fc.daily_values(series, m)]) for m in METRICS},
        )
    engine.dispose()
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                k: {"start": s.isoformat(), "values": {m: v.tolist() for m, v in vals.items()}}
                for k, (s, vals) in out.items()
            }
        ),
        encoding="utf-8",
    )
    return out


# --- cases --------------------------------------------------------------------------------------


def naive(history: FloatArray, horizon: int) -> tuple[tuple[float, float, float], float, float]:
    recent = history[-RUN_RATE_DAYS:]
    mid = float(recent.mean()) * horizon
    sd = float(recent.std(ddof=1)) * math.sqrt(horizon)
    return (mid - Z90 * sd, mid, mid + Z90 * sd), mid, sd


def _normal_above(x: float, mid: float, sd: float) -> float:
    if sd <= 0:
        return 1.0 if mid >= x else 0.0
    return 0.5 * math.erfc((x - mid) / (sd * math.sqrt(2)))


def cases_for(
    scenario: str,
    start: date,
    values: dict[str, FloatArray],
    window: int,
    half_life: float | None,
) -> list[Case]:
    out = []
    for metric, series in values.items():
        for cut in CUTS:
            horizons = [h for h in BUCKETS if cut + h <= len(series)]
            if not horizons:
                continue
            history = series[:cut]
            f = fc.forecast(
                history,
                start,
                metric,
                max(horizons),
                _seed(scenario, metric, cut),
                window=window,
                half_life=half_life,
                calibrated=False,
            )
            level = float(np.abs(history[-RUN_RATE_DAYS:]).mean())
            for h in horizons:
                band, mid, sd = naive(history, h)
                targets = [mid + a * level * h for a in AMBITIONS]
                truth = float(series[cut : cut + h].sum())
                out.append(
                    Case(
                        scenario=scenario,
                        metric=metric,
                        cut=cut,
                        horizon=h,
                        truth=truth,
                        raw=f.quantiles(h),
                        naive=band,
                        targets=targets,
                        reached=[truth >= t for t in targets],
                        naive_p=[_normal_above(t, mid, sd) for t in targets],
                        finals=f.paths[:, h - 1].copy(),
                    )
                )
    return out


def all_cases(
    values: dict[str, tuple[date, dict[str, FloatArray]]], window: int, half_life: float | None
) -> list[Case]:
    return [
        c
        for scenario, (start, vals) in sorted(values.items())
        for c in cases_for(scenario, start, vals, window, half_life)
    ]


# --- calibration and scores ---------------------------------------------------------------------


def conformal(scores: list[float], target: float = TARGET) -> float:
    n = len(scores)
    rank = math.ceil((n + 1) * target)
    return sorted(scores)[min(rank, n) - 1] if n else 1.0


def fit_scales(cases: list[Case]) -> dict[str, dict[str, float]]:
    """Per metric and horizon bucket: the conformal factor of the raw intervals (above 1 widens,
    below 1 narrows)."""
    out: dict[str, dict[str, float]] = {}
    for metric in METRICS:
        for b in BUCKETS:
            scores = [c.score() for c in cases if c.metric == metric and c.bucket == b]
            if scores:
                out.setdefault(metric, {})[str(b)] = round(conformal(scores), 4)
    return out


def _s(scales: dict[str, dict[str, float]], c: Case) -> float:
    return scales.get(c.metric, {}).get(str(c.bucket), 1.0)


def coverage(cases: list[Case], which: str, scales: dict[str, dict[str, float]]) -> float | None:
    if not cases:
        return None
    inside = 0
    for c in cases:
        low, _, high = (
            c.naive if which == "naive" else c.interval(_s(scales, c) if which == "model" else 1.0)
        )
        inside += low <= c.truth <= high
    return inside / len(cases)


def goals(
    cases: list[Case], which: str, scales: dict[str, dict[str, float]]
) -> list[tuple[float, bool]]:
    """(predicted probability, reached) for every target of every case."""
    out: list[tuple[float, bool]] = []
    for c in cases:
        ps = c.naive_p if which == "naive" else c.probabilities(_s(scales, c))
        out.extend(zip(ps, c.reached, strict=True))
    return out


def brier(pairs: list[tuple[float, bool]]) -> float | None:
    return statistics.mean((p - float(r)) ** 2 for p, r in pairs) if pairs else None


def reliability(pairs: list[tuple[float, bool]]) -> list[dict[str, Any]]:
    rows = []
    for k in range(10):
        low, high = k / 10, (k + 1) / 10
        mine = [(p, r) for p, r in pairs if low <= p < high or (k == 9 and p == 1.0)]
        if mine:
            mean_p = statistics.mean(p for p, _ in mine)
            observed = statistics.mean(float(r) for _, r in mine)
            rows.append(
                {
                    "bucket": [low, high],
                    "n": len(mine),
                    "predicted": round(mean_p, 3),
                    "observed": round(observed, 3),
                    "error": round(observed - mean_p, 3),
                }
            )
    return rows


def mean_error(rows: list[dict[str, Any]]) -> float:
    """The reliability curve's mean absolute error, weighted by goals (0 to 1)."""
    total = sum(r["n"] for r in rows)
    return sum(r["n"] * abs(r["error"]) for r in rows) / total if total else 0.0


def evaluate(cases: list[Case], scales: dict[str, dict[str, float]]) -> dict[str, Any]:
    by_h: dict[str, Any] = {}
    for b in BUCKETS:
        mine = [c for c in cases if c.bucket == b]
        by_h[str(b)] = {
            "n": len(mine),
            "coverage": coverage(mine, "model", scales),
            "coverage_raw": coverage(mine, "raw", scales),
            "coverage_naive": coverage(mine, "naive", scales),
            "by_metric": {
                m: coverage([c for c in mine if c.metric == m], "model", scales) for m in METRICS
            },
            "brier": brier(goals(mine, "model", scales)),
            "brier_naive": brier(goals(mine, "naive", scales)),
            "reliability": reliability(goals(mine, "model", scales)),
        }
    model, base = goals(cases, "model", scales), goals(cases, "naive", scales)
    return {
        "cases": len(cases),
        "goals": len(model),
        "by_horizon": by_h,
        "brier": brier(model),
        "brier_naive": brier(base),
        "reliability": reliability(model),
        "reliability_naive": reliability(base),
    }


def cross_validated(cases: list[Case]) -> dict[str, Any]:
    """Two folds by store: the calibration fitted on one half, scored on the other."""
    stores = sorted({c.scenario for c in cases})
    folds = [set(stores[0::2]), set(stores[1::2])]
    held: list[Case] = []
    pairs: list[tuple[float, bool]] = []
    inside: dict[str, list[bool]] = {str(b): [] for b in BUCKETS}
    for k in (0, 1):
        train = [c for c in cases if c.scenario not in folds[k]]
        test = [c for c in cases if c.scenario in folds[k]]
        scales = fit_scales(train)
        held += test
        pairs += goals(test, "model", scales)
        for c in test:
            low, _, high = c.interval(_s(scales, c))
            inside[str(c.bucket)].append(low <= c.truth <= high)
    return {
        "brier": brier(pairs),
        "coverage": {b: statistics.mean(v) if v else None for b, v in inside.items()},
        "reliability": reliability(pairs),
        "cases": len(held),
    }


def poor(cases: list[Case]) -> dict[str, list[int]]:
    """Metric and horizon buckets the cross-validation finds poorly calibrated: coverage out of
    75-85%, or a reliability curve more than 10 points off on average (weighted by goals; a
    single bucket of a cell is too few goals to judge)."""
    stores = sorted({c.scenario for c in cases})
    folds = [set(stores[0::2]), set(stores[1::2])]
    out: dict[str, list[int]] = {}
    for metric in METRICS:
        for b in BUCKETS:
            pairs: list[tuple[float, bool]] = []
            inside: list[bool] = []
            for k in (0, 1):
                scales = fit_scales([c for c in cases if c.scenario not in folds[k]])
                test = [
                    c
                    for c in cases
                    if c.scenario in folds[k] and c.metric == metric and c.bucket == b
                ]
                pairs += goals(test, "model", scales)
                for c in test:
                    low, _, high = c.interval(_s(scales, c))
                    inside.append(low <= c.truth <= high)
            if not inside:
                continue
            cov = statistics.mean(inside)
            off = mean_error(reliability(pairs)) > RELIABILITY_TOLERANCE
            if not COVERAGE_BAND[0] <= cov <= COVERAGE_BAND[1] or off:
                out.setdefault(metric, []).append(b)
    return out


# --- report -------------------------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.0%}"


def _num(x: float | None, digits: int = 4) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def checks(result: dict[str, Any]) -> list[str]:
    """The SPEC 17.6 targets, each met or missed."""
    lines = []
    for b, h in result["by_horizon"].items():
        cov = h["coverage"]
        ok = cov is not None and COVERAGE_BAND[0] <= cov <= COVERAGE_BAND[1]
        lines.append(
            f"- Coverage at {b} days: {_pct(cov)} (target 75-85%): {'met' if ok else 'missed'}."
        )
    judged = [r for r in result["reliability"] if r["n"] >= THIN]
    worst = max(judged, key=lambda r: abs(r["error"]), default=None)
    ok = worst is None or abs(worst["error"]) <= RELIABILITY_TOLERANCE
    lines.append(
        "- Reliability within 10 points in every bucket of at least "
        f"{THIN} goals: {'met' if ok else 'missed'}"
        + (
            f" (worst: {worst['bucket'][0]:.0%}-{worst['bucket'][1]:.0%}, "
            f"{worst['error'] * 100:+.1f} points)."
            if worst
            else "."
        )
    )
    better = result["brier"] < result["brier_naive"]
    lines.append(
        f"- Brier score {_num(result['brier'])} against {_num(result['brier_naive'])} for the "
        f"naive run rate: {'met' if better else 'missed'}."
    )
    return lines


def _reliability_table(rows: list[dict[str, Any]], naive_rows: list[dict[str, Any]]) -> list[str]:
    naive_by = {tuple(r["bucket"]): r for r in naive_rows}
    lines = [
        "| Predicted | Goals | Mean predicted | Observed | Error (points) | Naive goals | "
        "Naive observed |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        nv = naive_by.get(tuple(r["bucket"]))
        lines.append(
            f"| {r['bucket'][0]:.0%}-{r['bucket'][1]:.0%} | {r['n']} | {r['predicted']:.0%} | "
            f"{r['observed']:.0%} | {r['error'] * 100:+.1f} | {nv['n'] if nv else 0} | "
            f"{_pct(nv['observed']) if nv else '-'} |"
        )
    return lines


def _by_horizon_reliability(result: dict[str, Any]) -> list[str]:
    lines = []
    for b, h in result["by_horizon"].items():
        rows = h["reliability"]
        judged = [r for r in rows if r["n"] >= THIN]
        worst = max(judged, key=lambda r: abs(r["error"]), default=None)
        lines.append(
            f"| {b} days | {sum(r['n'] for r in rows)} | {mean_error(rows) * 100:.1f} | "
            + (
                f"{worst['bucket'][0]:.0%}-{worst['bucket'][1]:.0%}: "
                f"{worst['error'] * 100:+.1f} points |"
                if worst
                else "- |"
            )
        )
    return lines


def report(
    suite: str,
    run_id: str,
    result: dict[str, Any],
    settings: tuple[int, float | None],
    calibration: dict[str, Any],
    tuning: list[dict[str, Any]] | None = None,
) -> str:
    window, half_life = settings
    lines = [
        f"# Goal forecasts: backtest (`{suite}`)",
        "",
        f"Run `{run_id}`, generated by `uv run python -m bench.goals_backtest --suite {suite}`. "
        f"{len(result['stores'])} stores of 400 days; history cut at days "
        f"{', '.join(str(c) for c in CUTS)}; net profit, contribution margin and revenue forecast "
        "30, 60, 90 and 180 days ahead when the data goes that far "
        f"({result['cases']} forecasts), and {result['goals']} goals of varied ambition around "
        "each run rate. Forecast: least squares on the last "
        f"{window} days (level, trend, day of week), trend "
        + ("kept linear" if half_life is None else f"halving every {half_life:g} days ahead")
        + f", {fc.DRAWS} block-bootstrap paths; calibration `{calibration['version']}`.",
        "",
        "Targets (SPEC 17.6):",
        "",
        *checks(result),
        "",
        "## P10-P90 coverage per horizon",
        "",
        "| Horizon | Forecasts | Calibrated | Net profit | Contribution margin | Revenue | "
        "Uncalibrated | Naive run rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b, h in result["by_horizon"].items():
        m = h["by_metric"]
        lines.append(
            f"| {b} days | {h['n']} | {_pct(h['coverage'])} | {_pct(m['net_profit'])} | "
            f"{_pct(m['contribution_margin'])} | {_pct(m['revenue'])} | "
            f"{_pct(h['coverage_raw'])} | {_pct(h['coverage_naive'])} |"
        )
    lines += [
        "",
        "## Probability of reaching a goal",
        "",
        "| Horizon | Brier | Naive Brier | Skill (1 - Brier / naive) |",
        "| --- | --- | --- | --- |",
    ]
    for b, h in result["by_horizon"].items():
        skill = 1 - h["brier"] / h["brier_naive"] if h["brier"] and h["brier_naive"] else None
        lines.append(
            f"| {b} days | {_num(h['brier'])} | {_num(h['brier_naive'])} | {_num(skill, 3)} |"
        )
    total_skill = 1 - result["brier"] / result["brier_naive"]
    lines += [
        f"| All | {_num(result['brier'])} | {_num(result['brier_naive'])} | "
        f"{_num(total_skill, 3)} |",
        "",
        "Reliability: goals grouped by predicted probability, against the share reached "
        f"(buckets of fewer than {THIN} goals are shown, not judged):",
        "",
        *_reliability_table(result["reliability"], result["reliability_naive"]),
        "",
        "By horizon (the target above is on all goals; this shows where it holds):",
        "",
        "| Horizon | Goals | Mean error (points, weighted by goals) | Worst bucket |",
        "| --- | --- | --- | --- |",
        *_by_horizon_reliability(result),
        "",
        "## Calibration",
        "",
        "Factor applied to each horizon's deviations from the median path (above 1 widens), "
        "fitted on `goals_dev` by split conformal (rank ceil((n + 1) x 0.8)) and frozen in "
        "`backend/app/goals/calibration.json`:",
        "",
        "| Metric | 30 days | 60 days | 90 days | 180 days | Poorly calibrated (low evidence) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for metric in METRICS:
        sc = calibration.get("scales", {}).get(metric, {})
        poor_buckets = calibration.get("poor", {}).get(metric, [])
        lines.append(
            f"| {metric} | "
            + " | ".join(_num(sc.get(str(b)), 3) for b in BUCKETS)
            + f" | {', '.join(f'{b} days' for b in poor_buckets) or 'none'} |"
        )
    if tuning:
        lines += [
            "",
            "## Settings compared on goals_dev (two folds by store)",
            "",
            "Chosen: the lowest cross-validated Brier score among the settings whose "
            "cross-validated coverage is within 75-85% at every horizon.",
            "",
            "| Fit window | Trend ahead | CV Brier | CV coverage 30 / 60 / 90 / 180 days | "
            "CV worst reliability error (points) |",
            "| --- | --- | --- | --- | --- |",
        ]
        for t in tuning:
            cov = t["coverage"]
            judged = [r for r in t["reliability"] if r["n"] >= THIN]
            worst = max((abs(r["error"]) for r in judged), default=0.0)
            lines.append(
                f"| {t['window']} days | "
                + ("linear" if t["half_life"] is None else f"half-life {t['half_life']:g} days")
                + f" | {_num(t['brier'])} | "
                + " / ".join(_pct(cov[str(b)]) for b in BUCKETS)
                + f" | {worst * 100:.1f} |"
            )
    return "\n".join(lines) + "\n"


# --- main ---------------------------------------------------------------------------------------


def tune(values: dict[str, tuple[date, dict[str, FloatArray]]]) -> list[dict[str, Any]]:
    rows = []
    for window, half_life in SETTINGS:
        cv = cross_validated(all_cases(values, window, half_life))
        rows.append({"window": window, "half_life": half_life, **cv})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest the goal forecasts")
    parser.add_argument("--suite", choices=["goals_dev", "goals_test"], required=True)
    parser.add_argument("--tune", action="store_true", help="compare settings (goals_dev only)")
    parser.add_argument("--fit", action="store_true", help="fit and freeze the calibration")
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    parser.add_argument("--frozen", type=Path, default=fc.FROZEN)
    parser.add_argument("--database", default="profit_goals_backtest")
    args = parser.parse_args(argv)
    if (args.tune or args.fit) and args.suite != "goals_dev":
        parser.error("tuning and calibration use goals_dev only")
    configure_logging("WARNING")
    started = datetime.now(UTC).replace(microsecond=0)
    run_id = f"goals-backtest-{args.suite}-{started:%Y%m%dT%H%M%SZ}"
    values = load_values(args.suite, args.database)
    tuning = tune(values) if args.tune else None
    settings = (fc.FIT_DAYS, fc.TREND_HALF_LIFE)
    cases = all_cases(values, *settings)
    if args.fit:
        calibration = {
            "version": VERSION,
            "target": TARGET,
            "fitted_on": run_id,
            "settings": {"window": settings[0], "half_life": settings[1]},
            "scales": fit_scales(cases),
            "poor": poor(cases),
        }
        args.frozen.write_text(
            json.dumps(calibration, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        fc.frozen.cache_clear()
    calibration = json.loads(args.frozen.read_text(encoding="utf-8"))
    result = evaluate(cases, calibration.get("scales", {}))
    result["stores"] = sorted({c.scenario for c in cases})
    name = "goals-backtest.md" if args.suite == "goals_test" else "goals-backtest-dev.md"
    text = report(args.suite, run_id, result, settings, calibration, tuning)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / name).write_text(text, encoding="utf-8", newline="\n")
    saved = {"run_id": run_id, "settings": settings, "result": result, "tuning": tuning}
    (args.out / f"{run_id}.json").write_text(
        json.dumps(saved, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
