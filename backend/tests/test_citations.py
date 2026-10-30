"""Citation completeness: a named metric needs a cited fact of that metric."""

from typing import Any

import pytest

from app.agent.ask import QuestionType, contract_checks
from app.agent.citations import citation_check, covers, named_metrics
from app.agent.contracts import Answer

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
