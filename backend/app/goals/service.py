"""Goals as the owner sets them, their plans and their progress (Task 6 B4, SPEC 17, ADR 0024).

1. `create`: a draft goal (metric, target, deadline) counted from the day after the last day
   of data, with its target as a fact; `restate` writes it back in plain words for the owner
   to confirm. Nothing is analysed before the owner confirms.
2. `confirm`: the feasibility (`app.goals.feasibility`), as facts.
3. `make_plan`: a proposed plan (`app.goals.plan`) with its dated steps; `accept`: the owner
   accepts it, and its decision steps whose day has come become decisions in the normal flow
   (`app.decisions.store.propose`, source `goal`). Plans never execute anything.
4. `track` (weekly): the actual metric since the goal's start against the plan's milestone,
   the status (`ahead`, `on_track`, `behind`), step adherence, the updated probability (the
   remaining target from today), and a revision proposal after two weeks outside the band or
   a drop of a verdict level. `reforecast` (monthly, goals beyond 90 days): the updated
   probability, and a revision proposal once the plan's 90 days are over.
5. `revise`: a new target or deadline; the plans are superseded.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import Connection, text

from app.agent.contracts import ActionFamily
from app.decisions.options import Option, OptionKind, OptionSet, Reversibility
from app.decisions.store import DecisionStatus, propose
from app.decisions.store import get as get_decision
from app.detection.series import load_series
from app.domain.audit import append_audit
from app.facts.engine import FactEngine
from app.facts.model import Fact, Period, Scope, Unit
from app.facts.repository import get_facts
from app.goals import facts as gf
from app.goals.feasibility import (
    POINT_HORIZON,
    VERDICTS,
    Assessment,
    assess_store,
    checkpoints,
    verdict,
)
from app.goals.forecast import MAX_HORIZON, METHOD, METRICS, daily_values, forecast
from app.goals.levers import DECISION, Step, candidates, context, usual_reorders
from app.goals.plan import Plan, build
from app.settings.repository import StoreSettingsRepository
from app.twin import Action, ActionKind, fit_twin

METRIC_WORDS = {
    "net_profit": "net profit",
    "contribution_margin": "contribution margin",
    "revenue": "revenue",
}
PLAN_METHOD = "goal_plan_greedy_v1"
RANK = {name: i for i, (_, name) in enumerate(reversed(VERDICTS))}  # unlikely 0 .. likely 3


class GoalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Goal:
    goal_id: UUID
    store_id: UUID
    metric: str
    target: Decimal
    currency: str
    as_of: date
    deadline: date
    status: str
    question: str | None
    target_fact_id: int | None
    created_at: datetime
    confirmed_at: datetime | None

    @property
    def horizon(self) -> int:
        return (self.deadline - self.as_of).days


def data_end(conn: Connection, store_id: UUID) -> date:
    """The day after the last day of data: a goal set now counts from it."""
    end = conn.execute(
        text("SELECT max(ordered_at)::date + 1 FROM orders WHERE store_id = :s"), {"s": store_id}
    ).scalar_one()
    if end is None:
        raise GoalError("no_data", "the store has no data yet")
    day: date = end
    return day


def _goal(r: Any) -> Goal:
    return Goal(
        goal_id=r.goal_id,
        store_id=r.store_id,
        metric=r.metric,
        target=r.target,
        currency=r.currency,
        as_of=r.as_of,
        deadline=r.deadline,
        status=r.status,
        question=r.question,
        target_fact_id=r.target_fact_id,
        created_at=r.created_at,
        confirmed_at=r.confirmed_at,
    )


def get(conn: Connection, store_id: UUID, goal_id: UUID) -> Goal:
    row = conn.execute(
        text("SELECT * FROM goals WHERE store_id = :s AND goal_id = :g"),
        {"s": store_id, "g": goal_id},
    ).first()
    if row is None:
        raise GoalError("not_found", "no such goal")
    return _goal(row)


def list_goals(conn: Connection, store_id: UUID) -> list[Goal]:
    rows = conn.execute(
        text("SELECT * FROM goals WHERE store_id = :s ORDER BY created_at DESC, goal_id"),
        {"s": store_id},
    )
    return [_goal(r) for r in rows]


def _check(metric: str, as_of: date, deadline: date) -> None:
    if metric not in METRICS:
        raise GoalError("invalid_goal", f"goals are about {', '.join(METRICS)}")
    horizon = (deadline - as_of).days
    if not 1 <= horizon <= MAX_HORIZON:
        raise GoalError(
            "invalid_goal",
            f"the deadline must be within six months after the last day of data ({as_of})",
        )


def _target_fact(
    conn: Connection,
    goal_id: UUID,
    store_id: UUID,
    metric: str,
    target: Decimal,
    as_of: date,
    deadline: date,
    currency: str,
) -> Fact:
    return gf.target(
        FactEngine(conn, store_id),
        store_id,
        metric,
        target,
        (as_of, deadline),
        goal_id=goal_id,
        currency=currency,
    )


def create(
    conn: Connection,
    store_id: UUID,
    metric: str,
    target: Decimal,
    deadline: date,
    *,
    now: datetime,
    question: str | None = None,
) -> Goal:
    as_of = data_end(conn, store_id)
    _check(metric, as_of, deadline)
    currency = conn.execute(
        text("SELECT currency FROM stores WHERE store_id = :s"), {"s": store_id}
    ).scalar_one()
    goal_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO goals (goal_id, store_id, metric, target, currency, as_of, deadline, "
            "status, question, created_at, updated_at) VALUES (:g, :s, :m, :t, :c, :a, :d, "
            "'draft', :q, :now, :now)"
        ),
        {
            "g": goal_id,
            "s": store_id,
            "m": metric,
            "t": target,
            "c": currency,
            "a": as_of,
            "d": deadline,
            "q": question,
            "now": now,
        },
    )
    fact = _target_fact(conn, goal_id, store_id, metric, target, as_of, deadline, currency)
    conn.execute(
        text("UPDATE goals SET target_fact_id = :f WHERE store_id = :s AND goal_id = :g"),
        {"f": fact.id, "s": store_id, "g": goal_id},
    )
    append_audit(
        conn,
        store_id,
        actor="owner",
        action="goal.created",
        payload={"goal_id": str(goal_id), "metric": metric, "deadline": deadline.isoformat()},
        occurred_at=now,
    )
    return get(conn, store_id, goal_id)


def restate(goal: Goal) -> str:
    """The goal in plain words, for the owner to confirm (facts by reference, ISO dates)."""
    return (
        f"Your goal: {METRIC_WORDS[goal.metric]} of {{{{F{goal.target_fact_id}}}}} in total "
        f"from {goal.as_of.isoformat()} to {(goal.deadline - timedelta(days=1)).isoformat()} "
        f"included, the {METRIC_WORDS[goal.metric]} of {{{{E:store}}}} as a whole. Confirm it "
        "to see whether it is reachable."
    )


def feasibility(conn: Connection, goal: Goal) -> Assessment:
    """The goal's feasibility as it was set (from its first day)."""
    return assess_store(
        conn,
        goal.store_id,
        goal.metric,
        goal.target,
        goal.deadline,
        currency=goal.currency,
        as_of=goal.as_of,
    )


def confirm(conn: Connection, store_id: UUID, goal_id: UUID, *, now: datetime) -> Assessment:
    goal = get(conn, store_id, goal_id)
    if goal.status == "draft":
        conn.execute(
            text(
                "UPDATE goals SET status = 'confirmed', confirmed_at = :now, updated_at = :now "
                "WHERE store_id = :s AND goal_id = :g"
            ),
            {"now": now, "s": store_id, "g": goal_id},
        )
        append_audit(
            conn,
            store_id,
            actor="owner",
            action="goal.confirmed",
            payload={"goal_id": str(goal_id)},
            occurred_at=now,
        )
    return feasibility(conn, get(conn, store_id, goal_id))


# --- plans ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class StepRecord:
    step_id: UUID
    position: int
    lever: str
    kind: str
    due_date: date
    actions: list[dict[str, Any]]
    summary: str
    evidence: list[int]
    effect_fact_id: int | None
    experiment: dict[str, Any] | None
    status: str
    decision_id: UUID | None


@dataclass(frozen=True)
class PlanRecord:
    plan_id: UUID
    goal_id: UUID
    status: str
    as_of: date
    days: int
    payload: dict[str, Any]
    created_at: datetime
    accepted_at: datetime | None
    steps: list[StepRecord]


def get_plan(conn: Connection, store_id: UUID, plan_id: UUID) -> PlanRecord:
    row = conn.execute(
        text("SELECT * FROM goal_plans WHERE store_id = :s AND plan_id = :p"),
        {"s": store_id, "p": plan_id},
    ).first()
    if row is None:
        raise GoalError("not_found", "no such plan")
    steps = [
        StepRecord(
            step_id=r.step_id,
            position=r.position,
            lever=r.lever,
            kind=r.kind,
            due_date=r.due_date,
            actions=list(r.actions),
            summary=r.summary,
            evidence=list(r.evidence),
            effect_fact_id=r.effect_fact_id,
            experiment=r.experiment,
            status=r.status,
            decision_id=r.decision_id,
        )
        for r in conn.execute(
            text("SELECT * FROM goal_steps WHERE store_id = :s AND plan_id = :p ORDER BY position"),
            {"s": store_id, "p": plan_id},
        )
    ]
    return PlanRecord(
        plan_id=row.plan_id,
        goal_id=row.goal_id,
        status=row.status,
        as_of=row.as_of,
        days=row.days,
        payload=dict(row.payload),
        created_at=row.created_at,
        accepted_at=row.accepted_at,
        steps=steps,
    )


def plans(conn: Connection, store_id: UUID, goal_id: UUID) -> list[PlanRecord]:
    ids = conn.execute(
        text(
            "SELECT plan_id FROM goal_plans WHERE store_id = :s AND goal_id = :g "
            "ORDER BY created_at DESC, plan_id"
        ),
        {"s": store_id, "g": goal_id},
    ).scalars()
    return [get_plan(conn, store_id, p) for p in ids]


def current_plan(conn: Connection, store_id: UUID, goal_id: UUID) -> PlanRecord | None:
    return next((p for p in plans(conn, store_id, goal_id) if p.status == "accepted"), None)


def _actual(engine: FactEngine, goal: Goal, until: date) -> Fact:
    return engine.persist(
        engine.adopt(engine.fact(goal.metric, Scope.store(), Period.days(goal.as_of, until)))
    )


def _plan_facts(
    engine: FactEngine, goal: Goal, plan: Plan, method: str, parents: tuple[tuple[str, Fact], ...]
) -> dict[str, Any]:
    """The plan's numbers as facts; returns the payload that names them."""

    def estimate(
        formula: str, day: int, unit: Unit, qs: tuple[float, float, float], key: object
    ) -> Fact:
        return gf.estimate(
            engine,
            goal.store_id,
            formula=formula,
            period=(plan.as_of, plan.as_of + timedelta(days=day)),
            unit=unit,
            quantiles=qs,
            method=method,
            key=(goal.goal_id, plan.target, key),
            parents=parents,
            currency=goal.currency,
        )

    m = goal.metric
    without = estimate(
        f"goal.plan.baseline_probability.{m}",
        plan.horizon,
        Unit.RATIO,
        plan.probability_without,
        "without",
    )
    with_plan = estimate(
        f"goal.plan.probability.{m}",
        plan.horizon,
        Unit.RATIO,
        plan.probability_with,
        "with",
    )
    outcome = estimate(f"goal.plan.outcome.{m}", plan.horizon, Unit.MONEY, plan.outcome, "outcome")
    profit = estimate(
        "goal.plan.profit_change.net_profit", plan.days, Unit.MONEY, plan.profit_change, "profit"
    )
    milestones = [
        {
            "day": ms.day,
            "date": ms.date.isoformat(),
            "fact_id": estimate(f"goal.milestone.{m}", ms.day, Unit.MONEY, ms.range, ms.day).id,
        }
        for ms in plan.milestones
    ]
    alternatives = None
    if plan.alternatives is not None:
        alt = plan.alternatives
        alternatives = {
            "target_50_fact_id": estimate(
                f"goal.alternative.target_50.{m}",
                plan.horizon,
                Unit.MONEY,
                alt.target_50,
                "t50",
            ).id,
            "target_70_fact_id": estimate(
                f"goal.alternative.target_70.{m}",
                plan.horizon,
                Unit.MONEY,
                alt.target_70,
                "t70",
            ).id,
            "deadline": (plan.as_of + timedelta(days=alt.deadline_days)).isoformat()
            if alt.deadline_days
            else None,
        }
    band = plan.probability_with
    return {
        "metric": m,
        "target_fact_id": goal.target_fact_id,
        "probability_without_fact_id": without.id,
        "probability_with_fact_id": with_plan.id,
        "outcome_fact_id": outcome.id,
        "profit_change_fact_id": profit.id,
        "verdict_with": plan.verdict_with,
        "verdict_band": [verdict(band[0]), verdict(band[2])],
        "shows_point": plan.horizon <= POINT_HORIZON,
        "lowers_profit": plan.lowers_profit,
        "milestones": milestones,
        "checkpoints": [
            (plan.as_of + timedelta(days=d)).isoformat() for d in checkpoints(plan.horizon)
        ],
        "alternatives": alternatives,
        "experiments": [
            {
                "lever": s.lever,
                "summary": s.summary,
                "evidence": list(s.evidence),
                "experiment": s.experiment.__dict__ if s.experiment else None,
            }
            for s in plan.experiments
        ],
        "assumptions": list(plan.assumptions),
        "detailed_days": plan.days,
    }


def make_plan(conn: Connection, store_id: UUID, goal_id: UUID, *, now: datetime) -> PlanRecord:
    """A proposed plan from today's data, for what is left of the goal."""
    goal = get(conn, store_id, goal_id)
    if goal.status == "draft":
        raise GoalError("not_confirmed", "confirm the goal before planning it")
    as_of = max(goal.as_of, data_end(conn, store_id))
    horizon = (goal.deadline - as_of).days
    if horizon < 1:
        raise GoalError("invalid_goal", "the goal's deadline has passed")
    engine = FactEngine(conn, store_id)
    done = Decimal(0)
    if as_of > goal.as_of:
        done = _actual(engine, goal, as_of).value or Decimal(0)
    remaining = float(goal.target - done)
    series = load_series(conn, store_id)
    values = np.array([float(v) for v in daily_values(series, goal.metric)], dtype=np.float64)
    values = values[: series.index(as_of)]
    seed = int(goal.goal_id.int % (2**63))
    base = forecast(values, series.start, goal.metric, horizon, seed)
    extended = forecast(values, series.start, goal.metric, MAX_HORIZON, seed)
    model = fit_twin(conn, store_id, as_of=as_of, series=series)
    ctx = context(conn, store_id, model, horizon, series, goal.metric)
    floor = StoreSettingsRepository(conn).get_or_default(store_id).materiality.absolute
    plan = build(
        model,
        base.paths,
        candidates(ctx),
        metric=goal.metric,
        target=remaining,
        as_of=as_of,
        floor_monthly=floor,
        extended=extended.paths,
        background=usual_reorders(ctx),
    )
    method = f"{PLAN_METHOD};{METHOD};calibration {base.calibration};twin {model.fingerprint}"
    window = Period.days(as_of - timedelta(days=28), as_of)
    history = engine.persist(engine.adopt(engine.fact(goal.metric, Scope.store(), window)))
    payload = _plan_facts(engine, goal, plan, method, (("history", history),))
    conn.execute(
        text(
            "UPDATE goal_plans SET status = 'superseded' WHERE store_id = :s AND goal_id = :g "
            "AND status = 'proposed'"
        ),
        {"s": store_id, "g": goal_id},
    )
    plan_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO goal_plans (plan_id, store_id, goal_id, status, as_of, days, payload, "
            "created_at) VALUES (:p, :s, :g, 'proposed', :a, :d, CAST(:pl AS jsonb), :now)"
        ),
        {
            "p": plan_id,
            "s": store_id,
            "g": goal_id,
            "a": as_of,
            "d": plan.days,
            "pl": json.dumps(payload),
            "now": now,
        },
    )
    for position, (step, effect) in enumerate(plan.steps, start=1):
        fact = gf.estimate(
            engine,
            store_id,
            formula=f"goal.step.{step.lever}",
            period=(as_of, as_of + timedelta(days=plan.days)),
            unit=Unit.MONEY,
            quantiles=effect,
            method=method,
            key=(plan_id, position),
            parents=(("history", history),),
            currency=goal.currency,
        )
        conn.execute(
            text(
                "INSERT INTO goal_steps (step_id, store_id, plan_id, position, lever, kind, "
                "due_date, actions, summary, evidence, effect_fact_id, experiment, status, "
                "created_at) VALUES (:id, :s, :p, :pos, :lever, :kind, :due, CAST(:act AS jsonb), "
                ":summary, CAST(:ev AS jsonb), :f, NULL, 'planned', :now)"
            ),
            {
                "id": uuid4(),
                "s": store_id,
                "p": plan_id,
                "pos": position,
                "lever": step.lever,
                "kind": step.kind,
                "due": as_of + timedelta(days=step.day),
                "act": json.dumps([a.model_dump(mode="json") for a in step.actions]),
                "summary": step.summary,
                "ev": json.dumps(list(step.evidence)),
                "f": fact.id,
                "now": now,
            },
        )
    append_audit(
        conn,
        store_id,
        actor="system:goals",
        action="goal.plan_proposed",
        payload={"goal_id": str(goal_id), "plan_id": str(plan_id), "steps": len(plan.steps)},
        occurred_at=now,
    )
    return get_plan(conn, store_id, plan_id)


def _option_set(record: StepRecord, actions: tuple[Action, ...]) -> OptionSet:
    changes = [a.change for a in actions if a.kind is ActionKind.CHANGE_BUDGET]
    if all(a.kind is ActionKind.PAUSE_CAMPAIGN for a in actions):
        kind, family = OptionKind.PAUSE_CAMPAIGN, ActionFamily.PAUSE_OR_REDUCE_CAMPAIGN
    elif changes and all(c > 0 for c in changes):
        kind, family = OptionKind.INCREASE_BUDGET, ActionFamily.INCREASE_BUDGET_CAPPED
    elif changes and all(c < 0 for c in changes):
        kind, family = OptionKind.REDUCE_BUDGET, ActionFamily.PAUSE_OR_REDUCE_CAMPAIGN
    else:
        kind, family = OptionKind.REDUCE_BUDGET, ActionFamily.REDUCE_OR_REALLOCATE_BUDGET
    entity = f"campaign:{actions[0].entity}"
    option = Option(
        f"goal:{record.lever}:{record.step_id}",
        kind,
        family,
        entity,
        actions,
        Reversibility.REVERSIBLE,
        (),
        (),
    )
    return OptionSet(
        cause="goal",
        entity=entity,
        options=(option,),
        recommended=option.option_id,
        reason=f"a step of the goal's plan ({record.lever})",
        floor=Decimal(0),
    )


def propose_due_steps(
    conn: Connection, store_id: UUID, plan: PlanRecord, *, today: date, now: datetime
) -> int:
    """The plan's decision steps whose day has come become proposed decisions."""
    due = [
        s
        for s in plan.steps
        if s.kind == DECISION and s.status == "planned" and s.due_date <= today
    ]
    if not due:
        return 0
    model = fit_twin(conn, store_id)
    engine = FactEngine(conn, store_id)
    for step in due:
        actions = tuple(Action.model_validate({**a, "start": 0}) for a in step.actions)
        decision = propose(conn, engine, model, _option_set(step, actions), source="goal", now=now)
        conn.execute(
            text(
                "UPDATE goal_steps SET status = 'proposed', decision_id = :d "
                "WHERE store_id = :s AND step_id = :id"
            ),
            {"d": decision.decision_id, "s": store_id, "id": step.step_id},
        )
    return len(due)


def accept(
    conn: Connection, store_id: UUID, plan_id: UUID, *, now: datetime, actor: str
) -> PlanRecord:
    plan = get_plan(conn, store_id, plan_id)
    if plan.status != "proposed":
        raise GoalError("conflict", f"the plan is {plan.status}")
    conn.execute(
        text(
            "UPDATE goal_plans SET status = 'superseded' WHERE store_id = :s AND goal_id = :g "
            "AND status = 'accepted'"
        ),
        {"s": store_id, "g": plan.goal_id},
    )
    conn.execute(
        text(
            "UPDATE goal_plans SET status = 'accepted', accepted_at = :now "
            "WHERE store_id = :s AND plan_id = :p"
        ),
        {"now": now, "s": store_id, "p": plan_id},
    )
    conn.execute(
        text(
            "UPDATE goals SET status = 'planned', updated_at = :now "
            "WHERE store_id = :s AND goal_id = :g"
        ),
        {"now": now, "s": store_id, "g": plan.goal_id},
    )
    proposed = propose_due_steps(
        conn, store_id, get_plan(conn, store_id, plan_id), today=data_end(conn, store_id), now=now
    )
    append_audit(
        conn,
        store_id,
        actor=actor,
        action="goal.plan_accepted",
        payload={"plan_id": str(plan_id), "decisions_proposed": proposed},
        occurred_at=now,
    )
    return get_plan(conn, store_id, plan_id)


# --- progress -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Progress:
    progress_id: UUID
    goal_id: UUID
    plan_id: UUID | None
    kind: str
    as_of: date
    day: int
    actual_fact_id: int | None
    milestone_fact_id: int | None
    probability_fact_id: int | None
    status: str | None
    verdict: str | None
    adherence: dict[str, Any]
    revision_proposed: bool
    reason: str | None


def progress(conn: Connection, store_id: UUID, goal_id: UUID) -> list[Progress]:
    rows = conn.execute(
        text(
            "SELECT * FROM goal_progress WHERE store_id = :s AND goal_id = :g ORDER BY as_of, kind"
        ),
        {"s": store_id, "g": goal_id},
    )
    return [
        Progress(
            r.progress_id,
            r.goal_id,
            r.plan_id,
            r.kind,
            r.as_of,
            r.day,
            r.actual_fact_id,
            r.milestone_fact_id,
            r.probability_fact_id,
            r.status,
            r.verdict,
            dict(r.adherence),
            r.revision_proposed,
            r.reason,
        )
        for r in rows
    ]


def _adherence(conn: Connection, store_id: UUID, plan: PlanRecord, today: date) -> dict[str, Any]:
    out: dict[str, Any] = {"due": 0, "done": 0, "pending": 0, "skipped": 0, "steps": []}
    for s in plan.steps:
        if s.due_date > today:
            continue
        out["due"] += 1
        state = "pending"
        if s.decision_id is not None:
            status = get_decision(conn, store_id, s.decision_id).status
            if status in (DecisionStatus.EXECUTED, DecisionStatus.MEASURED):
                state = "done"
            elif status in (DecisionStatus.REJECTED, DecisionStatus.EXPIRED):
                state = "skipped"
        elif s.status in ("done", "skipped"):
            state = s.status
        out[state] += 1
        out["steps"].append({"position": s.position, "lever": s.lever, "state": state})
    return out


def _so_far(actual: Fact | None) -> Decimal:
    return Decimal(0) if actual is None or actual.value is None else actual.value


def _remaining(
    conn: Connection, goal: Goal, today: date
) -> tuple[Fact | None, Assessment | None, str | None]:
    """The actual metric so far (None before the goal's first full day), and the feasibility
    of what is left from today."""
    engine = FactEngine(conn, goal.store_id)
    actual = _actual(engine, goal, today) if today > goal.as_of else None
    if today >= goal.deadline:
        return actual, None, None
    left = goal.target - _so_far(actual)
    assessment = assess_store(
        conn, goal.store_id, goal.metric, left, goal.deadline, currency=goal.currency
    )
    f = assessment.feasibility
    word = f.verdict if f.shows_point else f"{f.verdict_band[0]}-{f.verdict_band[1]}"
    return actual, assessment, word


def _close(conn: Connection, goal: Goal, actual: Fact | None, now: datetime) -> str:
    status = "achieved" if _so_far(actual) >= goal.target else "missed"
    conn.execute(
        text(
            "UPDATE goals SET status = :st, updated_at = :now WHERE store_id = :s AND goal_id = :g"
        ),
        {"st": status, "now": now, "s": goal.store_id, "g": goal.goal_id},
    )
    return status


def _record(conn: Connection, goal: Goal, **row: Any) -> Progress:
    conn.execute(
        text(
            "INSERT INTO goal_progress (progress_id, store_id, goal_id, plan_id, kind, as_of, day, "
            "actual_fact_id, milestone_fact_id, probability_fact_id, status, verdict, adherence, "
            "revision_proposed, reason, created_at) VALUES (:id, :s, :g, :p, :kind, :as_of, :day, "
            ":actual, :milestone, :probability, :status, :verdict, CAST(:adherence AS jsonb), "
            ":revision, :reason, :now) ON CONFLICT (store_id, goal_id, kind, as_of) DO NOTHING"
        ),
        {
            "id": uuid4(),
            "s": goal.store_id,
            "g": goal.goal_id,
            **row,
            "adherence": json.dumps(row["adherence"]),
        },
    )
    found = next(
        p
        for p in progress(conn, goal.store_id, goal.goal_id)
        if p.kind == row["kind"] and p.as_of == row["as_of"]
    )
    return found


def track(conn: Connection, store_id: UUID, goal_id: UUID, *, now: datetime) -> Progress | None:
    """This week's progress of a goal with an accepted plan (None without one)."""
    goal = get(conn, store_id, goal_id)
    plan = current_plan(conn, store_id, goal_id)
    if plan is None or goal.status != "planned":
        return None
    today = data_end(conn, store_id)
    day = (today - goal.as_of).days
    if day < 1:
        return None
    propose_due_steps(conn, store_id, plan, today=today, now=now)
    plan = get_plan(conn, store_id, plan.plan_id)
    actual, assessment, word = _remaining(conn, goal, today)
    passed = [m for m in plan.payload["milestones"] if m["day"] <= (today - plan.as_of).days]
    milestone_id = passed[-1]["fact_id"] if passed else None
    status = None
    if milestone_id is not None:
        [milestone] = get_facts(conn, store_id, [milestone_id]).values()
        value = _so_far(actual)
        low, high = milestone.p10 or Decimal(0), milestone.p90 or Decimal(0)
        status = "behind" if value < low else "ahead" if value > high else "on_track"
    reasons = []
    earlier = [p for p in progress(conn, store_id, goal_id) if p.kind == "weekly"]
    if status in ("ahead", "behind") and earlier and earlier[-1].status in ("ahead", "behind"):
        reasons.append("a second week in a row outside the milestone's range")
    planned = plan.payload["verdict_with"]
    now_word = word.split("-")[-1] if word else None
    if now_word is not None and RANK[now_word] < RANK[planned]:
        reasons.append(f"the verdict dropped from {planned} to {now_word}")
    if assessment is None:
        reasons.append(f"the deadline has passed: the goal is {_close(conn, goal, actual, now)}")
    return _record(
        conn,
        goal,
        p=plan.plan_id,
        kind="weekly",
        as_of=today,
        day=day,
        actual=actual.id if actual else None,
        milestone=milestone_id,
        probability=assessment.probability.id if assessment else None,
        status=status,
        verdict=word,
        adherence=_adherence(conn, store_id, plan, today),
        revision=bool(reasons) and assessment is not None,
        reason="; ".join(reasons) or None,
        now=now,
    )


def reforecast(
    conn: Connection, store_id: UUID, goal_id: UUID, *, now: datetime
) -> Progress | None:
    """The monthly re-forecast of a goal beyond 90 days (None for shorter or closed goals)."""
    goal = get(conn, store_id, goal_id)
    if goal.horizon <= POINT_HORIZON or goal.status not in ("confirmed", "planned"):
        return None
    today = data_end(conn, store_id)
    actual, assessment, word = _remaining(conn, goal, today)
    plan = current_plan(conn, store_id, goal_id)
    reason = None
    if assessment is None:
        reason = f"the deadline has passed: the goal is {_close(conn, goal, actual, now)}"
    elif plan is not None and (today - plan.as_of).days >= plan.days:
        reason = "the plan's detailed days are over: plan the next quarter"
    return _record(
        conn,
        goal,
        p=plan.plan_id if plan else None,
        kind="reforecast",
        as_of=today,
        day=(today - goal.as_of).days,
        actual=actual.id if actual else None,
        milestone=None,
        probability=assessment.probability.id if assessment else None,
        status=None,
        verdict=word,
        adherence={},
        revision=reason is not None and assessment is not None,
        reason=reason,
        now=now,
    )


def revise(
    conn: Connection,
    store_id: UUID,
    goal_id: UUID,
    *,
    now: datetime,
    target: Decimal | None = None,
    deadline: date | None = None,
) -> Goal:
    goal = get(conn, store_id, goal_id)
    if goal.status in ("achieved", "missed", "cancelled"):
        raise GoalError("conflict", f"the goal is {goal.status}")
    new_target = goal.target if target is None else target
    new_deadline = goal.deadline if deadline is None else deadline
    _check(goal.metric, goal.as_of, new_deadline)
    fact = _target_fact(
        conn, goal_id, store_id, goal.metric, new_target, goal.as_of, new_deadline, goal.currency
    )
    conn.execute(
        text(
            "UPDATE goals SET target = :t, deadline = :d, target_fact_id = :f, "
            "status = CASE WHEN status = 'draft' THEN 'draft' ELSE 'confirmed' END, "
            "updated_at = :now WHERE store_id = :s AND goal_id = :g"
        ),
        {"t": new_target, "d": new_deadline, "f": fact.id, "now": now, "s": store_id, "g": goal_id},
    )
    conn.execute(
        text(
            "UPDATE goal_plans SET status = 'superseded' WHERE store_id = :s AND goal_id = :g "
            "AND status IN ('proposed', 'accepted')"
        ),
        {"s": store_id, "g": goal_id},
    )
    append_audit(
        conn,
        store_id,
        actor="owner",
        action="goal.revised",
        payload={"goal_id": str(goal_id), "deadline": new_deadline.isoformat()},
        occurred_at=now,
    )
    return get(conn, store_id, goal_id)


def active_goals(conn: Connection, store_id: UUID) -> list[Goal]:
    return [g for g in list_goals(conn, store_id) if g.status in ("confirmed", "planned")]


def step_for(plan: PlanRecord, position: int) -> StepRecord:
    return next(s for s in plan.steps if s.position == position)


def as_step(record: StepRecord) -> Step:
    """A stored step back as a lever step (for re-simulation)."""
    return Step(
        lever=record.lever,
        kind=record.kind,
        day=0,
        actions=tuple(Action.model_validate(a) for a in record.actions),
        summary=record.summary,
        evidence=tuple(record.evidence),
    )
