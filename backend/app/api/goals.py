"""Goals (Task 6 B4, SPEC 17, ADR 0024): set a goal, confirm it, its feasibility, its plan,
accept the plan, follow its progress, revise it.

Every number is a fact (`facts`, by id); text cites facts and entities by reference. A goal is
a draft until the owner confirms the restated goal. Beyond 90 days a goal shows no point
probability (SPEC 17.2, rule 6): `probability` is null and `probability_range` and
`verdict_band` say what can be said. Accepting a plan proposes its decision steps whose day has
come as decisions: they follow the normal flow (approval, policy engine, execution).
`POST /ask` restates a goal question and returns its draft `goal_id`; `explain` confirms it and
answers with the feasibility or the plan, in the Ask answer contract.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from app.agent.ask import AskResult, explain_goal
from app.api.auth import PrincipalDep, StoreDep
from app.api.deps import EngineDep, ProviderDep
from app.api.views import FactOut, fact_out
from app.db import tenant_transaction
from app.facts.repository import get_facts
from app.goals import service
from app.goals.feasibility import Assessment
from app.goals.service import Goal, GoalError, PlanRecord, Progress

router = APIRouter(prefix="/api/v1/stores/{store_id}/goals", tags=["goals"])
GoalId = Annotated[UUID, Path()]
PlanId = Annotated[UUID, Path()]
STATUS = {
    "not_found": 404,
    "invalid_goal": 422,
    "not_confirmed": 409,
    "conflict": 409,
    "no_data": 409,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _fail(exc: GoalError) -> HTTPException:
    return HTTPException(
        status_code=STATUS.get(exc.code, 422), detail={"code": exc.code, "message": str(exc)}
    )


def _facts(conn: Connection, store_id: UUID, ids: list[int | None]) -> dict[str, FactOut]:
    found = get_facts(conn, store_id, [i for i in ids if i is not None])
    return {str(k): fact_out(v) for k, v in found.items()}


class GoalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Literal["net_profit", "contribution_margin", "revenue"]
    target: Decimal = Field(max_digits=18, decimal_places=4)
    deadline: date
    question: str | None = Field(default=None, max_length=2000)


class GoalOut(BaseModel):
    goal_id: UUID
    metric: str
    target_fact_id: int | None
    currency: str
    as_of: date  # the first day the goal counts
    deadline: date  # exclusive: the goal covers the days before it
    horizon_days: int
    status: str
    question: str | None
    created_at: datetime
    confirmed_at: datetime | None
    restatement: str
    facts: dict[str, FactOut]


def goal_out(conn: Connection, goal: Goal) -> GoalOut:
    return GoalOut(
        goal_id=goal.goal_id,
        metric=goal.metric,
        target_fact_id=goal.target_fact_id,
        currency=goal.currency,
        as_of=goal.as_of,
        deadline=goal.deadline,
        horizon_days=goal.horizon,
        status=goal.status,
        question=goal.question,
        created_at=goal.created_at,
        confirmed_at=goal.confirmed_at,
        restatement=service.restate(goal),
        facts=_facts(conn, goal.store_id, [goal.target_fact_id]),
    )


class FeasibilityOut(BaseModel):
    goal_id: UUID
    metric: str
    horizon_days: int
    verdict: str | None  # null beyond 90 days: see verdict_band
    verdict_band: list[str]
    probability: str | None  # null beyond 90 days
    probability_range: list[str]  # low, high
    probability_fact_id: int
    gap_fact_id: int
    forecast_fact_id: int  # the cumulative forecast at the deadline
    checkpoints: list[dict[str, Any]]  # beyond 90 days: day, date, forecast fact
    low_evidence: list[str]
    facts: dict[str, FactOut]


def feasibility_out(conn: Connection, goal: Goal, a: Assessment) -> FeasibilityOut:
    f = a.feasibility
    deadline = a.forecast[f.horizon]
    marks = [
        {
            "day": d,
            "date": (goal.as_of + timedelta(days=d)).isoformat(),
            "fact_id": a.forecast[d].id,
        }
        for d in f.checkpoints
    ]
    ids: list[int | None] = [
        a.probability.id,
        a.gap.id,
        deadline.id,
        goal.target_fact_id,
        *(a.forecast[d].id for d in f.checkpoints),
    ]
    return FeasibilityOut(
        goal_id=goal.goal_id,
        metric=goal.metric,
        horizon_days=f.horizon,
        verdict=f.verdict if f.shows_point else None,
        verdict_band=list(f.verdict_band),
        probability=None if f.shown_probability is None else f"{f.shown_probability:.4f}",
        probability_range=[f"{f.probability_range[0]:.4f}", f"{f.probability_range[2]:.4f}"],
        probability_fact_id=a.probability.id or 0,
        gap_fact_id=a.gap.id or 0,
        forecast_fact_id=deadline.id or 0,
        checkpoints=marks,
        low_evidence=list(f.low_evidence),
        facts=_facts(conn, goal.store_id, ids),
    )


class StepOut(BaseModel):
    step_id: UUID
    position: int
    lever: str
    kind: str  # decision, manual, experiment
    due_date: date
    actions: list[dict[str, Any]]
    summary: str
    evidence: list[int]
    effect_fact_id: int | None
    status: str
    decision_id: UUID | None


class PlanOut(BaseModel):
    plan_id: UUID
    goal_id: UUID
    status: str
    as_of: date
    detailed_days: int
    payload: dict[str, Any]
    steps: list[StepOut]
    facts: dict[str, FactOut]


def plan_out(conn: Connection, store_id: UUID, plan: PlanRecord) -> PlanOut:
    p = plan.payload
    ids: list[int | None] = [
        p.get("target_fact_id"),
        p.get("probability_without_fact_id"),
        p.get("probability_with_fact_id"),
        p.get("outcome_fact_id"),
        p.get("profit_change_fact_id"),
        *(m["fact_id"] for m in p.get("milestones", [])),
        *(s.effect_fact_id for s in plan.steps),
        *(i for s in plan.steps for i in s.evidence),
        *(i for e in p.get("experiments", []) for i in e["evidence"]),
    ]
    if p.get("alternatives"):
        ids += [p["alternatives"]["target_50_fact_id"], p["alternatives"]["target_70_fact_id"]]
    return PlanOut(
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        status=plan.status,
        as_of=plan.as_of,
        detailed_days=plan.days,
        payload=p,
        steps=[StepOut(**s.__dict__) for s in plan.steps],
        facts=_facts(conn, store_id, ids),
    )


class ProgressOut(BaseModel):
    progress_id: UUID
    plan_id: UUID | None
    kind: str  # weekly, reforecast
    as_of: date
    day: int
    actual_fact_id: int | None
    milestone_fact_id: int | None
    probability_fact_id: int | None
    status: str | None  # ahead, on_track, behind
    verdict: str | None
    adherence: dict[str, Any]
    revision_proposed: bool
    reason: str | None
    facts: dict[str, FactOut]


def progress_out(conn: Connection, store_id: UUID, p: Progress) -> ProgressOut:
    return ProgressOut(
        **{k: v for k, v in p.__dict__.items() if k != "goal_id"},
        facts=_facts(
            conn, store_id, [p.actual_fact_id, p.milestone_fact_id, p.probability_fact_id]
        ),
    )


class ReviseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)
    deadline: date | None = None


@router.post("", status_code=201, response_model=GoalOut)
def post_goal(store_id: StoreDep, body: GoalIn, engine: EngineDep) -> GoalOut:
    """Set a goal: a draft, restated in plain words, until the owner confirms it."""
    with tenant_transaction(engine, store_id) as conn:
        try:
            goal = service.create(
                conn,
                store_id,
                body.metric,
                body.target,
                body.deadline,
                now=_now(),
                question=body.question,
            )
        except GoalError as exc:
            raise _fail(exc) from exc
        return goal_out(conn, goal)


@router.get("", response_model=list[GoalOut])
def get_goals(store_id: StoreDep, engine: EngineDep) -> list[GoalOut]:
    with tenant_transaction(engine, store_id) as conn:
        return [goal_out(conn, g) for g in service.list_goals(conn, store_id)]


@router.get("/{goal_id}", response_model=GoalOut)
def get_goal(store_id: StoreDep, goal_id: GoalId, engine: EngineDep) -> GoalOut:
    with tenant_transaction(engine, store_id) as conn:
        try:
            return goal_out(conn, service.get(conn, store_id, goal_id))
        except GoalError as exc:
            raise _fail(exc) from exc


@router.post("/{goal_id}/confirm", response_model=FeasibilityOut)
def post_confirm(store_id: StoreDep, goal_id: GoalId, engine: EngineDep) -> FeasibilityOut:
    """Confirm the restated goal: its feasibility, computed by code."""
    with tenant_transaction(engine, store_id) as conn:
        try:
            assessment = service.confirm(conn, store_id, goal_id, now=_now())
            return feasibility_out(conn, service.get(conn, store_id, goal_id), assessment)
        except GoalError as exc:
            raise _fail(exc) from exc


@router.get("/{goal_id}/feasibility", response_model=FeasibilityOut)
def get_feasibility(store_id: StoreDep, goal_id: GoalId, engine: EngineDep) -> FeasibilityOut:
    with tenant_transaction(engine, store_id) as conn:
        try:
            goal = service.get(conn, store_id, goal_id)
            if goal.status == "draft":
                raise GoalError("not_confirmed", "confirm the goal first")
            return feasibility_out(conn, goal, service.feasibility(conn, goal))
        except GoalError as exc:
            raise _fail(exc) from exc


@router.post("/{goal_id}/plans", status_code=201, response_model=PlanOut)
def post_plan(store_id: StoreDep, goal_id: GoalId, engine: EngineDep) -> PlanOut:
    """Propose a plan from today's data (the first 90 days in detail)."""
    with tenant_transaction(engine, store_id) as conn:
        try:
            return plan_out(conn, store_id, service.make_plan(conn, store_id, goal_id, now=_now()))
        except GoalError as exc:
            raise _fail(exc) from exc


@router.get("/{goal_id}/plans", response_model=list[PlanOut])
def get_plans(store_id: StoreDep, goal_id: GoalId, engine: EngineDep) -> list[PlanOut]:
    with tenant_transaction(engine, store_id) as conn:
        try:
            service.get(conn, store_id, goal_id)
        except GoalError as exc:
            raise _fail(exc) from exc
        return [plan_out(conn, store_id, p) for p in service.plans(conn, store_id, goal_id)]


@router.post("/{goal_id}/plans/{plan_id}/accept", response_model=PlanOut)
def post_accept(
    store_id: StoreDep,
    goal_id: GoalId,
    plan_id: PlanId,
    engine: EngineDep,
    principal: PrincipalDep,
) -> PlanOut:
    """Accept a proposed plan; its decision steps due now become proposed decisions."""
    with tenant_transaction(engine, store_id) as conn:
        try:
            plan = service.get_plan(conn, store_id, plan_id)
            if plan.goal_id != goal_id:
                raise GoalError("not_found", "no such plan")
            accepted = service.accept(conn, store_id, plan_id, now=_now(), actor=principal.label)
            return plan_out(conn, store_id, accepted)
        except GoalError as exc:
            raise _fail(exc) from exc


@router.get("/{goal_id}/progress", response_model=list[ProgressOut])
def get_progress(store_id: StoreDep, goal_id: GoalId, engine: EngineDep) -> list[ProgressOut]:
    with tenant_transaction(engine, store_id) as conn:
        try:
            service.get(conn, store_id, goal_id)
        except GoalError as exc:
            raise _fail(exc) from exc
        return [progress_out(conn, store_id, p) for p in service.progress(conn, store_id, goal_id)]


@router.post("/{goal_id}/revise", response_model=GoalOut)
def post_revise(store_id: StoreDep, goal_id: GoalId, body: ReviseIn, engine: EngineDep) -> GoalOut:
    """A new target or deadline: the goal is confirmed again and its plans are superseded."""
    with tenant_transaction(engine, store_id) as conn:
        try:
            goal = service.revise(
                conn, store_id, goal_id, now=_now(), target=body.target, deadline=body.deadline
            )
        except GoalError as exc:
            raise _fail(exc) from exc
        return goal_out(conn, goal)


class ExplainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what: Literal["feasibility", "plan"] = "feasibility"


@router.post("/{goal_id}/explain", response_model=AskResult)
def post_explain(
    store_id: StoreDep, goal_id: GoalId, body: ExplainIn, engine: EngineDep, provider: ProviderDep
) -> AskResult:
    """Confirm the goal and answer with its feasibility, or its plan (proposed, as
    `POST /plans` does), in the Ask answer contract. Code decides every number, the verdict
    and every step; the model explains, or code writes the answer from the same facts."""
    try:
        return explain_goal(engine, store_id, goal_id, provider, what=body.what)
    except GoalError as exc:
        raise _fail(exc) from exc
