"""Citation completeness: a named metric needs a cited fact of that metric."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.agent.ask import QuestionType, contract_checks
from app.agent.citations import citation_check, citation_repair, covers, named_metrics, resolve
from app.agent.contracts import Answer
from app.facts.model import Fact, FactKind, FactStatus, Period, Scope, Unit

FORMULAS = {
    1: "contribution_margin",
    2: "twin.change.net_profit",
    3: "profit_driver.refunds",
    4: "cpa",
    5: "expected_monthly_impact",
}


def lookup(ids: list[int]) -> dict[int, str]:
    return {i: FORMULAS[i] for i in ids if i in FORMULAS}


def answer(text: str, evidence: list[int], **extra: Any) -> Answer:
    fields: dict[str, Any] = {
        "answer": text,
        "evidence": evidence,
        "reasoning": None,
        "alternatives": [],
        "uncertainty": "Estimated.",
        "recommendation": None,
        "would_change_my_mind": None,
        "flags": [],
        **extra,
    }
    return Answer.model_validate(fields)


@pytest.mark.parametrize(
    ("text", "metrics"),
    [
        ("Contribution margin fell to {{F1}}.", {"contribution_margin"}),
        ("Promoted contribution margin and revenue", {"promoted_contribution_margin", "revenue"}),
        ("The refund rate rose; a refund and the fees", {"refund_rate", "refunds", "fees"}),
        ("A CPA drift; ROAS and the cost per purchase", {"cpa", "roas"}),
        (
            "Stock cover is short and units on hand are zero",
            {"inventory_cover_days", "units_on_hand"},
        ),
        ("The unit cost rose in order to restock", set()),
        ("{{E:campaign:1}} and {{F12}} with no metric", set()),
    ],
)
def test_the_vocabulary(text: str, metrics: set[str]) -> None:
    assert named_metrics([text]) == metrics


def test_a_fact_covers_its_metric_and_its_parts() -> None:
    assert covers("refunds", "refunds")
    assert covers("profit_driver.refunds", "refunds")
    assert covers("twin.change.net_profit", "net_profit")
    assert covers("twin.change.net_profit.x", "net_profit")
    assert not covers("refund_rate", "refunds")
    assert not covers("expected_monthly_impact", "net_profit")


def test_the_check() -> None:
    check = citation_check(lookup)
    assert check(answer("Net profit changes by {{F2}}; refunds drive it {{F3}}.", [2, 3])) == []
    missing = check(answer("Contribution margin and CPA moved.", [5]))
    assert len(missing) == 1
    assert "contribution margin, cpa" in missing[0].detail
    hidden = answer("See {{F5}}.", [5], reasoning="Gross margin fell.")
    assert check(hidden)[0].path == "evidence"  # every text field counts
    assert check(answer("Nothing named, see {{F5}}.", [5])) == []


def test_the_contract_includes_citations_only_with_a_lookup() -> None:
    bare = answer("CPA rose, see {{F5}}.", [5])
    assert contract_checks(QuestionType.LOOKUP)(bare) == []
    assert [v.path for v in contract_checks(QuestionType.LOOKUP, lookup)(bare)] == ["evidence"]
    assert contract_checks(QuestionType.LOOKUP, lookup)(answer("CPA rose {{F4}}.", [4])) == []


# --- attached by code (ADR 0022) ---------------------------------------------------------------

CAMPAIGN_X, CAMPAIGN_Y = UUID(int=11), UUID(int=12)
WEEK = Period.days(date(2026, 9, 21), date(2026, 9, 28))
LAST_WEEK = Period.days(date(2026, 9, 14), date(2026, 9, 21))


def seen_fact(fid: int, metric: str, scope: Scope, period: Period = WEEK) -> Fact:
    return Fact(
        id=fid,
        store_id=UUID(int=1),
        formula_id=metric,
        formula_version=1,
        kind=FactKind.EXACT,
        scope=scope,
        period=period,
        status=FactStatus.DEFINED,
        value=Decimal("1"),
        unit=Unit.MONEY,
        currency="USD",
        inputs_hash="0" * 64,
    )


POOL = {
    f.id: f
    for f in (
        seen_fact(1, "net_profit", Scope.store()),
        seen_fact(2, "net_profit", Scope.store(), LAST_WEEK),
        seen_fact(3, "campaign_profit", Scope.campaign(CAMPAIGN_X)),
        seen_fact(4, "cpa", Scope.campaign(CAMPAIGN_X)),
        seen_fact(5, "cpa", Scope.campaign(CAMPAIGN_Y)),
        seen_fact(6, "profit_driver.refunds", Scope.store()),
        seen_fact(7, "refunds", Scope.store()),
    )
}


def repaired(text: str, evidence: list[int]) -> tuple[Any, list[int]]:
    repair = citation_repair(lambda: set(POOL), lambda ids: {i: POOL[i] for i in ids if i in POOL})
    return repair(answer(text, evidence))


def test_code_attaches_the_one_fact_a_metric_must_mean() -> None:
    x = f"{{{{E:campaign:{CAMPAIGN_X}}}}}"
    fixed, added = repaired(f"The campaign profit of {x} fell.", [])
    assert (added, fixed.evidence) == ([3], [3])
    _, added = repaired(f"CPA rose for {x}, see {{{{F3}}}}.", [3])
    assert added == [4]  # the entity the sentence names
    _, added = repaired("Net profit fell; refunds rose {{F6}}.", [6])
    assert added == []  # two periods of net profit: ambiguous, the model regenerates
    _, added = repaired("Net profit fell to {{F1}}.", [1])
    assert added == []  # already cited
    _, added = repaired("CPA rose.", [])
    assert added == []  # two campaigns: ambiguous
    _, added = repaired("Refunds rose.", [])
    assert added == [7]  # its own formula before its parts (profit_driver.refunds)
    _, added = repaired("Revenue grew.", [])
    assert added == []  # no revenue fact was seen


def test_resolve_uses_the_period_of_the_sentence() -> None:
    cited = {9: seen_fact(9, "revenue", Scope.store(), LAST_WEEK)}
    assert resolve("net_profit", ["Net profit and revenue {{F9}}."], POOL, cited) == 2
    assert resolve("net_profit", ["Net profit moved."], POOL, {}) is None
