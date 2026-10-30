"""Review questions: did a past decision work? Answers cite the measured effect, or abstain."""

import json
from typing import Any

import pytest
from sqlalchemy import Engine

from app.agent.ask import QuestionType, ask
from app.agent.contracts import Answer, Flag
from app.agent.llm import fake as f
from app.agent.review import review_checks
from bench.simulator import advance
from tests.action_helpers import Rig, approved, option_set, simulator_store
from tests.llm_helpers import Harness


@pytest.fixture(scope="module")
def sim(app_engine: Engine) -> dict[str, Any]:
    """A simulator store with one executed pause, seven days ago."""
    store = simulator_store(app_engine, "dev-mix_shift-05")
    approved(app_engine, store["id"], option_set(store["campaigns"][0], label="review"))
    Rig(app_engine).executor().run_once()
    advance(app_engine, store["id"], 7)
    return store


@pytest.mark.db
def test_review_answers_abstain_without_a_measured_outcome(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    h = Harness([f.structured({"question_type": "review"}, model="muse-spark-1.3-contributor")])
    out = ask(app_engine, golden_stockout["id"], "Did my last change work?", h.provider)
    assert (out.status, out.question_type) == ("abstained", QuestionType.REVIEW)
    assert out.answer.flags == [Flag.ABSTAIN_INSUFFICIENT_EVIDENCE]
    assert len(h.transport.requests) == 1


@pytest.mark.db
def test_review_answers_cite_the_measured_effect(app_engine: Engine, sim: dict[str, Any]) -> None:
    def explain(body: dict[str, Any]) -> f.Reply:
        payload = json.loads(
            next(
                i["content"][0]["text"]
                for i in body["input"]
                if i["content"][0]["text"].startswith("Executed decisions")
            ).split("\n", 1)[1]
        )
        latest = payload[0]
        effect = latest["outcome"]["effect"]
        cited = [effect["fact_id"]] if effect else [latest["current_facts"][0]["fact_id"]]
        flags = [] if effect else ["abstain_insufficient_evidence"]
        return f.structured(
            {
                "answer": f"The change's effect was {{{{F{cited[0]}}}}}.",
                "evidence": cited,
                "reasoning": None,
                "alternatives": [],
                "uncertainty": "An estimate against untouched campaigns.",
                "recommendation": None,
                "would_change_my_mind": None,
                "flags": flags,
                "ranked_causes": [],
                "action_family": None,
            }
        )

    h = Harness(
        [f.structured({"question_type": "review"}, model="muse-spark-1.3-contributor"), explain]
    )
    out = ask(app_engine, sim["id"], "Did pausing it work?", h.provider)
    assert out.question_type is QuestionType.REVIEW
    assert out.status == "answered"
    assert out.answer.evidence


def test_a_review_never_calls_an_estimate_exact() -> None:
    check = review_checks([7], {7, 8}, lambda _: [])

    def answer(uncertainty: str) -> Answer:
        return Answer(
            answer="The pause earned {{F7}}.",
            evidence=[7],
            reasoning=None,
            alternatives=[],
            uncertainty=uncertainty,
            recommendation=None,
            would_change_my_mind=None,
            flags=[],
        )

    assert check(answer("The effect {{F7}} is likely between its bounds.")) == []
    [exact] = check(answer("The effect {{F7}} is an estimate, never exact."))
    assert (exact.path, exact.detail) == ("uncertainty", "an estimate is never exact")
    assert check(answer("The prediction {{F8}} was exactly right.")) != []
    assert check(answer("Spend is an exact fact.")) == []  # no estimate cited
    missing = check(answer("{{F8}} only.").model_copy(update={"evidence": [8]}))
    assert [v.detail for v in missing] == ["cite the measured effect"]
