"""Evaluate and what-if: intent resolution, variants, the code verdict, and the Ask flow."""

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine

from app.agent.ask import AskResult, QuestionType, ask
from app.agent.contracts import Answer, Flag
from app.agent.evaluate import (
    IntentAction,
    ParsedIntent,
    clarification_answer,
    resolve,
    variants,
)
from app.agent.llm import fake as f
from app.decisions.verdict import Verdict, judge
from app.twin import Action, ActionKind, Scenario
from app.twin.model import Range, Simulation, TwinModel
from tests.llm_helpers import Harness
from tests.test_twin import CAMPAIGN, OTHER, PROMOTED
from tests.test_twin import model as twin_model  # noqa: F401  (module fixture)


def parsed(**fields: Any) -> ParsedIntent:
    base: dict[str, Any] = {
        "action": None,
        "entity": None,
        "best_selling_product": False,
        "change_percent": None,
        "duration_days": None,
        "missing": [],
    }
    return ParsedIntent.model_validate({**base, **fields})


def test_resolve_builds_the_scenario(twin_model: TwinModel) -> None:  # noqa: F811
    cut, missing = resolve(
        parsed(action="change_budget", entity=f"{{{{E:campaign:{CAMPAIGN}}}}}", change_percent=-30),
        twin_model,
    )
    assert missing == []
    assert cut == Scenario(
        actions=(Action(kind=ActionKind.CHANGE_BUDGET, entity=CAMPAIGN, change=Decimal("-0.3")),)
    )
    stop, _ = resolve(
        parsed(action="change_budget", entity=f"campaign:{CAMPAIGN}", change_percent=-100),
        twin_model,
    )
    assert stop is not None
    assert stop.actions[0].kind is ActionKind.PAUSE_CAMPAIGN
    discount, _ = resolve(
        parsed(
            action="change_price", best_selling_product=True, change_percent=-20, duration_days=14
        ),
        twin_model,
    )
    assert discount is not None
    # Most units over the window; ties go to the larger id (both test products sell the same).
    best = max(twin_model.products, key=lambda p: (twin_model.products[p].units_observed, str(p)))
    assert (discount.actions[0].entity, discount.actions[0].change) == (best, Decimal("-0.2"))
    assert (discount.horizon_days, discount.actions[0].days) == (14, None)
    week, _ = resolve(
        parsed(
            action="change_price", entity=f"product:{OTHER}", change_percent=10, duration_days=7
        ),
        twin_model,
    )
    assert week is not None
    assert (week.horizon_days, week.actions[0].days) == (14, 7)
    month, _ = resolve(
        parsed(action="change_all_ad_spend", change_percent=-30, duration_days=90), twin_model
    )
    assert month is not None
    assert (month.horizon_days, month.actions[0].entity) == (60, None)
    launch, _ = resolve(parsed(action="launch_campaign", entity=f"product:{OTHER}"), twin_model)
    assert launch is not None
    assert launch.actions[0].daily_budget == Decimal("100.00")


def test_resolve_asks_back_instead_of_guessing(twin_model: TwinModel) -> None:  # noqa: F811
    assert resolve(parsed(), twin_model) == (None, ["action"])
    no_size = parsed(action="change_budget", entity=f"campaign:{CAMPAIGN}")
    assert resolve(no_size, twin_model) == (None, ["magnitude"])
    absurd = parsed(action="change_price", entity=f"product:{OTHER}", change_percent=-95)
    assert resolve(absurd, twin_model) == (None, ["magnitude"])
    unknown = parsed(action="pause_campaign", entity=f"campaign:{UUID(int=4)}")
    assert resolve(unknown, twin_model) == (None, ["entity"])
    wrong_kind = parsed(action="pause_campaign", entity=f"product:{OTHER}")
    assert resolve(wrong_kind, twin_model) == (None, ["entity"])
    said_missing = parsed(
        action="pause_campaign", entity=f"campaign:{CAMPAIGN}", missing=["entity", "magnitude"]
    )
    assert resolve(said_missing, twin_model)[1] == []  # resolved after all; no size needed
    no_campaigns = TwinModel(**{**twin_model.__dict__, "campaigns": {}})
    assert resolve(parsed(action="launch_campaign", entity=f"product:{OTHER}"), no_campaigns) == (
        None,
        ["entity"],
    )
    ask_back = clarification_answer(["entity", "magnitude"], twin_model)
    assert f"{{{{E:campaign:{CAMPAIGN}}}}}" in ask_back.answer
    assert ask_back.flags == [Flag.ABSTAIN_INSUFFICIENT_EVIDENCE]


def test_variants_change_size_or_duration() -> None:
    def kinds(action: Action) -> list[tuple[str, str, int | None]]:
        return [
            (v.actions[0].kind.value, str(v.actions[0].change), v.actions[0].days)
            for v in variants(Scenario(actions=(action,)))
        ]

    assert kinds(
        Action(kind=ActionKind.CHANGE_BUDGET, entity=CAMPAIGN, change=Decimal("-0.2"))
    ) == [
        ("change_budget", "-0.1", None),
        ("change_budget", "-0.3", None),
        ("pause_campaign", "0", None),
    ]
    assert kinds(Action(kind=ActionKind.CHANGE_ALL_AD_SPEND, change=Decimal(1))) == [
        ("change_all_ad_spend", "0.1", None),
        ("change_all_ad_spend", "0.2", None),
        ("change_all_ad_spend", "0.3", None),
    ]
    assert [k for k, _, _ in kinds(Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=CAMPAIGN))] == [
        "change_budget",
        "change_budget",
    ]
    assert kinds(Action(kind=ActionKind.CHANGE_PRICE, entity=OTHER, change=Decimal("-0.2"))) == [
        ("change_price", "-0.05", None),
        ("change_price", "-0.1", None),
        ("change_price", "-0.15", None),
        ("change_price", "-0.2", 7),
    ]
    assert kinds(
        Action(kind=ActionKind.CHANGE_PRICE, entity=OTHER, change=Decimal("0.04"), days=1)
    ) == [("change_price", "0.03", 1)]
    launch = Action(kind=ActionKind.LAUNCH_CAMPAIGN, entity=PROMOTED, daily_budget=Decimal(50))
    assert [v.actions[0].daily_budget for v in variants(Scenario(actions=(launch,)))] == [
        Decimal("25.00")
    ]


def sim(change: Range | None) -> Simulation:
    return Simulation(
        scenario=Scenario(),
        totals={},
        do_nothing={},
        change={} if change is None else {"net_profit": change},
        undefined_reason=None if change else "cannot",
    )


def test_verdict_rule() -> None:
    floor = 50.0
    good, better, risky, losing = (
        sim(Range(-10, 100, 200)),
        sim(Range(0, 300, 500)),
        sim(Range(-400, 200, 600)),
        sim(Range(-300, -100, 50)),
    )
    assert judge(good, [sim(Range(-20, 120, 200))], floor).verdict is Verdict.GO
    adjust = judge(good, [better], floor)
    assert (adjust.verdict, adjust.adjusted) == (Verdict.ADJUST, better)
    assert judge(risky, [good], floor).verdict is Verdict.ADJUST
    assert judge(losing, [good], floor).verdict is Verdict.ADJUST
    assert judge(losing, [risky], floor).reason.startswith("no version")
    assert judge(risky, [losing], floor).verdict is Verdict.AVOID
    assert judge(risky, [], floor).reason.startswith("the downside")
    assert judge(sim(None), [good], floor).verdict is None


# --- the Ask flow, with a scripted model ---------------------------------------------------


def classify(kind: str) -> f.Reply:
    return f.structured({"question_type": kind}, model="muse-spark-1.3-contributor")


def intent(**fields: Any) -> f.Reply:
    return f.structured(parsed(**fields).model_dump(mode="json"))


def context(body: dict[str, Any]) -> dict[str, Any]:
    for item in body["input"]:
        text = item["content"][0]["text"]
        if text.startswith("Simulation results"):
            payload: dict[str, Any] = json.loads(text.split("\n", 1)[1])
            return payload
    raise AssertionError("no simulation context")


def explained(body: dict[str, Any], **extra: Any) -> f.Reply:
    scenario = context(body)["scenario"]
    change = scenario["simulated_change_vs_doing_nothing"]["net_profit"]["fact_id"]
    days = scenario["parameters"]["twin.parameter.horizon_days"]["fact_id"]
    now = context(body)["entity_facts"][0]["fact_id"]
    payload = {
        "answer": f"Not worth doing: net profit would change by {{{{F{change}}}}}.",
        "evidence": [change, days, now],
        "reasoning": f"Today {{{{F{now}}}}}; over {{{{F{days}}}}} days the spend sells no more.",
        "alternatives": ["A smaller budget loses less."],
        "uncertainty": "The new campaign's response is borrowed from the store's others.",
        "recommendation": "Restock first.",
        "would_change_my_mind": "Stock arriving before the campaign starts.",
        "flags": [],
        "ranked_causes": [],
        "action_family": None,
        **extra,
    }
    return f.structured(payload)


@pytest.mark.db
def test_evaluate_a_new_campaign_on_an_empty_product(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    product = golden_stockout["product"]
    h = Harness(
        [
            classify("evaluate"),
            intent(action="launch_campaign", entity=f"product:{product}"),
            explained,
        ]
    )
    out = ask(app_engine, golden_stockout["id"], "Should I launch a campaign for it?", h.provider)
    assert (out.status, out.question_type) == ("answered", QuestionType.EVALUATE)
    assert out.evaluation is not None
    assert out.evaluation.verdict is Verdict.AVOID
    assert out.evaluation.change_fact_id in out.answer.evidence
    assert Flag.LOW_EVIDENCE in out.answer.flags  # the response curve is borrowed
    assert out.evaluation.scenario is not None
    assert out.evaluation.scenario.actions[0].kind is ActionKind.LAUNCH_CAMPAIGN
    requests = h.transport.requests
    assert requests[1]["text"]["format"]["name"] == "ParsedIntent"
    assert "tools" not in requests[2] or not requests[2]["tools"]
    assert context(requests[2])["verdict"] == "avoid"
    assert out.usage.calls == 2  # intent and explanation (classification counted apart)


@pytest.mark.db
def test_what_if_and_its_checks(app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    def no_reasoning(body: dict[str, Any]) -> f.Reply:
        return explained(body, reasoning=None, alternatives=[])

    steps = [
        classify("what_if"),
        intent(action="change_all_ad_spend", change_percent=-30),
        no_reasoning,
        explained,
    ]
    h = Harness(steps)
    out = ask(app_engine, golden_stockout["id"], "What if I cut all ads by 30%?", h.provider)
    assert (out.status, out.question_type) == ("answered", QuestionType.WHAT_IF)
    assert out.evaluation is not None
    assert out.evaluation.verdict is None
    assert out.regenerations == 1  # a what-if answer explains the effect
    assert out.evaluation.variant_fact_ids


@pytest.mark.db
def test_evaluate_falls_back_and_asks_back(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]

    def exact(body: dict[str, Any]) -> f.Reply:
        change = context(body)["scenario"]["simulated_change_vs_doing_nothing"]["net_profit"]
        return explained(body, answer=f"It costs exactly {{{{F{change['fact_id']}}}}}.")

    campaign = f"campaign:{golden_stockout['campaign']}"
    h = Harness(
        [
            classify("evaluate"),
            intent(action="pause_campaign", entity=campaign),
            exact,
            exact,
            exact,
        ]
    )
    out = ask(app_engine, store, "Should I pause it?", h.provider)
    assert out.status == "fallback"
    assert out.evaluation is not None
    assert out.evaluation.verdict is not None
    assert out.evaluation.change_fact_id in out.answer.evidence
    assert out.answer.alternatives
    unclear = Harness([classify("evaluate"), intent(action="change_budget", missing=["entity"])])
    asked = ask(app_engine, store, "Should I change a budget?", unclear.provider)
    assert asked.status == "clarification"
    assert asked.evaluation is not None
    assert asked.evaluation.missing == ["entity", "magnitude"]
    assert len(unclear.transport.requests) == 2
    broken = Harness([classify("what_if"), f.ok([f.message("not json")])])
    failed = ask(app_engine, store, "What if?", broken.provider)
    assert (failed.status, failed.stop_reason) == ("partial", "intent parsing failed")


def test_answers_are_answers() -> None:
    assert isinstance(clarification_answer(["action"], None), Answer)
    assert isinstance(AskResult, type)
    assert IntentAction("change_price") is IntentAction.CHANGE_PRICE


@pytest.mark.db
def test_an_evaluation_starts_from_the_current_facts(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    def simulation_only(body: dict[str, Any]) -> f.Reply:
        scenario = context(body)["scenario"]
        change = scenario["simulated_change_vs_doing_nothing"]["net_profit"]["fact_id"]
        return explained(body, evidence=[change], reasoning=f"It moves {{{{F{change}}}}}.")

    product = golden_stockout["product"]
    steps = [
        classify("evaluate"),
        intent(action="launch_campaign", entity=f"product:{product}"),
        simulation_only,
        explained,
    ]
    h = Harness(steps)
    out = ask(app_engine, golden_stockout["id"], "Launch one?", h.provider)
    assert (out.status, out.regenerations) == ("answered", 1)
