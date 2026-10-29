"""Calibrate the twin's P10-P90 intervals on `dev` scenarios (ADR 0014).

    uv run python -m bench.twin.calibrate            # writes calibration.toml and the report
    uv run python -m bench.twin.calibrate --check    # coverage of the frozen calibration only

For every dev scenario the twin is fitted on the data before day T (the last `HORIZON` days are
held back) and predicts those days, then the prediction is compared with what the generator
produced. Four variants per scenario: "do nothing" (the plain store), and the same store with the
generator really applying an action from day T to its largest campaign: budget -30%, +20%, pause.

Split conformal: scenarios with an even index calibrate, odd ones evaluate. Per metric and per
kind ("do nothing" or action) the factor `q` is the conformal quantile of
`max(P10 - y, y - P90) / half-width`, so that the widened intervals cover 80% of outcomes. The
coverage reported is the one on the evaluation half, which the factors never saw.
"""

import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from app.db import make_engine, tenant_transaction
from app.detection.series import StoreSeries, load_series
from app.observability import configure_logging
from app.twin import Action, ActionKind, Scenario, fit_twin, simulate
from app.twin.calibration import CALIBRATION_FILE, Calibration, load_calibration
from app.twin.model import METRICS
from bench.generator import Intervention
from bench.generator.load import load
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR
from bench.scenarios.manifest import ScenarioManifest, load_suite

HORIZON = 14
TARGET = 0.8
TWIN_DB = "profit_twin"  # one database per variant: the variants are the same store
VARIANTS: tuple[tuple[str, float | None], ...] = (
    ("do_nothing", None),
    ("budget_-30%", 0.7),
    ("budget_+20%", 1.2),
    ("pause", 0.0),
)


@lru_cache(maxsize=len(VARIANTS))
def _engine(url: str) -> Engine:
    return make_engine(url)


def actuals(series: StoreSeries, first: int, end: int) -> dict[str, float]:
    """What the store really did over days [first, end), with the facts' definitions."""
    cm = units = 0.0
    for p in series.products.values():
        for t in range(first, end):
            cm += float(p.revenue[t] - p.cogs[t] - p.fees[t] - p.refunds[t])
            units += float(p.units[t])
    spend = sum(float(c.spend[t]) for c in series.campaigns.values() for t in range(first, end))
    fixed = sum(float(series.fixed_costs[t]) for t in range(first, end))
    return {
        "contribution_margin": cm,
        "net_profit": cm - spend - fixed,
        "units": units,
        "ad_spend": spend,
    }


def _largest_campaign(manifest: ScenarioManifest, day: int) -> int | None:
    data = manifest.generate()
    started = [
        (float(c.daily_budget), i)
        for i, (c, truth) in enumerate(zip(data.campaigns, data.campaign_truth, strict=True))
        if truth.start_day <= day - 28
    ]
    return max(started)[1] if started else None


def run_scenario(job: tuple[ScenarioManifest, tuple[str, ...]]) -> list[dict[str, Any]]:
    manifest, urls = job
    day = manifest.config.days - HORIZON
    campaign = _largest_campaign(manifest, day)
    records: list[dict[str, Any]] = []
    for (name, multiplier), url in zip(VARIANTS, urls, strict=True):
        engine = _engine(url)
        if multiplier is not None and campaign is None:
            continue
        interventions = [] if multiplier is None else [Intervention(day, campaign or 0, multiplier)]
        data = manifest.generate(interventions=interventions)
        store = data.store.store_id
        load(engine, data, manifest.config)
        with tenant_transaction(engine, store) as conn:
            series = load_series(conn, store)
            as_of = series.day(day)
            model = fit_twin(conn, store, as_of=as_of, series=series)
        actions: tuple[Action, ...] = ()
        if multiplier is not None:
            cid = data.campaigns[campaign or 0].id
            kind = ActionKind.PAUSE_CAMPAIGN if multiplier == 0 else ActionKind.CHANGE_BUDGET
            change = Decimal(str(round(multiplier - 1, 4)))
            actions = (Action(kind=kind, entity=cid, change=change if multiplier else Decimal(0)),)
        sim = simulate(
            model,
            Scenario(actions=actions, horizon_days=HORIZON),
            calibration=Calibration.identity(),
        )
        truth = actuals(series, day, day + HORIZON)
        for metric in METRICS:
            r = sim.totals.get(metric)
            if r is None:
                continue
            records.append(
                {
                    "scenario": manifest.scenario_id,
                    "variant": name,
                    "kind": "do_nothing" if multiplier is None else "action",
                    "metric": metric,
                    "p10": r.p10,
                    "p50": r.p50,
                    "p90": r.p90,
                    "actual": truth[metric],
                    "low_evidence": list(sim.low_evidence),
                }
            )
    return records


def score(r: dict[str, Any]) -> float:
    half = (r["p90"] - r["p10"]) / 2
    excess = max(r["p10"] - r["actual"], r["actual"] - r["p90"])
    if half <= 0:
        return 0.0 if excess <= 0 else math.inf
    return float(excess / half)


def conformal_factor(scores: list[float], target: float = TARGET) -> float:
    """Smallest q such that at least `target` of the calibration scores are <= q (finite-sample
    corrected)."""
    ordered = sorted(scores)
    k = min(len(ordered), math.ceil((len(ordered) + 1) * target)) - 1
    return ordered[max(k, 0)]


def covered(r: dict[str, Any], q: float) -> bool:
    half = (r["p90"] - r["p10"]) / 2
    return bool(r["p10"] - q * half <= r["actual"] <= r["p90"] + q * half)


def summarize(records: list[dict[str, Any]], cal: Calibration) -> dict[str, Any]:
    scenarios = sorted({r["scenario"] for r in records})
    evaluation = {s for i, s in enumerate(scenarios) if i % 2 == 1}
    out: dict[str, Any] = {"by_metric": {}, "by_variant": {}}
    for kind in ("do_nothing", "action"):
        for metric in METRICS:
            group = [r for r in records if r["kind"] == kind and r["metric"] == metric]
            held = [r for r in group if r["scenario"] in evaluation]
            q = cal.factor(metric, action=kind == "action")
            out["by_metric"][f"{kind}:{metric}"] = {
                "n_evaluation": len(held),
                "raw_coverage": _rate([covered(r, 0.0) for r in held]),
                "calibrated_coverage": _rate([covered(r, q) for r in held]),
                "factor": q,
            }
    for name, _ in VARIANTS:
        held = [r for r in records if r["variant"] == name and r["scenario"] in evaluation]
        out["by_variant"][name] = {
            "n_evaluation": len(held),
            "raw_coverage": _rate([covered(r, 0.0) for r in held]),
            "calibrated_coverage": _rate(
                [covered(r, cal.factor(r["metric"], action=r["kind"] == "action")) for r in held]
            ),
        }
    held = [r for r in records if r["scenario"] in evaluation]
    out["overall"] = {
        "n_evaluation": len(held),
        "raw_coverage": _rate([covered(r, 0.0) for r in held]),
        "calibrated_coverage": _rate(
            [covered(r, cal.factor(r["metric"], action=r["kind"] == "action")) for r in held]
        ),
        "scenarios": len(scenarios),
        "evaluation_scenarios": len(evaluation),
    }
    return out


def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def fit_calibration(records: list[dict[str, Any]], version: int) -> Calibration:
    scenarios = sorted({r["scenario"] for r in records})
    calibration_set = {s for i, s in enumerate(scenarios) if i % 2 == 0}
    factors: dict[str, dict[str, float]] = {"do_nothing": {}, "action": {}}
    for kind in factors:
        for metric in METRICS:
            scores = [
                score(r)
                for r in records
                if r["kind"] == kind and r["metric"] == metric and r["scenario"] in calibration_set
            ]
            factors[kind][metric] = round(conformal_factor(scores), 4) if scores else 0.0
    return Calibration(
        version=version,
        method="split_conformal_v1",
        do_nothing=factors["do_nothing"],
        action=factors["action"],
    )


def write_calibration(cal: Calibration, summary: dict[str, Any], started: datetime) -> None:
    o = summary["overall"]
    lines = [
        "# Twin interval calibration (ADR 0014). Written by `python -m bench.twin.calibrate` on",
        "# dev scenarios, then frozen: any change bumps `version` (part of every simulated fact).",
        f"# Run {started.isoformat()}: {o['scenarios']} dev scenarios, horizon {HORIZON} days;",
        f"# P10-P90 coverage on the {o['evaluation_scenarios']} held-out scenarios: raw "
        f"{o['raw_coverage']}, calibrated {o['calibrated_coverage']} (target {TARGET}).",
        f"version = {cal.version}",
        f'method = "{cal.method}"',
        "",
        "[do_nothing]",
        *(f"{m} = {cal.do_nothing[m]}" for m in METRICS),
        "",
        "[action]",
        *(f"{m} = {cal.action[m]}" for m in METRICS),
        "",
    ]
    CALIBRATION_FILE.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def markdown(summary: dict[str, Any], cal: Calibration, started: datetime) -> str:
    o = summary["overall"]
    lines = [
        "# Twin calibration (`dev`)",
        "",
        f"Run {started.isoformat()} - calibration v{cal.version} ({cal.method}) - horizon "
        f"{HORIZON} days - {o['scenarios']} scenarios, {o['evaluation_scenarios']} held out for "
        "evaluation (odd index), the others calibrate.",
        "",
        "P10-P90 coverage on the held-out scenarios (target 75-85%):",
        "",
        "| | Intervals | Raw coverage | Calibrated coverage |",
        "| --- | --- | --- | --- |",
        f"| All | {o['n_evaluation']} | {_pct(o['raw_coverage'])} | "
        f"{_pct(o['calibrated_coverage'])} |",
        *(
            f"| {name} | {v['n_evaluation']} | {_pct(v['raw_coverage'])} | "
            f"{_pct(v['calibrated_coverage'])} |"
            for name, v in summary["by_variant"].items()
        ),
        "",
        "| Kind : metric | Intervals | Raw coverage | Factor | Calibrated coverage |",
        "| --- | --- | --- | --- | --- |",
        *(
            f"| {key} | {v['n_evaluation']} | {_pct(v['raw_coverage'])} | {v['factor']} | "
            f"{_pct(v['calibrated_coverage'])} |"
            for key, v in summary["by_metric"].items()
        ),
        "",
        "An interval [P10, P90] of half-width w becomes [P10 - q w, P90 + q w]. Price changes are",
        "not calibrated: the generator's demand does not respond to price, so price answers rest",
        "on the documented elasticity prior and carry `low_evidence`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate the twin on dev scenarios")
    parser.add_argument("--check", action="store_true", help="coverage of the frozen calibration")
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--only", type=int, help="first N scenarios (smoke runs)")
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    configure_logging("WARNING")
    manifests = load_suite("dev")[: args.only]
    started = datetime.now(UTC).replace(microsecond=0)
    urls = tuple(prepare_database(f"{TWIN_DB}_{i}") for i in range(len(VARIANTS)))
    jobs = [(m, urls) for m in manifests]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        records = [r for batch in pool.map(run_scenario, jobs) for r in batch]
    if args.check:
        cal = load_calibration()
    else:
        cal = fit_calibration(records, version=load_calibration().version + 1)
    summary = summarize(records, cal)
    stamp = f"{started:%Y%m%dT%H%M%SZ}"
    if not args.check and args.only is None:
        write_calibration(cal, summary, started)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"twin-calibration-{stamp}.json").write_text(
            json.dumps({"summary": summary, "records": records}, indent=1) + "\n",
            encoding="utf-8",
        )
        (args.out / "twin-calibration.md").write_text(
            markdown(summary, cal, started), encoding="utf-8", newline="\n"
        )
    sys.stdout.write(markdown(summary, cal, started))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
