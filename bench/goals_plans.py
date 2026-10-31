"""Validate goal plans against what happens when they are followed (Task 6 B3, ADR 0024).

    uv run python -m bench.goals_plans --suite goals_dev    # bench/reports/goals-plans-dev.md
    uv run python -m bench.goals_plans --suite goals_test   # once: bench/reports/goals-plans.md
    uv run python -m bench.goals_plans --suite goals_test --resume   # finish an interrupted run

Each store's goals are saved as soon as they are done (data/goals/plans-<suite>.jsonl): a run
that stops can be finished with `--resume`, which skips the stores already done.

Each store of the suite is generated and loaded. At each cut, a goal is set on each metric for
the next 60 days, at the 70th percentile of the forecast from the cut: a goal the store reaches
about three times in ten on its own, where a plan matters (on average over the cuts: at one
time of year the forecast errs one way, see CUTS). The target comes from what the owner knows at
the cut, never from the outcome. Its plan is built as in production
(`app.goals.service.compute_plan`).

The plan is then followed: its budget and pause steps are executed in the simulator from their
due day, by generating the same store again with them as interventions (identical until the
first step), loaded in a database of its own. Reorder steps are not executed (the simulator's
restock only ends a stockout fault) and experiments are never counted. Compared, for each goal:
whether it was reached without the plan (the store as generated) and with it, against the
predicted probabilities; whether the cumulative metric with the plan fell inside each weekly
milestone's P10-P90 band; whether the outcome with the plan fell inside its predicted P10-P90;
and the plan's effect on net profit against its predicted range.

The uplift (success rate with the plan minus without) is reported with a 90% bootstrap interval
over stores (SPEC 17.6).
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import create_engine, text

from app.config import get_settings, repo_path
from app.db import make_engine, tenant_transaction
from app.detection.series import StoreSeries, load_series
from app.goals.forecast import FloatArray, daily_values, forecast
from app.goals.plan import Plan
from app.goals.service import compute_plan
from app.observability import configure_logging
from app.twin import ActionKind
from bench.generator import GeneratedStore, Intervention
from bench.generator.load import load
from bench.runner.__main__ import _with_db, prepare_database
from bench.runner.report import REPORT_DIR
from bench.scenarios.manifest import ScenarioManifest, Suite, load_suite

# Days of history when the goal is set, spread over the yearly cycle: the suites' stores share
# one yearly peak and the forecast has no yearly term, so at a single time of year its errors
# go one way (cuts at days 250 and 310 alone, both after the trough: goals at the forecast's
# 70th percentile were reached 60% of the time, not 30%: the first goals_dev run,
# bench/reports/goals-plans-goals_dev-20261031T171012Z.json).
CUTS = (150, 230, 310)
HORIZON = 60
METRICS = ("net_profit", "revenue")
TARGET_PERCENTILE = 70  # of the forecast at the deadline: reached about 3 times in 10 alone
BAND = (0.70, 0.90)  # milestone bands are P10-P90: about 80% of weeks inside
RESAMPLES = 2000
DATABASE = "profit_goals_plans"
CACHE = repo_path("data/goals")


@dataclass
class Row:
    scenario: str
    cut: int
    metric: str
    target: float
    steps: list[str]
    executed: int  # actions run in the simulator
    skipped: int  # reorder actions, not executed
    p_without: float
    p_with: float
    reached_without: bool
    reached_with: bool
    outcome: tuple[float, float, float]
    actual_with: float
    actual_without: float
    profit_change: tuple[float, float, float]
    actual_profit_change: float
    milestones: list[tuple[int, float, float, float]]  # day, P10, P90, actual with the plan


def _saved(suite: str) -> Path:
    return CACHE / f"plans-{suite}.jsonl"


def _load_saved(path: Path) -> list[Row]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Row(**json.loads(line)) for line in lines if line.strip()]


def _database(name: str) -> str:
    """A fresh bench database whose tables autovacuum leaves alone. Every store's load ends by
    analyzing all the domain tables in one transaction; two workers doing so on one database
    queue behind each other, and an autovacuum caught in that queue did not yield: the run
    waited for good (twice, on the first runs)."""
    url = prepare_database(name)
    owner = create_engine(_with_db(get_settings().database_url, name))
    with owner.begin() as conn:
        tables = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
        for table in list(tables):
            conn.execute(text(f'ALTER TABLE public."{table}" SET (autovacuum_enabled = false)'))
    owner.dispose()
    return url


def _db(prefix: str, metric: str, cut: int) -> str:
    return f"{prefix}_{metric}_{cut}"


def follow(plan: Plan, plain: GeneratedStore, cut: int) -> tuple[list[Intervention], int, int]:
    """The plan's budget and pause steps as generator interventions from their day."""
    index = {c.id: i for i, c in enumerate(plain.campaigns)}
    out: list[Intervention] = []
    skipped = 0
    for step, _ in plan.steps:
        for action in step.actions:
            if action.kind not in (ActionKind.CHANGE_BUDGET, ActionKind.PAUSE_CAMPAIGN):
                skipped += 1
                continue
            assert action.entity is not None
            campaign = index[action.entity]
            start = cut + step.day + action.start
            multiplier = (
                0.0 if action.kind is ActionKind.PAUSE_CAMPAIGN else 1 + float(action.change)
            )
            out.append(Intervention(day=start, campaign=campaign, budget_multiplier=multiplier))
            if action.days is not None:
                out.append(Intervention(start + action.days, campaign, 1.0))
    return out, len(out), skipped


def _values(series: StoreSeries, metric: str) -> FloatArray:
    return np.array([float(v) for v in daily_values(series, metric)], dtype=np.float64)


def store_rows(
    manifest: ScenarioManifest, url_plain: str, urls_with: dict[tuple[str, int], str]
) -> list[Row]:
    """Every goal of one store (run in a worker process)."""
    configure_logging("WARNING")
    plain_engine = make_engine(url_plain)
    plain = manifest.generate()
    load(plain_engine, plain, manifest.config)
    store = plain.store.store_id
    with tenant_transaction(plain_engine, store) as conn:
        series = load_series(conn, store)
    without = {m: _values(series, m) for m in {*METRICS, "net_profit"}}
    rows = []
    for cut in CUTS:
        as_of = series.day(cut)
        for metric in METRICS:
            seed = cut * 1009 + METRICS.index(metric)
            history = without[metric][:cut]
            paths = forecast(history, series.start, metric, HORIZON, seed).paths
            target = float(np.percentile(paths[:, -1], TARGET_PERCENTILE))
            with tenant_transaction(plain_engine, store) as conn:
                plan, _ = compute_plan(conn, store, metric, target, as_of, HORIZON, seed)
            interventions, executed, skipped = follow(plan, plain, cut)
            followed = manifest.generate(interventions)
            engine = make_engine(urls_with[(metric, cut)])
            load(engine, followed, manifest.config)
            with tenant_transaction(engine, store) as conn:
                after = load_series(conn, store)
            engine.dispose()
            with_plan = _values(after, metric)
            profit_with = _values(after, "net_profit")
            window = slice(cut, cut + HORIZON)
            detailed = slice(cut, cut + plan.days)
            rows.append(
                Row(
                    scenario=manifest.scenario_id,
                    cut=cut,
                    metric=metric,
                    target=target,
                    steps=[s.lever for s, _ in plan.steps],
                    executed=executed,
                    skipped=skipped,
                    p_without=plan.probability_without[1],
                    p_with=plan.probability_with[1],
                    reached_without=bool(without[metric][window].sum() >= target),
                    reached_with=bool(with_plan[window].sum() >= target),
                    outcome=plan.outcome,
                    actual_with=float(with_plan[window].sum()),
                    actual_without=float(without[metric][window].sum()),
                    profit_change=plan.profit_change,
                    actual_profit_change=float(
                        profit_with[detailed].sum() - without["net_profit"][detailed].sum()
                    ),
                    milestones=[
                        (m.day, m.range[0], m.range[2], float(with_plan[cut : cut + m.day].sum()))
                        for m in plan.milestones
                    ],
                )
            )
    plain_engine.dispose()
    return rows


# --- summary --------------------------------------------------------------------------------


def _inside(x: float, low: float, high: float) -> bool:
    return low <= x <= high


def bootstrap(
    rows: list[Row], stat: Callable[[list[Row]], float], seed: int = 0
) -> tuple[float, float, float]:
    """The statistic and its 90% bootstrap interval over stores (each store's goals resampled
    together: they share the store)."""
    by_store: dict[str, list[Row]] = {}
    for r in rows:
        by_store.setdefault(r.scenario, []).append(r)
    groups = list(by_store.values())
    rng = np.random.default_rng(seed)
    draws = [
        stat([r for i in rng.integers(0, len(groups), len(groups)) for r in groups[i]])
        for _ in range(RESAMPLES)
    ]
    low, high = np.percentile(draws, [5, 95])
    return stat(rows), float(low), float(high)


def uplift(rows: list[Row]) -> float:
    """Success rate with the plan minus without."""
    return statistics.fmean(r.reached_with for r in rows) - statistics.fmean(
        r.reached_without for r in rows
    )


def realised_profit_change(rows: list[Row]) -> float:
    return statistics.fmean(r.actual_profit_change for r in rows)


def summary(rows: list[Row]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, part in (("all", rows), *((m, [r for r in rows if r.metric == m]) for m in METRICS)):
        if not part:
            continue
        with_steps = [r for r in part if r.steps]
        weeks = [(r, m) for r in with_steps for m in r.milestones]
        out[name] = {
            "goals": len(part),
            "with_steps": len(with_steps),
            "reached_without": statistics.fmean(r.reached_without for r in part),
            "predicted_without": statistics.fmean(r.p_without for r in part),
            "reached_with": statistics.fmean(r.reached_with for r in part),
            "predicted_with": statistics.fmean(r.p_with for r in part),
            "uplift": bootstrap(part, uplift),
            "brier_with": statistics.fmean((r.p_with - r.reached_with) ** 2 for r in part),
            "milestone_weeks": len(weeks),
            "milestone_hits": statistics.fmean(_inside(m[3], m[1], m[2]) for _, m in weeks)
            if weeks
            else None,
            "outcome_coverage": statistics.fmean(
                _inside(r.actual_with, r.outcome[0], r.outcome[2]) for r in part
            ),
            # the twin's change is paired (the same draws with and without); the simulator's
            # store with the plan draws its own randomness after the first step, so one goal's
            # realised change carries both stores' noise: compared on average, not one by one
            "profit_change_predicted": statistics.fmean(r.profit_change[1] for r in with_steps)
            if with_steps
            else None,
            "profit_change_realised": bootstrap(with_steps, realised_profit_change)
            if with_steps
            else None,
            "skipped_actions": sum(r.skipped for r in part),
        }
    return out


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def report(suite: str, run_id: str, rows: list[Row], s: dict[str, Any]) -> str:
    a = s["all"]
    hits = a["milestone_hits"]
    met = hits is not None and BAND[0] <= hits <= BAND[1]
    lines = [
        f"# Goal plans: validation against the simulator (`{suite}`)",
        "",
        f"Run `{run_id}`, generated by `uv run python -m bench.goals_plans --suite {suite}`. "
        f"{len({r.scenario for r in rows})} stores; at days {', '.join(map(str, CUTS))} a goal "
        f"on {' and '.join(m.replace('_', ' ') for m in METRICS)} for the next {HORIZON} days, at "
        f"the {TARGET_PERCENTILE}th percentile of the forecast from that day "
        f"({len(rows)} goals). Each plan is built as in production, then its budget and pause "
        "steps are executed in the simulator from their day (the same store, generated again "
        "with them); reorder steps are not executed, experiments never counted.",
        "",
        "## Success with and without the plan",
        "",
        "| Metric | Goals | With steps | Reached without (predicted) | Reached with (predicted) "
        "| Uplift (90% interval over stores) | Brier with the plan |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, v in s.items():
        u, low, high = v["uplift"]
        lines.append(
            f"| {name.replace('_', ' ')} | {v['goals']} | {v['with_steps']} | "
            f"{_pct(v['reached_without'])} ({_pct(v['predicted_without'])}) | "
            f"{_pct(v['reached_with'])} ({_pct(v['predicted_with'])}) | "
            f"{u * 100:+.1f} points ({low * 100:+.1f} to {high * 100:+.1f}) | "
            f"{v['brier_with']:.4f} |"
        )
    lines += [
        "",
        "## Bands",
        "",
        "| Metric | Milestone weeks | Inside the P10-P90 band | Outcome inside its P10-P90 |",
        "| --- | --- | --- | --- |",
        *(
            f"| {name.replace('_', ' ')} | {v['milestone_weeks']} | {_pct(v['milestone_hits'])} "
            f"| {_pct(v['outcome_coverage'])} |"
            for name, v in s.items()
        ),
        "",
        "Effect of the plans on net profit over their detailed days, per goal with steps: the "
        "twin's median against what the simulator realised (a mean over goals, with its 90% "
        "interval over stores; one goal's realised change also carries the noise of both "
        "stores, which draw their own randomness after the first step).",
        "",
        "| Metric | Predicted (mean of medians) | Realised (90% interval) |",
        "| --- | --- | --- |",
        *(
            f"| {name.replace('_', ' ')} | {v['profit_change_predicted']:,.0f} | "
            f"{v['profit_change_realised'][0]:,.0f} ({v['profit_change_realised'][1]:,.0f} to "
            f"{v['profit_change_realised'][2]:,.0f}) |"
            for name, v in s.items()
            if v["profit_change_realised"] is not None
        ),
        "",
        f"Milestone bands: {_pct(hits)} of weeks inside (target {_pct(BAND[0])}-{_pct(BAND[1])}"
        f" for a P10-P90 band): {'met' if met else 'missed'}.",
        "",
        "## Steps",
        "",
        "| Lever | Plans using it |",
        "| --- | --- |",
        *(
            f"| `{lever}` | {n} |"
            for lever, n in Counter(lv for r in rows for lv in set(r.steps)).most_common()
        ),
        "",
        f"Reorder actions not executed: {a['skipped_actions']}. Plans without any step "
        f"(nothing the twin found worth doing): {a['goals'] - a['with_steps']}.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate goal plans against the simulator")
    parser.add_argument("--suite", choices=["goals_dev", "goals_test"], default="goals_dev")
    parser.add_argument("--only", nargs="*", help="scenario ids")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    parser.add_argument("--resume", action="store_true", help="skip the stores already done")
    parser.add_argument("--database", default=DATABASE, help="prefix of the bench databases")
    args = parser.parse_args(argv)
    configure_logging("WARNING")
    suite: Suite = args.suite
    manifests = [m for m in load_suite(suite) if not args.only or m.scenario_id in args.only]
    started = datetime.now(UTC).replace(microsecond=0)
    run_id = f"goals-plans-{suite}-{started:%Y%m%dT%H%M%SZ}"
    saved = _saved(suite)
    if not args.resume:
        saved.unlink(missing_ok=True)
    rows = _load_saved(saved)
    done = {r.scenario for r in rows}
    todo = [m for m in manifests if m.scenario_id not in done]
    url_plain = _database(args.database)
    urls_with = {(m, c): _database(_db(args.database, m, c)) for m in METRICS for c in CUTS}
    saved.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(store_rows, m, url_plain, urls_with) for m in todo]
        for future in as_completed(futures):
            store = future.result()
            with saved.open("a", encoding="utf-8") as f:
                f.writelines(json.dumps(asdict(r)) + "\n" for r in store)
            rows.extend(store)
    rows = [r for r in rows if r.scenario in {m.scenario_id for m in manifests}]
    rows.sort(key=lambda r: (r.scenario, r.cut, r.metric))
    s = summary(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{run_id}.json").write_text(
        json.dumps({"summary": s, "rows": [asdict(r) for r in rows]}, indent=1, default=str) + "\n",
        encoding="utf-8",
    )
    name = "goals-plans.md" if suite == "goals_test" else "goals-plans-dev.md"
    text = report(suite, run_id, rows, s)
    (args.out / name).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
