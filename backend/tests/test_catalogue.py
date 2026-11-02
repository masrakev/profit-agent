"""Every fact can be explained: registry formulas in their version, derived families by name."""

import pytest

from app.facts.catalogue import EXACT, FAMILIES, describe, fact_name, is_change, method_text
from app.facts.formulas import REGISTRY


def test_every_registry_formula_explains_itself() -> None:
    for formula in REGISTRY:
        described = describe(formula.formula_id)
        assert described is not None
        assert described.explanation.endswith(".")
        assert described.expression == formula.description
        assert described.version == formula.version
        assert not described.change  # registry formulas are levels, not changes
    assert "fixed costs" in REGISTRY.get("net_profit").explanation


@pytest.mark.parametrize(
    ("formula_id", "words", "change"),
    [
        ("twin.change.net_profit", "How much net profit changes", True),
        ("twin.do_nothing.units", "Where units sold goes", False),
        ("twin.ad_spend", "Where ad spend goes", False),
        ("twin.parameter.horizon_days", "its horizon days", False),
        ("decision.do_nothing.net_profit", "the change in net profit is zero", True),
        ("profit_driver.unit_cost", "How much unit cost moved net profit", True),
        ("outcome.effect.contribution_after_ads", "changed in contribution after ads", True),
        ("goal.forecast.net_profit", "Where net profit is heading", False),
        ("goal.plan.probability.net_profit", "with the plan", False),
        ("goal.step.scale_profitable", "(scale profitable)", True),
        ("goal.alternative.target_70.net_profit", "seven times in ten", False),
        ("expected_monthly_impact", "a month", True),
        ("briefing.monthly_loss", "costs a month", False),
        ("derived.daily_slope", "per day", True),
        ("derived.compute", "made by code", False),
    ],
)
def test_derived_families_are_described(formula_id: str, words: str, change: bool) -> None:
    described = describe(formula_id)
    assert described is not None
    assert words in described.explanation
    assert described.version is None
    assert is_change(formula_id) is change


@pytest.mark.parametrize(
    ("formula_id", "name"),
    [
        ("net_profit", "Net profit"),
        ("cogs", "Cost of goods"),
        ("twin.change.net_profit", "Change in net profit"),
        ("twin.do_nothing.units", "Projected units sold if nothing changes"),
        ("decision.do_nothing.net_profit", "Change in net profit from doing nothing"),
        ("profit_driver.unit_cost", "Effect of unit cost on net profit"),
        ("expected_monthly_impact", "Monthly impact"),
        ("derived.sum", "Sum"),
        ("nobody.knows_this", "Knows this"),
    ],
)
def test_every_fact_has_a_name(formula_id: str, name: str) -> None:
    assert fact_name(formula_id) == name


def test_unknown_families_say_nothing() -> None:
    assert describe("nobody.knows") is None
    assert not is_change("nobody.knows")


def test_families_are_matched_longest_prefix_first() -> None:
    prefixes = list(FAMILIES)
    for i, prefix in enumerate(prefixes):
        assert not any(prefix.startswith(earlier) for earlier in prefixes[:i]), prefix
    assert not set(EXACT) & {f.formula_id for f in REGISTRY}


def test_methods_are_told_in_words() -> None:
    assert method_text("twin_monte_carlo_v1") == "simulated by the store twin"
    assert method_text("negated:block_bootstrap_shapley_v1") == "resampled from your history"
    assert method_text("twin_monte_carlo_v1;calibration v1") == "simulated by the store twin"
    assert method_text("brand_new_v1") == "brand new"
    assert method_text("twin_monte_carlo_v1;calibration v1", 1000) == (
        "simulated 1,000 times by the store twin"
    )
    assert method_text("synthetic_control_v2", 500) == "measured against a synthetic control"
    assert method_text(None) is None
    assert method_text("") is None
