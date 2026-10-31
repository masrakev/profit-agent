"""Plans: levers selected and sequenced to raise a goal's probability (Task 6 B2, SPEC 17.3,
ADR 0024).

The search is greedy with re-simulation. Starting from no step, each round tries every
remaining lever step that touches no campaign already changed (one change per campaign), and
simulates the twin with all the chosen actions together (so steps that interact are judged
together); the step that raises the probability of reaching the target most is kept, or, when
no step moves the probability (a goal far out of reach or already sure), the one that raises
the median outcome most. A step is only kept if the plan's P10 stays within the materiality
floor (scaled to the plan's days) of the baseline's P10: a plan may not risk much more than it
can gain. The search stops when no step improves the plan, or after five steps.

The twin assumes the store's usual reorders (`app.goals.levers.usual_supply`) in every plan
simulation, as the baseline forecast does. Plans are detailed and simulated for the
first 90 days (SPEC 17.2, rule 6): a goal beyond them
counts only that period's effect. The probability with the plan adds the twin's simulated
change, draw by draw, to the baseline forecast's calibrated paths. Weekly milestones are the
cumulative metric with the plan, each week simulated on its own. Experiments are listed, never
counted. When the goal stays `unlikely` with the plan: the targets reachable with 50% and 70%
probability, the deadline that would make the target `possible`, and the experiments.

Plans never execute anything: their decision steps become decisions in the normal flow when
their day comes (policy engine, the owner's approval, execution, measured outcome).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from app.goals.feasibility import POINT_HORIZON, RESAMPLES, probability_range, verdict
from app.goals.forecast import FloatArray
from app.goals.levers import DECISION, EXPERIMENT, Step
from app.twin import Action, Scenario, TwinModel, change_draws

PLAN_DAYS = POINT_HORIZON  # plans are detailed and simulated for the first 90 days
MAX_STEPS = 5
WEEK = 7
POSSIBLE = 0.40
TWIN_METRIC = {m: m for m in ("net_profit", "contribution_margin", "revenue")}
ASSUMPTIONS = (
    "campaigns keep spending at their recent daily level, scaled by any budget change, and "
    "their sales follow the response curves fitted on the last weeks",
    "a reorder arrives after the supplier's lead time and restores the supply from then on",
    "the store's own trend, weekday pattern and noise follow the baseline forecast",
    "steps run only after the owner approves them; a step that is not approved changes nothing",
    "experiments are never counted until they are measured",
)


def plan_days(horizon: int) -> int:
    return max(WEEK, min(horizon, PLAN_DAYS))


@dataclass(frozen=True)
class Effect:
    draws: FloatArray  # the simulated change in the metric, one value per twin draw
    profit: FloatArray  # the same steps' change in net profit

    def range(self) -> tuple[float, float, float]:
        q10, q50, q90 = np.percentile(self.draws, [10, 50, 90])
        return float(q10), float(q50), float(q90)


def effect(
    model: TwinModel,
    actions: tuple[Action, ...],
    metric: str,
    days: int,
    background: tuple[Action, ...] = (),
) -> Effect:
    if not actions:
        zero = np.zeros(1)
        return Effect(zero, zero)
    draws = change_draws(
        model,
        Scenario(actions=actions, horizon_days=days),
        background=background,
    )
    if not draws:
        zero = np.zeros(1)
        return Effect(zero, zero)
    return Effect(draws[TWIN_METRIC[metric]], draws["net_profit"])


def combine(baseline: FloatArray, change: FloatArray) -> FloatArray:
    """The baseline's draws plus the change, paired draw by draw (cycling the shorter)."""
    idx = np.arange(len(baseline)) % len(change)
    out: FloatArray = baseline + change[idx]
    return out


def reach(values: FloatArray, target: float) -> float:
    return float((values >= target).mean())


def quantile_range(values: FloatArray, q: float, seed: int) -> tuple[float, float, float]:
    """The `q` percentile of `values`, with a bootstrap interval (P10-P90) over the draws."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(RESAMPLES, len(values)))
    low, high = np.percentile(np.percentile(values[idx], q, axis=1), [10, 90])
    mid = float(np.percentile(values, q))
    return (min(float(low), mid), mid, max(float(high), mid))


@dataclass(frozen=True)
class Choice:
    steps: tuple[Step, ...]
    effect: Effect
    probability: float
    median: float
    low: float  # the outcome's P10


def _choice(
    steps: tuple[Step, ...],
    model: TwinModel,
    baseline: FloatArray,
    metric: str,
    days: int,
    t: float,
    background: tuple[Action, ...],
) -> Choice:
    e = effect(model, tuple(a for s in steps for a in s.actions), metric, days, background)
    outcome = combine(baseline, e.draws)
    return Choice(
        steps=steps,
        effect=e,
        probability=reach(outcome, t),
        median=float(np.median(outcome)),
        low=float(np.percentile(outcome, 10)),
    )


def search(
    model: TwinModel,
    baseline: FloatArray,
    candidates: list[Step],
    *,
    metric: str,
    target: float,
    days: int,
    floor: float,
    background: tuple[Action, ...] = (),
) -> Choice:
    """Greedy selection with re-simulation (module docstring). `baseline`: the forecast's
    calibrated draws at the deadline; `floor`: how much lower the plan's P10 may be;
    `background`: the store's usual reorders, in every simulation."""
    pool = [s for s in candidates if s.kind != EXPERIMENT and s.actions]
    best = _choice((), model, baseline, metric, days, target, background)
    limit = best.low - floor
    while len(best.steps) < MAX_STEPS:
        used = {c for s in best.steps for c in s.campaigns}
        tried = [
            _choice((*best.steps, s), model, baseline, metric, days, target, background)
            for s in pool
            if s not in best.steps and not (s.campaigns & used)
        ]
        allowed = [c for c in tried if c.low >= limit]
        better = [
            c
            for c in allowed
            if c.probability > best.probability
            or (c.probability == best.probability and c.median > best.median)
        ]
        if not better:
            break
        best = max(better, key=lambda c: (c.probability, c.median))
    return best


@dataclass(frozen=True)
class Milestone:
    day: int
    date: date
    range: tuple[float, float, float]  # cumulative P10, P50, P90 with the plan


@dataclass(frozen=True)
class Alternatives:
    target_50: tuple[float, float, float]  # reached with 50% probability, with the plan
    target_70: tuple[float, float, float]  # with 70% (each: a bootstrap of the quantile)
    deadline_days: int | None  # the first horizon making the target possible; None in 6 months


@dataclass(frozen=True)
class Plan:
    metric: str
    target: float
    as_of: date
    horizon: int
    days: int  # the detailed part: the first 90 days at most
    steps: tuple[tuple[Step, tuple[float, float, float]], ...]  # each with its own effect
    experiments: tuple[Step, ...]
    milestones: tuple[Milestone, ...]
    probability_without: tuple[float, float, float]  # low, point, high
    probability_with: tuple[float, float, float]
    outcome: tuple[float, float, float]  # at the deadline, with the plan
    profit_change: tuple[float, float, float]  # the plan's effect on net profit
    alternatives: Alternatives | None
    assumptions: tuple[str, ...] = field(default=ASSUMPTIONS)

    @property
    def verdict_with(self) -> str:
        return verdict(self.probability_with[1])

    @property
    def lowers_profit(self) -> bool:
        """A revenue plan that would lower net profit (said first, SPEC 17.1)."""
        return self.metric == "revenue" and self.profit_change[1] < 0

    def dated(self, step: Step) -> date:
        return self.as_of + timedelta(days=step.day)


def build(
    model: TwinModel,
    paths: FloatArray,
    candidates: list[Step],
    *,
    metric: str,
    target: float,
    as_of: date,
    floor_monthly: Decimal,
    extended: FloatArray | None = None,
    background: tuple[Action, ...] = (),
) -> Plan:
    """The plan for a goal whose baseline calibrated cumulative paths are `paths` (draws x
    horizon days). `extended`: the same forecast to six months, for the alternative deadline."""
    horizon = paths.shape[1]
    days = plan_days(horizon)
    floor = float(floor_monthly) * days / 30
    final = paths[:, -1]
    best = search(
        model,
        final,
        candidates,
        metric=metric,
        target=target,
        days=days,
        floor=floor,
        background=background,
    )
    steps = tuple(
        (s, effect(model, s.actions, metric, days, background).range()) for s in best.steps
    )
    actions = tuple(a for s in best.steps for a in s.actions)
    milestones = []
    for day in (*range(WEEK, days + 1, WEEK), *(() if days % WEEK == 0 else (days,))):
        if day > horizon:
            break
        cum = combine(paths[:, day - 1], effect(model, actions, metric, day, background).draws)
        q10, q50, q90 = np.percentile(cum, [10, 50, 90])
        milestones.append(
            Milestone(day, as_of + timedelta(days=day), (float(q10), float(q50), float(q90)))
        )
    outcome = combine(final, best.effect.draws)
    seed = int(abs(target) * 100) % (2**32)
    with_plan = probability_range(outcome, target, horizon, seed)
    alternatives = None
    if verdict(with_plan[1]) == "unlikely":
        deadline = None
        if extended is not None:
            for h in range(horizon + 1, extended.shape[1] + 1):
                if reach(combine(extended[:, h - 1], best.effect.draws), target) >= POSSIBLE:
                    deadline = h
                    break
        alternatives = Alternatives(
            target_50=quantile_range(outcome, 50, seed),
            target_70=quantile_range(outcome, 30, seed),
            deadline_days=deadline,
        )
    o10, o50, o90 = np.percentile(outcome, [10, 50, 90])
    p10, p50, p90 = np.percentile(best.effect.profit, [10, 50, 90])
    return Plan(
        metric=metric,
        target=target,
        as_of=as_of,
        horizon=horizon,
        days=days,
        steps=steps,
        experiments=tuple(s for s in candidates if s.kind == EXPERIMENT),
        milestones=tuple(milestones),
        probability_without=probability_range(final, target, horizon, seed),
        probability_with=with_plan,
        outcome=(float(o10), float(o50), float(o90)),
        profit_change=(float(p10), float(p50), float(p90)),
        alternatives=alternatives,
    )


def decision_steps(plan: Plan) -> list[Step]:
    """The steps that become decisions when their day comes."""
    return [s for s, _ in plan.steps if s.kind == DECISION]
