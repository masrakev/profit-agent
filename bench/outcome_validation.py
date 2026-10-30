"""Validate outcome measurement against the truth (Task 5 B5, ADR 0018).

    uv run python -m bench.outcome_validation     # writes bench/reports/outcome-validation.md

For dev scenarios, a real action (a pause, a budget cut or a raise on the store's largest
campaign) is approved and executed on the simulator 14 days before the data end, the store
lives 7 more days, and the outcome is measured by synthetic control as in production. The
same store without the action is generated in a second database: the true effect over the
window is the difference of the campaign's contribution after ads between the two.

Reported: the abstention rate, the coverage of the measured P10-P90 (target 80%), bias and
error of the measured P50; and, to test the weak-fit threshold (relative error 0.5, chosen in
Task 4), the same estimate made without the threshold, by band of pre-period relative error.
"""

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import Engine, text

from app.agent.contracts import ActionFamily
from app.causal import control
from app.causal.control import synthetic_control
from app.causal.outcome import PRE_DAYS, WINDOW_DAYS, campaign_series, donor_matrix, measure
from app.db import make_engine, tenant_transaction
from app.decisions.options import Option, OptionKind, OptionSet, Reversibility
from app.decisions.store import Channel, Verdict, decide, propose
from app.detection.series import load_series
from app.domain.hashing import canonical_json, sha256_hex
from app.executor.simulator import SimulatorAdapter
from app.executor.worker import Executor
from app.facts.engine import FactEngine
from app.observability import configure_logging
from app.twin import Action, ActionKind, fit_twin
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR
from bench.scenarios.manifest import ScenarioManifest, load_suite
from bench.simulator import advance, register

TREATED_DB = "profit_outcomes_treated"
CONTROL_DB = "profit_outcomes_control"
DAYS_BEFORE_END = 14
BANDS = ((0.0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, float("inf")))
ACTIONS = (("pause", None), ("budget -30%", "-0.3"), ("budget +20%", "0.2"))


@dataclass(frozen=True)
class Case:
    scenario: str
    action: str
    status: str
    reason: str
    relative_error: float | None
    measured: tuple[float, float, float] | None  # as reported (None when abstained)
    unthresholded: tuple[float, float, float] | None  # the estimate without the fit threshold
    truth: float


def _largest_campaign(engine: Engine, store: UUID) -> UUID:
    with tenant_transaction(engine, store) as conn:
        found: UUID = conn.execute(
            text(
                "SELECT campaign_id FROM ad_metrics_daily WHERE store_id = :s GROUP BY "
                "campaign_id ORDER BY sum(spend) DESC, campaign_id LIMIT 1"
            ),
            {"s": store},
        ).scalar_one()
    return found


def _options(campaign: UUID, change: str | None) -> OptionSet:
    action = (
        Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=campaign)
        if change is None
        else Action(kind=ActionKind.CHANGE_BUDGET, entity=campaign, change=Decimal(change))
    )
    kind = (
        OptionKind.PAUSE_CAMPAIGN
        if change is None
        else OptionKind.REDUCE_BUDGET
        if Decimal(change) < 0
        else OptionKind.INCREASE_BUDGET
    )
    family = (
        ActionFamily.INCREASE_BUDGET_CAPPED
        if kind is OptionKind.INCREASE_BUDGET
        else ActionFamily.PAUSE_OR_REDUCE_CAMPAIGN
    )
    option = Option(
        f"validation:{kind.value}:{campaign}",
        kind,
        family,
        f"campaign:{campaign}",
        (action,),
        Reversibility.REVERSIBLE,
        (),
        (),
    )
    return OptionSet(
        cause="validation",
        entity=f"campaign:{campaign}",
        options=(option,),
        recommended=option.option_id,
        reason="outcome validation",
        floor=Decimal(100),
    )


def _window_sum(engine: Engine, store: UUID, campaign: UUID, start: date) -> float:
    with tenant_transaction(engine, store) as conn:
        series = load_series(conn, store)
    values = campaign_series(series, campaign)
    first = series.index(start)
    return float(values[first : first + WINDOW_DAYS].sum())


def _unthresholded(
    engine: Engine, store: UUID, action_id: UUID
) -> tuple[float, float, float] | None:
    """The estimate `measure` would report if the weak-fit threshold did not apply."""
    with tenant_transaction(engine, store) as conn:
        row = conn.execute(
            text("SELECT campaign_id, after_state FROM actions WHERE action_id = :a"),
            {"a": action_id},
        ).one()
        series = load_series(conn, store)
    effective = date.fromisoformat(str(row.after_state["effective_date"]))
    split = series.index(effective)
    first = max(0, split - PRE_DAYS)
    target = campaign_series(series, row.campaign_id)[first:]
    donors, _ = donor_matrix(series, row.campaign_id)
    rng = np.random.default_rng(int(sha256_hex(canonical_json([str(action_id), None]))[:16], 16))
    saved = control.MAX_RELATIVE_ERROR
    control.MAX_RELATIVE_ERROR = float("inf")
    try:
        result = synthetic_control(target, donors[first:], split - first, WINDOW_DAYS, rng)
    finally:
        control.MAX_RELATIVE_ERROR = saved
    return result.effect


def run_case(
    treated: Engine, untreated: Engine, manifest: ScenarioManifest, label: str, change: str | None
) -> Case:
    today = manifest.config.days - DAYS_BEFORE_END
    store = register(treated, manifest, today)
    register(untreated, manifest, today + WINDOW_DAYS)
    campaign = _largest_campaign(treated, store)
    with tenant_transaction(treated, store) as conn:
        model = fit_twin(conn, store)
        d = propose(
            conn, FactEngine(conn, store), model, _options(campaign, change), source="owner"
        )
        decide(
            conn,
            store,
            d.decision_id,
            d.recommended_option_id,
            Verdict.APPROVED,
            channel=Channel.API,
            actor="owner:validation",
        )
    Executor(treated, {"simulator": SimulatorAdapter(treated)}).run_once()
    advance(treated, store, WINDOW_DAYS)
    with tenant_transaction(treated, store) as conn:
        action_id: UUID = conn.execute(
            text(
                "SELECT action_id FROM actions WHERE store_id = :s AND decision_id = :d "
                "AND status = 'executed'"
            ),
            {"s": store, "d": d.decision_id},
        ).scalar_one()
        effective = date.fromisoformat(
            str(
                conn.execute(
                    text("SELECT after_state->>'effective_date' FROM actions WHERE action_id = :a"),
                    {"a": action_id},
                ).scalar_one()
            )
        )
        outcome = measure(conn, store, action_id)
    truth = _window_sum(treated, store, campaign, effective) - _window_sum(
        untreated, store, campaign, effective
    )
    effect = outcome.get("effect")
    measured = (
        (float(effect["p10"]), float(effect["p50"]), float(effect["p90"])) if effect else None
    )
    relative = outcome.get("relative_error")
    return Case(
        scenario=manifest.scenario_id,
        action=label,
        status=outcome["status"],
        reason=outcome["reason"],
        relative_error=float(relative) if relative is not None else None,
        measured=measured,
        unthresholded=measured or _unthresholded(treated, store, action_id),
        truth=round(truth, 2),
    )


def _stats(pairs: list[tuple[tuple[float, float, float], float]]) -> dict[str, Any]:
    if not pairs:
        return {"n": 0}
    inside = sum(p10 <= t <= p90 for (p10, _, p90), t in pairs)
    errors = [p50 - t for (_, p50, _), t in pairs]
    return {
        "n": len(pairs),
        "coverage": round(inside / len(pairs), 3),
        "bias": round(statistics.mean(errors), 2),
        "mae": round(statistics.mean(abs(e) for e in errors), 2),
        "median_abs_error": round(statistics.median(abs(e) for e in errors), 2),
    }


def summarize(cases: list[Case]) -> dict[str, Any]:
    measured = [(c.measured, c.truth) for c in cases if c.measured is not None]
    reasons: dict[str, int] = {}
    for c in cases:
        if c.status != "measured":
            reasons[c.reason] = reasons.get(c.reason, 0) + 1
    bands = []
    for low, high in BANDS:
        mine = [
            (c.unthresholded, c.truth)
            for c in cases
            if c.unthresholded is not None
            and c.relative_error is not None
            and low <= c.relative_error < high
        ]
        bands.append({"band": [low, high], **_stats(mine)})
    by_action = {
        label: _stats([(c.measured, c.truth) for c in cases if c.action == label and c.measured])
        for label, _ in ACTIONS
    }
    return {
        "cases": len(cases),
        "measured": len(measured),
        "abstention_rate": round(1 - len(measured) / len(cases), 3) if cases else None,
        "abstained_because": reasons,
        "measured_intervals": _stats(measured),
        "by_action": by_action,
        "unthresholded_by_relative_error": bands,
    }


def _band(low: float, high: float) -> str:
    return f"{low} to {high}" if high != float("inf") else f"{low} and more"


def verdict(summary: dict[str, Any], cases: list[Case]) -> list[str]:
    """What the runs say about the intervals and about the 0.5 weak-fit threshold."""
    m = summary["measured_intervals"]
    lines = []
    if m["n"]:
        actions = [(s["coverage"], a) for a, s in summary["by_action"].items() if s["n"]]
        worst = min(actions)
        lines.append(
            f"Intervals: the measured P10-P90 holds the truth {m['coverage']:.0%} of the time "
            f"against the 80% target"
            + (
                f"; they are too narrow, most for {worst[1]} ({worst[0]:.0%})."
                if m["coverage"] < 0.8
                else "."
            )
        )
    threshold = control.MAX_RELATIVE_ERROR
    kept = [
        (c.unthresholded, c.truth)
        for c in cases
        if c.unthresholded and c.relative_error is not None and c.relative_error < threshold
    ]
    withheld = [
        (c.unthresholded, c.truth)
        for c in cases
        if c.unthresholded and c.relative_error is not None and c.relative_error >= threshold
    ]
    below, above = _stats(kept), _stats(withheld)
    if not above["n"]:
        lines.append(
            f"Threshold {threshold}: no estimate crossed it; these runs neither validate nor "
            "refute it."
        )
        return lines
    compared = (
        f"the {above['n']} estimates it withheld hold the truth {above['coverage']:.0%} of "
        f"the time (mean abs error {above['mae']}), the {below['n']} it lets through "
        f"{below['coverage']:.0%} ({below['mae']})"
    )
    if above["coverage"] >= below["coverage"] and above["mae"] <= below["mae"]:
        lines.append(
            f"Threshold {threshold}: refuted on these runs. {compared[0].upper()}{compared[1:]}: "
            "a weak pre-period fit does not predict a wrong estimate, and the misses are "
            f"among the estimates it reports. With {above['n']} estimates above it, the "
            "evidence is thin."
        )
    else:
        lines.append(
            f"Threshold {threshold}: supported on these runs. {compared[0].upper()}{compared[1:]}."
        )
    return lines


def load_cases(path: Path) -> tuple[str, list[Case]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for c in data["cases"]:
        for key in ("measured", "unthresholded"):
            c[key] = tuple(c[key]) if c[key] is not None else None
        cases.append(Case(**c))
    return str(data["run_id"]), cases


def markdown(run_id: str, summary: dict[str, Any], cases: list[Case]) -> str:
    m = summary["measured_intervals"]
    lines = [
        "# Outcome validation",
        "",
        f"Run `{run_id}`: {summary['cases']} actions on dev scenarios (a pause, a budget cut of "
        "30% or a raise of 20% on the store's largest campaign, executed on the simulator 14 "
        "days before the data end), measured after 7 days by synthetic control, against the "
        "true effect: the same store without the action.",
        "",
        "| Measured | Abstained | P10-P90 coverage (target 80%) | Bias of P50 | Mean abs error |"
        " Median abs error |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {summary['measured']} | {summary['cases'] - summary['measured']} "
        f"({summary['abstention_rate']:.0%}) | {m.get('coverage', 0):.0%} | {m.get('bias')} | "
        f"{m.get('mae')} | {m.get('median_abs_error')} |",
        "",
        *[f"{line}\n" for line in verdict(summary, cases)],
        "Abstentions: "
        + (", ".join(f"{r} ({n})" for r, n in summary["abstained_because"].items()) or "none")
        + ".",
        "",
        "By action (measured only):",
        "",
        "| Action | n | Coverage | Bias | Mean abs error |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, s in summary["by_action"].items():
        if s["n"]:
            lines.append(f"| {label} | {s['n']} | {s['coverage']:.0%} | {s['bias']} | {s['mae']} |")
    lines += [
        "",
        "The weak-fit threshold: every estimate, including those the threshold withheld, by "
        "the pre-period's relative error (daily RMSE over the mean absolute level). The "
        "threshold is 0.5: estimates above it are not reported.",
        "",
        "| Relative error | n | Coverage | Bias | Mean abs error |",
        "| --- | --- | --- | --- | --- |",
    ]
    for b in summary["unthresholded_by_relative_error"]:
        if b["n"]:
            lines.append(
                f"| {_band(*b['band'])} | {b['n']} | {b['coverage']:.0%} | {b['bias']} | "
                f"{b['mae']} |"
            )
    lines += [
        "",
        "| Scenario | Action | Status | Relative error | Measured P10 / P50 / P90 | Truth |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in cases:
        est = " / ".join(f"{x:.0f}" for x in c.measured) if c.measured else c.reason
        rel = f"{c.relative_error:.2f}" if c.relative_error is not None else "-"
        lines.append(f"| {c.scenario} | {c.action} | {c.status} | {rel} | {est} | {c.truth:.0f} |")
    return "\n".join(lines) + "\n"


def run(
    every: int, out: Path, databases: tuple[str, str] = (TREATED_DB, CONTROL_DB)
) -> tuple[str, list[Case]]:
    started = datetime.now(UTC).replace(microsecond=0)
    run_id = f"outcome-validation-{started:%Y%m%dT%H%M%SZ}"
    treated = make_engine(prepare_database(databases[0]))
    untreated = make_engine(prepare_database(databases[1]))
    cases = []
    for i, manifest in enumerate(load_suite("dev")[::every]):
        label, change = ACTIONS[i % len(ACTIONS)]
        try:
            cases.append(run_case(treated, untreated, manifest, label, change))
        except Exception as exc:  # a scenario that cannot be acted on is reported, not fatal
            sys.stderr.write(f"{manifest.scenario_id}: {type(exc).__name__}: {exc}\n")
    treated.dispose()
    untreated.dispose()
    out.mkdir(parents=True, exist_ok=True)
    stamp = run_id.removeprefix("outcome-validation-")
    (out / f"outcome-validation-{stamp}.json").write_text(
        json.dumps(
            {"run_id": run_id, "summary": summarize(cases), "cases": [c.__dict__ for c in cases]},
            indent=2,
            default=list,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return run_id, cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate outcome measurement on dev scenarios")
    parser.add_argument("--every", type=int, default=3, help="every Nth dev scenario")
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    parser.add_argument("--from", dest="saved", type=Path, help="rewrite the report of a run")
    args = parser.parse_args(argv)
    configure_logging("WARNING")
    run_id, cases = load_cases(args.saved) if args.saved else run(args.every, args.out)
    report = markdown(run_id, summarize(cases), cases)
    (args.out / "outcome-validation.md").write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
