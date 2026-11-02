"""What a fact is, in words: its formula's technical expression and a plain explanation, whether
it is a change (shown signed: "+$613"), and how an estimate was made.

Registry formulas carry their own words (`Formula.explanation`, part of the version). Facts made
outside the registry (the store twin, goals, profit drivers, the agent's derived numbers) are
named by family, `<family>.<metric or part>`; their words are here, one entry per family.
"""

from dataclasses import dataclass

from app.facts.formulas import REGISTRY
from app.facts.registry import UnknownFormulaError


@dataclass(frozen=True)
class Described:
    formula_id: str
    expression: str  # technical
    explanation: str  # plain words, for the owner
    inputs: tuple[str, ...] = ()
    change: bool = False  # a difference between two states: shown with its sign
    version: int | None = None  # a registry formula's version (the words belong to it)


# The parts of a family's id, in words ("net_profit" -> "net profit").
WORDS = {
    "net_profit": "net profit",
    "contribution_margin": "contribution margin",
    "contribution_after_ads": "contribution after ads",
    "ad_spend": "ad spend",
    "units": "units sold",
    "unit_cost": "unit cost",
    "fixed_costs": "fixed costs",
    "mix": "product mix",
}


def _words(part: str) -> str:
    return WORDS.get(part, part.replace("_", " "))


@dataclass(frozen=True)
class Family:
    expression: str  # `{x}` is the id's last part, in words
    explanation: str
    change: bool = False


# Longest prefix first: `twin.change.` before `twin.`.
FAMILIES: dict[str, Family] = {
    "twin.change.": Family(
        "P10/P50/P90 over Monte Carlo draws of Σ {x} with the action − Σ {x} without, draw by draw",
        "How much {x} changes over the horizon if you take the action, compared with doing "
        "nothing, as the store twin simulates both.",
        change=True,
    ),
    "twin.do_nothing.": Family(
        "P10/P50/P90 over Monte Carlo draws of Σ {x} over the horizon, without any action",
        "Where {x} goes over the horizon if nothing changes, as the store twin simulates it.",
    ),
    "twin.": Family(
        "P10/P50/P90 over Monte Carlo draws of Σ {x} over the horizon, with the action",
        "Where {x} goes over the horizon if you take the action, as the store twin simulates it.",
    ),
    "decision.do_nothing.": Family(
        "0: doing nothing compared with itself",
        "Doing nothing changes nothing: compared with doing nothing, the change in {x} is zero.",
        change=True,
    ),
    "profit_driver.": Family(
        "exact two-level Shapley contribution of the driver to the net profit change",
        "How much {x} moved net profit between the two periods; the drivers add up to the whole "
        "change.",
        change=True,
    ),
    "outcome.effect.": Family(
        "effect on {x} over the observation window, by synthetic control, calibrated interval",
        "What the action changed in {x}, measured once it took effect, against a synthetic copy "
        "built from the parts of the store it did not touch.",
        change=True,
    ),
    "goal.target.": Family(
        "the owner's target for {x} over the goal's days",
        "Your target: {x} over the goal's days.",
    ),
    "goal.forecast.": Family(
        "P10/P50/P90 of Σ {x} over the goal's days, recent trend with a block bootstrap",
        "Where {x} is heading over the goal's days without a plan: your recent trend, resampled "
        "from your history.",
    ),
    "goal.probability.": Family(
        "share of the forecast's draws reaching the target, with a bootstrap range",
        "The chance of reaching your target without a plan.",
    ),
    "goal.gap.": Family(
        "target − the forecast's P90, P50 and P10",
        "How far the forecast falls short of your target (below zero: ahead of it).",
    ),
    "goal.milestone.": Family(
        "P10/P50/P90 of cumulative {x} at the milestone, with the plan",
        "Where {x} should be by this point of the plan.",
    ),
    "goal.plan.baseline_probability.": Family(
        "share of the baseline forecast's draws reaching the target",
        "The chance of reaching your target without the plan.",
    ),
    "goal.plan.probability.": Family(
        "share of the planned draws reaching the target",
        "The chance of reaching your target with the plan.",
    ),
    "goal.plan.outcome.": Family(
        "P10/P50/P90 of Σ {x} over the goal's days, with the plan",
        "Where {x} is heading over the goal's days with the plan.",
    ),
    "goal.plan.profit_change.": Family(
        "Σ of the plan's steps' simulated changes in net profit",
        "How much the plan adds to net profit over its days.",
        change=True,
    ),
    "goal.step.": Family(
        "simulated change in net profit from the step ({x})",
        "What this step of the plan ({x}) adds to net profit.",
        change=True,
    ),
    "goal.alternative.target_50.": Family(
        "the forecast's P50 of Σ {x} with the plan",
        "A target you would reach about one time in two, with the plan.",
    ),
    "goal.alternative.target_70.": Family(
        "the forecast's P30 of Σ {x} with the plan",
        "A target you would reach about seven times in ten, with the plan.",
    ),
}
EXACT: dict[str, Family] = {
    "expected_monthly_impact": Family(
        "the incident's Shapley contributions over the current window, scaled to 30 days; "
        "P10/P50/P90 by a seeded 7-day block bootstrap",
        "What this problem changes in profit a month: its share of the change over the current "
        "window, scaled to 30 days.",
        change=True,
    ),
    "profit_delta": Family(
        "net_profit(current) − net_profit(baseline)",
        "How much net profit changed between the two periods.",
        change=True,
    ),
    "briefing.money_at_stake": Family(
        "Σ of the open incidents' monthly impacts, quantile by quantile",
        "What the open problems could cost a month, all together.",
    ),
    "briefing.monthly_loss": Family(
        "−expected_monthly_impact",
        "What this problem costs a month.",
    ),
    "derived.compute": Family(
        "arithmetic over facts requested by the agent (references only)",
        "A calculation over the numbers it is built from, made by code for an answer.",
    ),
    "derived.sum": Family("sum of the parts", "The parts it is built from, added up."),
    "derived.mean": Family(
        "mean of the defined days of a daily series",
        "The average of the days that have data.",
    ),
    "derived.difference": Family(
        "last day minus first day of a daily series",
        "The last day minus the first day.",
        change=True,
    ),
    "derived.gap": Family(
        "whole minus the sum of its parts",
        "What the parts leave out of the whole.",
    ),
    "derived.share": Family(
        "numerator divided by denominator",
        "One number divided by the other.",
    ),
    "derived.daily_slope": Family(
        "OLS slope of a daily series per day, normal 80% interval",
        "How much the series rises or falls per day, on average.",
        change=True,
    ),
}


def describe(formula_id: str) -> Described | None:
    """The words of a formula, or None for a family this catalogue does not know."""
    try:
        f = REGISTRY.get(formula_id)
        return Described(f.formula_id, f.description, f.explanation, f.inputs, version=f.version)
    except UnknownFormulaError:
        pass
    family = EXACT.get(formula_id)
    if family is not None:
        return Described(formula_id, family.expression, family.explanation, (), family.change)
    for prefix, family in FAMILIES.items():
        if formula_id.startswith(prefix):
            x = _words(formula_id.removeprefix(prefix))
            return Described(
                formula_id,
                family.expression.format(x=x),
                family.explanation.format(x=x),
                (),
                family.change,
            )
    return None


def is_change(formula_id: str) -> bool:
    found = describe(formula_id)
    return found is not None and found.change


# How estimates are made, in words (method ids are versioned: `<method>_v<n>`).
METHODS: dict[str, str] = {
    "twin_monte_carlo_v1": "simulated by the store twin",
    "synthetic_control_v2": "measured against a synthetic control",
    "block_bootstrap_shapley_v1": "resampled from your history",
    "goal_trend_block_bootstrap_v1": "your recent trend, resampled from your history",
    "goal_plan_greedy_v1": "simulated with the plan's steps",
    "goal_parameter_v1": "set from your goal",
    "ols_daily_normal_v1": "fitted to the daily trend",
    "sum_of_quantiles_v1": "added up from the ranges it is built from",
    "shapley_v1": "split between the drivers (Shapley values)",
}


def method_text(method: str | None) -> str | None:
    """How an estimate was made, in words; a derived method (`negated:<method>`) is its base."""
    if not method:
        return None
    base = method.rsplit(":", 1)[-1]
    return METHODS.get(base, base.removesuffix("_v1").replace("_", " "))
