"""The demo store (Task 5 B7): the golden stockout store, with a history to show.

    uv run python -m bench.demo_seed             # make demo-seed: a fresh profit_demo database
    uv run python -m bench.demo_seed --record    # re-record the model exchanges (synthetic data)

1. The golden stockout store enters the simulator 28 days before its data end.
2. The owner sets a goal: net profit over the next 90 days, at the forecast's median (a goal
   reached about one time in two without a plan). Confirmed, planned, and the plan accepted:
   its first steps are proposed as decisions, left pending (the owner's to approve).
3. Two past decisions on a campaign that neither promotes the product nor is in the goal's
   plan, proposed by the owner, approved and executed: a budget cut, then a raise a week
   later. Each is measured by synthetic control after its 7-day window (measured, or
   abstained when the fit is weak). After each week, the goal's weekly tracking.
4. Fourteen days before the data end, detection raises the critical stockout alert (ads still
   spending on a product out of stock); the alert proposes its decision, left pending. It acts
   on the campaign the goal's budget reallocation step lowers, on more recent data: that step's
   decision is superseded, and the goal's plan proposes a revision.
5. The alert is investigated; its step trace is kept.
6. The daily brief, the weekly report (with the goal's progress) and the monthly review.
7. An owner and an API token (printed once, never written to the report).

Model calls replay the exchanges recorded under `backend/tests/cassettes/demo/` (no key, no
network), so the seed is the same on every machine; `--record` calls the model once and
rewrites them. `make demo` runs the Task 4 loop on this store (bench/demo.py).
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import Engine, text

from app.agent.contracts import ActionFamily
from app.agent.llm.cassette import LLMMode
from app.agent.llm.factory import build_provider
from app.agent.llm.provider import LLMProvider
from app.agent.trace import steps_after
from app.api.stores import run_investigation
from app.auth.service import add_owner, create_api_token
from app.briefings.models import BriefingKind
from app.briefings.service import generate
from app.causal.outcome import WINDOW_DAYS, measure
from app.config import Settings, get_settings, repo_path
from app.db import make_engine, tenant_transaction
from app.decisions.options import Option, OptionKind, OptionSet, Reversibility
from app.decisions.store import Channel, Verdict, decide, propose, targets
from app.decisions.store import get as get_decision
from app.delivery.alerts import dispatch_alerts
from app.detection.models import AlertLevel, Incident
from app.detection.pipeline import run_pipeline
from app.detection.series import load_series
from app.executor.simulator import SimulatorAdapter
from app.executor.worker import Executor
from app.facts.engine import FactEngine
from app.goals import service as goals
from app.goals.feasibility import seed_of
from app.goals.forecast import daily_values, forecast
from app.observability import configure_logging
from app.twin import Action, ActionKind, fit_twin
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR
from bench.scenarios.manifest import ScenarioManifest, load_suite
from bench.simulator import advance, register

SCENARIO = "golden-stockout_on_promoted"
DEMO_DB = "profit_demo"
CASSETTES = repo_path("backend/tests/cassettes/demo")
OWNER = "owner@example.com"
DAYS_BEFORE_END = 28
PAST = (("budget -30%", Decimal("-0.3")), ("budget +20%", Decimal("0.2")))
GOAL_DAYS = 90
GOAL_PERCENTILE = 50
KINDS = (BriefingKind.DAILY, BriefingKind.WEEKLY, BriefingKind.MONTHLY)
COUNTED = (
    "incidents",
    "alerts",
    "decisions",
    "actions",
    "goals",
    "goal_plans",
    "goal_steps",
    "goal_progress",
    "outcomes",
    "investigations",
    "investigation_steps",
    "briefings",
    "facts",
    "audit_log",
)


@dataclass(frozen=True)
class Past:
    label: str
    decision_id: UUID
    action_id: UUID
    outcome: dict[str, Any]


@dataclass(frozen=True)
class DemoGoal:
    goal_id: UUID
    plan_id: UUID
    steps: list[str]  # the plan's levers
    decisions: list[UUID]  # its due steps, proposed: the owner's to approve
    progress: list[dict[str, Any]]  # each week's tracking
    states: dict[str, str]  # each step decision's status once the alert's decision is proposed
    revisions: int  # revisions the plan proposes


@dataclass(frozen=True)
class Seeded:
    store_id: UUID
    manifest: ScenarioManifest
    goal: DemoGoal
    incident: Incident  # the critical stockout alert
    decision_id: UUID  # its decision, pending: the owner's to approve
    investigation_id: UUID
    past: list[Past]
    briefings: dict[str, UUID]
    api_token: str
    counts: dict[str, int]


def demo_manifest() -> ScenarioManifest:
    return next(m for m in load_suite("golden") if m.scenario_id == SCENARIO)


def _campaigns(engine: Engine, store: UUID, promoted: UUID) -> list[UUID]:
    """The store's other campaigns, largest spend first."""
    with tenant_transaction(engine, store) as conn:
        return list(
            conn.execute(
                text(
                    "SELECT campaign_id FROM ad_metrics_daily WHERE store_id = :s AND "
                    "campaign_id <> :c GROUP BY campaign_id ORDER BY sum(spend) DESC, campaign_id"
                ),
                {"s": store, "c": promoted},
            ).scalars()
        )


def _planned(engine: Engine, store: UUID, decisions: list[UUID]) -> set[UUID]:
    """The campaigns the goal plan's pending decisions act on."""
    with tenant_transaction(engine, store) as conn:
        acted = {t for d in decisions for t in targets(get_decision(conn, store, d))}
    return {UUID(t.split(":", 1)[1]) for t in acted if t.startswith("campaign:") and "*" not in t}


def owner_option(campaign: UUID, change: Decimal) -> OptionSet:
    kind = OptionKind.REDUCE_BUDGET if change < 0 else OptionKind.INCREASE_BUDGET
    family = (
        ActionFamily.PAUSE_OR_REDUCE_CAMPAIGN if change < 0 else ActionFamily.INCREASE_BUDGET_CAPPED
    )
    option = Option(
        f"owner:{kind.value}:{campaign}",
        kind,
        family,
        f"campaign:{campaign}",
        (Action(kind=ActionKind.CHANGE_BUDGET, entity=campaign, change=change),),
        Reversibility.REVERSIBLE,
        (),
        (),
    )
    return OptionSet(
        cause="owner",
        entity=f"campaign:{campaign}",
        options=(option,),
        recommended=option.option_id,
        reason="the owner's own change",
        floor=Decimal(100),
    )


def past_decision(
    engine: Engine,
    store: UUID,
    campaign: UUID,
    label: str,
    change: Decimal,
    seed: int,
    *,
    when: datetime,
) -> Past:
    """Proposed, approved and executed at `when` (its week: the policy allows one change per
    campaign a day), then measured once its window has passed."""
    with tenant_transaction(engine, store) as conn:
        model = fit_twin(conn, store)
        d = propose(
            conn,
            FactEngine(conn, store),
            model,
            owner_option(campaign, change),
            source="owner",
            now=when,
        )
        decide(
            conn,
            store,
            d.decision_id,
            d.recommended_option_id,
            Verdict.APPROVED,
            channel=Channel.API,
            actor=f"owner:{OWNER}",
            now=when,
        )
    Executor(engine, {"simulator": SimulatorAdapter(engine)}, clock=lambda: when).run_once()
    advance(engine, store, WINDOW_DAYS)
    with tenant_transaction(engine, store) as conn:
        action_id: UUID = conn.execute(
            text(
                "SELECT action_id FROM actions WHERE store_id = :s AND decision_id = :d AND "
                "status = 'executed'"
            ),
            {"s": store, "d": d.decision_id},
        ).scalar_one()
        outcome = measure(conn, store, action_id, seed=seed)  # replayable
    return Past(label, d.decision_id, action_id, outcome)


def set_goal(engine: Engine, store: UUID) -> tuple[UUID, UUID, list[str], list[UUID]]:
    """The owner's goal: net profit over the next 90 days at the forecast's median, as the API
    takes it (created, then confirmed); its plan proposed and accepted."""
    now = datetime.now(UTC)
    with tenant_transaction(engine, store) as conn:
        today = goals.data_end(conn, store)
        series = load_series(conn, store)
        values = np.array([float(v) for v in daily_values(series, "net_profit")])
        seed = seed_of(store, "net_profit", today, GOAL_DAYS)
        paths = forecast(values, series.start, "net_profit", GOAL_DAYS, seed).paths
        target = round(float(np.percentile(paths[:, -1], GOAL_PERCENTILE)), -3)
        goal = goals.create(
            conn,
            store,
            "net_profit",
            Decimal(target),
            today + timedelta(days=GOAL_DAYS),
            now=now,
            question=f"I want {target:,.0f} in net profit over the next three months.",
        )
        goals.confirm(conn, store, goal.goal_id, now=now)
        plan = goals.make_plan(conn, store, goal.goal_id, now=now)
        accepted = goals.accept(conn, store, plan.plan_id, now=now, actor=f"owner:{OWNER}")
    proposed = [s.decision_id for s in accepted.steps if s.decision_id is not None]
    return goal.goal_id, plan.plan_id, [s.lever for s in plan.steps], proposed


def track_goal(engine: Engine, store: UUID, goal_id: UUID) -> dict[str, Any]:
    """The weekly tracking job's work for the goal."""
    with tenant_transaction(engine, store) as conn:
        p = goals.track(conn, store, goal_id, now=datetime.now(UTC))
    assert p is not None
    return {"day": p.day, "status": p.status, "verdict": p.verdict, "adherence": p.adherence}


def _local_today(engine: Engine, store: UUID) -> date:
    """The day after the last day of data: the store's today in the simulator."""
    with tenant_transaction(engine, store) as conn:
        today: date = conn.execute(
            text("SELECT max(ordered_at)::date + 1 FROM orders WHERE store_id = :s"), {"s": store}
        ).scalar_one()
    return today


def _counts(engine: Engine, store: UUID) -> dict[str, int]:
    with tenant_transaction(engine, store) as conn:
        return {
            table: int(
                conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE store_id = :s"),
                    {"s": store},
                ).scalar_one()
            )
            for table in COUNTED
        }


def seed(engine: Engine, provider: LLMProvider) -> Seeded:
    manifest = demo_manifest()
    label = manifest.labels[0]
    promoted = next(e.id for e in label.entities if e.kind.value == "campaign")
    assert promoted is not None
    store = register(engine, manifest, manifest.config.days - DAYS_BEFORE_END)
    goal_id, plan_id, levers, proposed = set_goal(engine, store)
    planned = _planned(engine, store, proposed)
    others = [c for c in _campaigns(engine, store, promoted) if c not in planned]
    assert others, "no campaign outside the promoted one and the goal's plan"
    past, weeks = [], []
    now = datetime.now(UTC)
    for seed, (name, change) in enumerate(PAST):
        campaign = others[seed % len(others)]  # with one such campaign: cut, then raise it
        when = now - timedelta(days=WINDOW_DAYS * (len(PAST) - seed))  # its week, in the past
        past.append(past_decision(engine, store, campaign, name, change, seed, when=when))
        weeks.append(track_goal(engine, store, goal_id))
    detected = run_pipeline(engine, store)
    alert = next(
        a
        for a in dispatch_alerts(engine, store)
        if a.level is AlertLevel.CRITICAL and a.decision_id is not None
    )
    assert alert.decision_id is not None
    incident = next(i for i in detected.incidents if i.incident_id == alert.incident_id)
    with tenant_transaction(engine, store) as conn:
        states = {str(d): get_decision(conn, store, d).status.value for d in proposed}
        revisions = sum(p.kind == "revision" for p in goals.progress(conn, store, goal_id))
    investigation_id = uuid4()
    run_investigation(engine, provider, store, incident.incident_id, investigation_id, True)
    with tenant_transaction(engine, store) as conn:
        steps = steps_after(conn, store, investigation_id)
    if steps[-1].kind != "done" or steps[-1].detail.get("status") != "complete":
        stopped = [s.detail for s in steps if s.kind in ("stopped", "failed")]
        raise RuntimeError(f"the investigation is not complete: {stopped or steps[-1].detail}")
    local_today = _local_today(engine, store)
    briefings: dict[str, UUID] = {}
    for kind in KINDS:
        record = generate(engine, store, kind, provider, local_today=local_today, run_id="demo")
        if record.narration.narrative is None:
            raise RuntimeError(f"the {kind.value} briefing has no narrative")
        briefings[kind.value] = record.briefing_id
    owner = add_owner(engine, OWNER, store)
    _, api_token = create_api_token(engine, store, "demo", owner, datetime.now(UTC))
    return Seeded(
        store_id=store,
        manifest=manifest,
        goal=DemoGoal(goal_id, plan_id, levers, proposed, weeks, states, revisions),
        incident=incident,
        decision_id=alert.decision_id,
        investigation_id=investigation_id,
        past=past,
        briefings=briefings,
        api_token=api_token,
        counts=_counts(engine, store),
    )


def demo_provider(settings: Settings, mode: LLMMode = LLMMode.REPLAY) -> LLMProvider:
    return build_provider(settings, mode=mode, cassette_dir=CASSETTES)


def markdown(s: Seeded, started: datetime) -> str:
    lines = [
        "# Demo store",
        "",
        f"Seeded {started.isoformat()} by `make demo-seed` from `{SCENARIO}` (simulator, "
        f"{DAYS_BEFORE_END} days before the data end, then two windows of {WINDOW_DAYS} days).",
        "",
        f"- Store `{s.store_id}`, owner `{OWNER}` with an API token (printed by the seed).",
        f"- Alert `{s.incident.incident_id}`, level **{s.incident.alert.value}** "
        f"({s.incident.category.value}); its decision `{s.decision_id}` is pending.",
        f"- Investigation `{s.investigation_id}`, with its step trace.",
        "- Briefings: " + ", ".join(f"{k} `{v}`" for k, v in s.briefings.items()) + ".",
        f"- Goal `{s.goal.goal_id}`: net profit over the next {GOAL_DAYS} days; plan "
        f"`{s.goal.plan_id}` accepted ("
        + (", ".join(f"`{lv}`" for lv in s.goal.steps) or "no step")
        + "); its due steps' decisions: "
        + ", ".join(f"`{d[:8]}` {state}" for d, state in s.goal.states.items())
        + (
            " (superseded: the alert's decision acts on the same campaign, on more recent "
            f"data); revisions proposed: {s.goal.revisions}."
            if "superseded" in s.goal.states.values()
            else "."
        ),
        "",
        "Goal tracking:",
        "",
        "| Day | Status | Verdict | Steps due | Done | Pending |",
        "| --- | --- | --- | --- | --- | --- |",
        *(
            f"| {w['day']} | {w['status']} | {w['verdict']} | {w['adherence']['due']} | "
            f"{w['adherence']['done']} | {w['adherence']['pending']} |"
            for w in s.goal.progress
        ),
        "",
        "Past decisions:",
        "",
        "| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in s.past:
        effect = p.outcome.get("effect") or {}
        lines.append(
            f"| `{str(p.decision_id)[:8]}` | {p.label} | {p.outcome['status']} "
            f"({p.outcome['reason']}) | {effect.get('p10', '-')} / {effect.get('p50', '-')} / "
            f"{effect.get('p90', '-')} | {p.outcome.get('relative_error')} |"
        )
    lines += ["", "Rows:", "", "| Table | Rows |", "| --- | --- |"]
    lines += [f"| {table} | {n} |" for table, n in s.counts.items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the demo store")
    parser.add_argument("--record", action="store_true", help="call the model and re-record")
    args = parser.parse_args(argv)
    configure_logging("WARNING")
    started = datetime.now(UTC).replace(microsecond=0)
    engine = make_engine(prepare_database(DEMO_DB))
    mode = LLMMode.RECORD if args.record else LLMMode.REPLAY
    seeded = seed(engine, demo_provider(get_settings(), mode))
    report = markdown(seeded, started)
    (REPORT_DIR / "demo-seed.md").write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(report)
    sys.stdout.write(f"\nAPI token for the demo store (shown once): {seeded.api_token}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
