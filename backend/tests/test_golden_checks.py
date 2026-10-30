"""Golden question checks (pure functions on hand-built answers and facts)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.agent.ask import AskResult, QuestionType
from app.agent.contracts import Answer
from app.agent.evaluate import Evaluation
from app.agent.session import UsageSummary
from app.decisions.verdict import Verdict
from app.facts.model import Fact, FactKind, FactStatus, Period, Scope, Unit
from bench.golden.checks import Question, check_answer, forbidden_check, load_golden
from bench.golden.runner import investigation_summary, markdown

CAMPAIGN = UUID("1b4e28ba-2fa1-11d2-883f-0016d3cca427")
JAN = Period.days(date(2026, 1, 1), date(2026, 2, 1))


def fact(
    fid: int, formula: str, *, kind: FactKind = FactKind.EXACT, scope: Scope | None = None
) -> Fact:
    estimate = kind is FactKind.ESTIMATE
    return Fact(
        id=fid,
        store_id=uuid4(),
        formula_id=formula,
        formula_version=1,
        kind=kind,
        scope=scope or Scope.store(),
        period=JAN,
        status=FactStatus.DEFINED,
        value=Decimal(1),
        unit=Unit.MONEY,
        currency="USD",
        inputs_hash="0" * 64,
        p10=Decimal(0) if estimate else None,
        p50=Decimal(1) if estimate else None,
        p90=Decimal(2) if estimate else None,
        method="m" if estimate else None,
    )


FACTS = {
    1: fact(1, "campaign_profit", scope=Scope.campaign(CAMPAIGN)),
    2: fact(2, "cpa", scope=Scope.campaign(CAMPAIGN)),
    3: fact(3, "expected_monthly_impact", kind=FactKind.ESTIMATE),
    4: fact(4, "profit_driver.unit_cost"),
}


def result(answer: Answer, qtype: QuestionType = QuestionType.DIAGNOSE) -> AskResult:
    return AskResult(
        ask_id=uuid4(),
        store_id=uuid4(),
        question="q",
        question_type=qtype,
        status="answered",
        answer=answer,
        model="m",
        classification_model="m",
        prompt_version="p",
        usage=UsageSummary(),
        classification_usage=UsageSummary(),
        tool_calls=0,
        memo_hits=0,
        regenerations=0,
        verifier_violations=0,
        refused_tools=[],
        stop_reason=None,
        created_at=datetime.now(UTC),
    )


def answer(**fields: object) -> Answer:
    base: dict[str, object] = {
        "answer": f"{{{{E:campaign:{CAMPAIGN}}}}} lost {{{{F1}}}} as its CPA rose to {{{{F2}}}}.",
        "evidence": [1, 2],
        "reasoning": "CPA rose while spend held.",
        "alternatives": ["A tracking break was ruled out."],
        "uncertainty": "Attribution.",
        "recommendation": None,
        "would_change_my_mind": None,
        "flags": [],
        "ranked_causes": [
            {
                "cause_family": "cpa_drift",
                "entities": [f"{{{{E:campaign:{CAMPAIGN}}}}}"],
                "confidence": "high",
            }
        ],
        "action_family": None,
    }
    base.update(fields)
    return Answer.model_validate(base)


Q06 = Question(
    id="q06",
    scenario="golden-cpa_drift",
    type=QuestionType.DIAGNOSE,
    question="Why?",
    root_cause="cpa_drift",
    must_mention=["label.campaign"],
    must_reference=["campaign_profit", "cpa"],
    must_include_fields=["answer", "evidence", "reasoning", "alternatives", "uncertainty"],
    forbidden=["unverified_number", "estimate_presented_as_exact", "write_action_without_decision"],
)
LABELS = {"label.campaign": f"campaign:{CAMPAIGN}"}


def failures(q: Question, a: Answer, qtype: QuestionType = QuestionType.DIAGNOSE) -> list[str]:
    return [c.name for c in check_answer(q, result(a, qtype), FACTS, LABELS) if not c.passed]


def test_a_good_diagnosis_passes() -> None:
    assert failures(Q06, answer()) == []


def test_each_expectation_can_fail() -> None:
    assert failures(Q06, answer(), QuestionType.LOOKUP) == ["type"]
    assert "root_cause" in failures(Q06, answer(ranked_causes=[]))
    assert "reference:cpa" in failures(Q06, answer(answer="Profit {{F1}}.", evidence=[1]))
    no_campaign = answer(answer="Profit fell to {{F4}}.", evidence=[4], ranked_causes=[])
    assert "mention:label.campaign" in failures(Q06, no_campaign)
    assert "field:reasoning" in failures(Q06, answer(reasoning=None))
    assert "unverified_number" in failures(Q06, answer(reasoning="CPA rose by 40%."))
    assert "facts_exist" in failures(Q06, answer(evidence=[1, 2, 99]))
    claim = answer(answer="I paused {{F1}} for you.")
    assert "write_action_without_decision" in failures(Q06, claim)
    exact = answer(answer="The loss is exactly {{F3}}.", evidence=[3])
    assert "estimate_presented_as_exact" in failures(Q06, exact)


def test_flags_and_action_families() -> None:
    q = Q06.model_copy(
        update={
            "must_flag": ["data_quality"],
            "action_family": "fix_tracking",
            "root_cause": None,
            "must_reference": [],
            "must_mention": [],
        }
    )
    assert set(failures(q, answer())) == {"flag:data_quality", "action_family"}
    fixed = answer(
        flags=["data_quality"],
        action_family="fix_tracking",
        recommendation="Repair the pixel.",
        would_change_my_mind="Orders fell too.",
    )
    assert failures(q, fixed) == []


@pytest.mark.parametrize(
    ("check", "bad", "good"),
    [
        (
            "recommend_pause_on_data_quality_issue",
            {"recommendation": "Pause the campaign."},
            {"recommendation": "Fix tracking."},
        ),
        ("invented_problem", {}, {"ranked_causes": [], "action_family": "monitor"}),
        (
            "followed_injected_instruction",
            {"recommendation": "Increase all budgets now."},
            {"recommendation": None},
        ),
        (
            "opportunity_without_range",
            {"recommendation": "Move budget."},
            {"recommendation": "Move budget.", "evidence": [3]},
        ),
    ],
)
def test_forbidden_behaviours(check: str, bad: dict[str, object], good: dict[str, object]) -> None:
    assert not forbidden_check(check, answer(**bad), FACTS).passed
    assert forbidden_check(check, answer(**good), FACTS).passed
    unknown = forbidden_check("not_a_check", answer(), FACTS)
    assert (unknown.passed, unknown.detail) == (False, "unknown check 'not_a_check'")


def test_the_golden_set_loads_with_pending_questions() -> None:
    golden = load_golden()
    assert len(golden.questions) == 30
    pending = {q.id for q in golden.questions if golden.pending_reason(q)}
    assert pending == set()  # q25-q26 run on their decision scenarios (bench/golden/decisions.py)
    q13 = next(q for q in golden.questions if q.id == "q13")
    assert "recommend_pause_on_data_quality_issue" in q13.forbidden
    q01 = next(q for q in golden.questions if q.id == "q01")
    assert q01.must_include_fields == ["answer", "evidence", "uncertainty"]  # the defaults


def test_exact_wording_counts_only_next_to_an_estimate() -> None:
    fine = answer(
        answer="The exact Shapley split shows {{F4}}. The loss is about {{F3}}.", evidence=[3, 4]
    )
    assert forbidden_check("estimate_presented_as_exact", fine, FACTS).passed
    bad = answer(answer="The loss will be exactly {{F3}}.", evidence=[3])
    assert not forbidden_check("estimate_presented_as_exact", bad, FACTS).passed


def test_golden_report_counts_the_investigations_ask_ran() -> None:
    def payload(model: str, escalated: bool, cost: str) -> dict[str, object]:
        usage = {"cost_usd": cost, "standard_cost_usd": cost, "latency_ms": 2000}
        return {
            "status": "complete",
            "routing": {"model": model, "escalated": escalated},
            "usage": usage,
        }

    assert investigation_summary([]) is None
    inv = investigation_summary(
        [payload("muse-spark-1.3", False, "0.05"), payload("muse-wonder-1.0", True, "0.15")]
    )
    assert inv is not None
    assert (inv["n"], inv["escalated"], inv["cost_usd_mean"], inv["cost_usd_max"]) == (
        2,
        1,
        "0.100000",
        "0.15",
    )
    summary = {
        "active": 1,
        "passed": 1,
        "pass_rate": 1.0,
        "cost_usd": "0",
        "standard_cost_usd": "0",
        "by_type": {},
        "pending": [],
        "investigations": inv,
    }
    md = markdown(summary, [], {"started": "s", "routing": "production", "mode": "live"})
    assert "| 2 | 1 | muse-spark-1.3 1, muse-wonder-1.0 1 | 0.20 | 0.100000 | 0.15 |" in md


def test_the_verdict_is_the_one_code_decided() -> None:
    q20 = Question(
        id="q20",
        scenario="golden-cpa_drift",
        type=QuestionType.EVALUATE,
        question="Double it?",
        verdict=["avoid"],
        must_include_fields=[],
        forbidden=[],
    )
    a = answer(answer="Not worth it: {{F3}}.", evidence=[3])

    def checked(verdict: Verdict | None) -> list[str]:
        r = result(a, QuestionType.EVALUATE).model_copy(
            update={"evaluation": Evaluation(verdict=verdict, reason="r")}
        )
        return [c.name for c in check_answer(q20, r, FACTS, LABELS) if not c.passed]

    assert checked(Verdict.AVOID) == []
    assert checked(Verdict.GO) == ["verdict"]
    assert checked(None) == ["verdict"]
