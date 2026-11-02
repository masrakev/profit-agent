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
    name: str  # what the number is, in a few words ("Change in net profit")
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
    name: str  # `{x}` is the id's last part, in words
    expression: str
    explanation: str
    change: bool = False


# Registry formulas are named after their id ("net_profit" -> "Net profit"), except these.
NAMES = {
    "cogs": "Cost of goods",
    "promoted_cogs": "Cost of goods of the promoted products",
    "promoted_revenue": "Revenue of the promoted products",
    "promoted_fees": "Fees of the promoted products",
    "promoted_refunds": "Refunds of the promoted products",
    "promoted_contribution_margin": "Contribution margin of the promoted products",
    "roas": "Return on ad spend",
    "poas": "Profit on ad spend",
    "cpa": "Cost per purchase",
    "mer": "Marketing efficiency ratio",
    "supplier_lead_time_days": "Supplier lead time",
    "inventory_cover_days": "Days of stock",
}


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


# Longest prefix first: `twin.change.` before `twin.`.
FAMILIES: dict[str, Family] = {
    "twin.change.": Family(
        "Change in {x}",
        "P10/P50/P90 over Monte Carlo draws of Σ {x} with the action − Σ {x} without, draw by draw",
        "How much {x} changes over the horizon if you take the action, compared with doing "
        "nothing, as the store twin simulates both.",
        change=True,
    ),
    "twin.parameter.": Family(
        "Action setting: {x}",
        "a parameter of the simulated scenario: {x}",
        "A setting of the action the store twin simulates: its {x}.",
    ),
    "twin.do_nothing.": Family(
        "Projected {x} if nothing changes",
        "P10/P50/P90 over Monte Carlo draws of Σ {x} over the horizon, without any action",
        "Where {x} goes over the horizon if nothing changes, as the store twin simulates it.",
    ),
    "twin.": Family(
        "Projected {x} with the action",
        "P10/P50/P90 over Monte Carlo draws of Σ {x} over the horizon, with the action",
        "Where {x} goes over the horizon if you take the action, as the store twin simulates it.",
    ),
    "decision.do_nothing.": Family(
        "Change in {x} from doing nothing",
        "0: doing nothing compared with itself",
        "Doing nothing changes nothing: compared with doing nothing, the change in {x} is zero.",
        change=True,
    ),
    "profit_driver.": Family(
        "Effect of {x} on net profit",
        "exact two-level Shapley contribution of the driver to the net profit change",
        "How much {x} moved net profit between the two periods; the drivers add up to the whole "
        "change.",
        change=True,
    ),
    "outcome.effect.": Family(
        "Measured effect on {x}",
        "effect on {x} over the observation window, by synthetic control, calibrated interval",
        "What the action changed in {x}, measured once it took effect, against a synthetic copy "
        "built from the parts of the store it did not touch.",
        change=True,
    ),
    "goal.target.": Family(
        "Target {x}",
        "the owner's target for {x} over the goal's days",
        "Your target: {x} over the goal's days.",
    ),
    "goal.forecast.": Family(
        "Forecast {x}",
        "P10/P50/P90 of Σ {x} over the goal's days, recent trend with a block bootstrap",
        "Where {x} is heading over the goal's days without a plan: your recent trend, resampled "
        "from your history.",
    ),
    "goal.probability.": Family(
        "Chance of reaching the target",
        "share of the forecast's draws reaching the target, with a bootstrap range",
        "The chance of reaching your target without a plan.",
    ),
    "goal.gap.": Family(
        "Gap to the target",
        "target − the forecast's P90, P50 and P10",
        "How far the forecast falls short of your target (below zero: ahead of it).",
    ),
    "goal.milestone.": Family(
        "Milestone {x}",
        "P10/P50/P90 of cumulative {x} at the milestone, with the plan",
        "Where {x} should be by this point of the plan.",
    ),
    "goal.plan.baseline_probability.": Family(
        "Chance without the plan",
        "share of the baseline forecast's draws reaching the target",
        "The chance of reaching your target without the plan.",
    ),
    "goal.plan.probability.": Family(
        "Chance with the plan",
        "share of the planned draws reaching the target",
        "The chance of reaching your target with the plan.",
    ),
    "goal.plan.outcome.": Family(
        "Projected {x} with the plan",
        "P10/P50/P90 of Σ {x} over the goal's days, with the plan",
        "Where {x} is heading over the goal's days with the plan.",
    ),
    "goal.plan.profit_change.": Family(
        "Profit added by the plan",
        "Σ of the plan's steps' simulated changes in net profit",
        "How much the plan adds to net profit over its days.",
        change=True,
    ),
    "goal.step.": Family(
        "Profit added by this step",
        "simulated change in net profit from the step ({x})",
        "What this step of the plan ({x}) adds to net profit.",
        change=True,
    ),
    "goal.alternative.target_50.": Family(
        "Target reached one time in two",
        "the forecast's P50 of Σ {x} with the plan",
        "A target you would reach about one time in two, with the plan.",
    ),
    "goal.alternative.target_70.": Family(
        "Target reached seven times in ten",
        "the forecast's P30 of Σ {x} with the plan",
        "A target you would reach about seven times in ten, with the plan.",
    ),
}
EXACT: dict[str, Family] = {
    "expected_monthly_impact": Family(
        "Monthly impact",
        "the incident's Shapley contributions over the current window, scaled to 30 days; "
        "P10/P50/P90 by a seeded 7-day block bootstrap",
        "What this problem changes in profit a month: its share of the change over the current "
        "window, scaled to 30 days.",
        change=True,
    ),
    "profit_delta": Family(
        "Change in net profit",
        "net_profit(current) − net_profit(baseline)",
        "How much net profit changed between the two periods.",
        change=True,
    ),
    "briefing.money_at_stake": Family(
        "Money at stake",
        "Σ of the open incidents' monthly impacts, quantile by quantile",
        "What the open problems could cost a month, all together.",
    ),
    "briefing.monthly_loss": Family(
        "Monthly loss",
        "−expected_monthly_impact",
        "What this problem costs a month.",
    ),
    "derived.compute": Family(
        "Calculation",
        "arithmetic over facts requested by the agent (references only)",
        "A calculation over the numbers it is built from, made by code for an answer.",
    ),
    "derived.sum": Family("Sum", "sum of the parts", "The parts it is built from, added up."),
    "derived.mean": Family(
        "Daily average",
        "mean of the defined days of a daily series",
        "The average of the days that have data.",
    ),
    "derived.difference": Family(
        "Difference",
        "last day minus first day of a daily series",
        "The last day minus the first day.",
        change=True,
    ),
    "derived.gap": Family(
        "Remainder",
        "whole minus the sum of its parts",
        "What the parts leave out of the whole.",
    ),
    "derived.share": Family(
        "Share",
        "numerator divided by denominator",
        "One number divided by the other.",
    ),
    "derived.daily_slope": Family(
        "Daily trend",
        "OLS slope of a daily series per day, normal 80% interval",
        "How much the series rises or falls per day, on average.",
        change=True,
    ),
}


def describe(formula_id: str) -> Described | None:
    """The words of a formula, or None for a family this catalogue does not know."""
    try:
        f = REGISTRY.get(formula_id)
        name = NAMES.get(formula_id, _capitalized(formula_id.replace("_", " ")))
        return Described(
            f.formula_id, name, f.description, f.explanation, f.inputs, version=f.version
        )
    except UnknownFormulaError:
        pass
    family = EXACT.get(formula_id)
    if family is not None:
        return Described(
            formula_id, family.name, family.expression, family.explanation, (), family.change
        )
    for prefix, family in FAMILIES.items():
        if formula_id.startswith(prefix):
            x = _words(formula_id.removeprefix(prefix))
            return Described(
                formula_id,
                _capitalized(family.name.format(x=x)),
                family.expression.format(x=x),
                family.explanation.format(x=x),
                (),
                family.change,
            )
    return None


def fact_name(formula_id: str) -> str:
    """What a fact is, in a few words; an unknown family is named after its id."""
    found = describe(formula_id)
    if found is not None:
        return found.name
    return _capitalized(formula_id.rsplit(".", 1)[-1].replace("_", " "))


def is_change(formula_id: str) -> bool:
    found = describe(formula_id)
    return found is not None and found.change


# How estimates are made, in words (method ids are versioned: `<method>_v<n>`): without and
# with the number of draws (`{n}`).
METHODS: dict[str, tuple[str, str]] = {
    "twin_monte_carlo_v1": (
        "simulated by the store twin",
        "simulated {n} times by the store twin",
    ),
    "synthetic_control_v2": (
        "measured against a synthetic control",
        "measured against a synthetic control",
    ),
    "block_bootstrap_shapley_v1": (
        "resampled from your history",
        "resampled {n} times from your history",
    ),
    "goal_trend_block_bootstrap_v1": (
        "your recent trend, resampled from your history",
        "your recent trend, resampled {n} times from your history",
    ),
    "goal_plan_greedy_v1": (
        "simulated with the plan's steps",
        "simulated {n} times with the plan's steps",
    ),
    "goal_parameter_v1": ("set from your goal", "set from your goal"),
    "ols_daily_normal_v1": ("fitted to the daily trend", "fitted to the daily trend"),
    "sum_of_quantiles_v1": (
        "added up from the ranges it is built from",
        "added up from the ranges it is built from",
    ),
    "shapley_v1": (
        "split between the drivers (Shapley values)",
        "split between the drivers (Shapley values)",
    ),
}


def method_text(method: str | None, draws: int | None = None) -> str | None:
    """How an estimate was made, in words, with its number of draws when it has some. A derived
    method names its operation first (`negated:<method>`); a method may add its settings after a
    semicolon (`twin_monte_carlo_v1;calibration v1`)."""
    if not method:
        return None
    base = method.rsplit(":", 1)[-1].split(";", 1)[0]
    plain, counted = METHODS.get(base, (base.removesuffix("_v1").replace("_", " "),) * 2)
    return counted.format(n=f"{draws:,}") if draws else plain
