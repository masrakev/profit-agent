"""Ask on the golden stockout store and on a small hostile store, with a scripted model."""

import json
import re
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.agent import ask as ask_module
from app.agent.ask import (
    AskResult,
    QuestionType,
    ask,
    classification_routing,
    contract_checks,
)
from app.agent.contracts import ActionFamily, Answer, Flag
from app.agent.investigator import investigate
from app.agent.llm import DataOrigin
from app.agent.llm import fake as f
from app.agent.stages import Routing
from app.db import tenant_transaction
from bench.scenarios.build import INJECTION_TEXT
from tests import test_investigator as investigation_steps
from tests.builders import Scenario
from tests.conftest import create_store
from tests.llm_helpers import Harness

pytestmark = pytest.mark.db


def classify(kind: str) -> f.Reply:
    return f.structured({"question_type": kind}, model="muse-spark-1.3-contributor")


def fact_ids(body: dict[str, Any]) -> list[int]:
    return [int(x) for x in re.findall(r'fact_id\\?":\s*(\d+)', json.dumps(body["input"]))]


def answer(text: str, evidence: list[int], **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "answer": text,
        "evidence": evidence,
        "reasoning": None,
        "alternatives": [],
        "uncertainty": "Attribution is platform-reported.",
        "recommendation": None,
        "would_change_my_mind": None,
        "flags": [],
        "ranked_causes": [],
        "action_family": None,
    }
    payload.update(extra)
    return payload


def run(
    app_engine: Engine, store_id: Any, question: str, steps: list[Any]
) -> tuple[AskResult, Harness]:
    h = Harness(steps)
    return ask(app_engine, store_id, question, h.provider), h


def test_out_of_scope_and_not_available(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    out, h = run(
        app_engine, golden_stockout["id"], "Should I hire someone?", [classify("out_of_scope")]
    )
    assert (out.status, out.question_type) == ("out_of_scope", QuestionType.OUT_OF_SCOPE)
    assert out.answer.flags == [Flag.OUT_OF_SCOPE]
    assert len(h.transport.requests) == 1  # classification only
    # A scope statement plus what the product can say: one fact, cited.
    assert len(out.answer.evidence) == 1
    assert f"{{{{F{out.answer.evidence[0]}}}}}" in out.answer.answer
    # SPEC section 16: classification uses the Contributor model on synthetic stores.
    assert h.transport.requests[0]["model"] == "muse-spark-1.3-contributor"
    assert out.classification_model == "muse-spark-1.3-contributor"
    # A review with no executed decision abstains (no model call beyond classification).
    result, _ = run(app_engine, golden_stockout["id"], "Did it work?", [classify("review")])
    assert result.status == "abstained"
    assert result.answer.flags == [Flag.ABSTAIN_INSUFFICIENT_EVIDENCE]


def test_a_lookup_is_answered_with_facts(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    def cite(body: dict[str, Any]) -> f.Reply:
        fid = fact_ids(body)[0]
        return f.structured(answer(f"The expected loss is {{{{F{fid}}}}}.", [fid]))

    steps = [
        classify("lookup"),
        f.ok([f.function_call("list_incidents", {"include_watchlist": False})]),
        cite,
    ]
    result, h = run(app_engine, golden_stockout["id"], "What is my biggest problem?", steps)
    assert (result.status, result.question_type) == ("answered", QuestionType.LOOKUP)
    assert result.tool_calls == 1
    assert result.usage.calls == 2
    assert result.classification_usage.calls == 1
    question = h.transport.requests[1]["input"][1]["content"][0]["text"]
    assert question.startswith("Question type: lookup")
    assert h.transport.requests[1]["text"]["format"]["name"] == "Answer"


def test_a_diagnosis_needs_causes_and_alternatives(
    app_engine: Engine, golden_stockout: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The diagnosis builds on investigations of the most urgent incidents: one real
    # investigation (scripted model) stands in for each of them.
    inv_harness = Harness([investigation_steps.call_sensitivity, investigation_steps.answer])
    investigation = investigate(
        app_engine,
        golden_stockout["id"],
        golden_stockout["incident"],
        inv_harness.provider,
        use_cache=False,
    )
    monkeypatch.setattr(ask_module, "investigate", lambda *a, **k: investigation)

    def thin(body: dict[str, Any]) -> f.Reply:
        fid = fact_ids(body)[0]
        return f.structured(answer(f"See {{{{F{fid}}}}}.", [fid]))

    def full(body: dict[str, Any]) -> f.Reply:
        fid = fact_ids(body)[0]
        return f.structured(
            answer(
                f"A promoted product ran out of stock, see {{{{F{fid}}}}}.",
                [fid],
                alternatives=["A drift in the campaign's efficiency was considered and rejected."],
                ranked_causes=[
                    {
                        "cause_family": "stockout_on_promoted",
                        "entities": ["{{E:store}}"],
                        "confidence": "medium",
                    }
                ],
            )
        )

    steps = [
        classify("diagnose"),
        f.ok([f.function_call("list_incidents", {"include_watchlist": False})]),
        thin,
        full,
    ]
    result, h = run(app_engine, golden_stockout["id"], "Why is profit down?", steps)
    assert (result.status, result.regenerations) == ("answered", 1)
    sent = [i["content"][0]["text"] for i in h.transport.requests[1]["input"][:3]]
    assert sent[0].startswith("Store context")
    assert sent[1].startswith("Incidents (result of list_incidents")
    assert investigation.incident_id in sent[1]
    assert sent[2].startswith("Question type: diagnose")
    feedback = h.transport.requests[3]["input"][-1]["content"][0]["text"]
    assert "rank the causes" in feedback
    assert "list the alternatives" in feedback
    assert result.answer.ranked_causes[0].cause_family.value == "stockout_on_promoted"


def test_classification_failure_and_unverifiable_answers(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    down, _ = run(
        app_engine, golden_stockout["id"], "Hello?", [f.error(503, "server_error", "down")] * 4
    )
    assert (down.status, down.stop_reason) == ("partial", "classification failed")
    bad = f.structured(answer("Profit fell by $12,345.", []))
    result, _ = run(
        app_engine, golden_stockout["id"], "Profit?", [classify("lookup"), bad, bad, bad]
    )
    assert result.status == "fallback"
    assert result.verifier_violations == 3
    assert result.answer.flags == [Flag.ABSTAIN_INSUFFICIENT_EVIDENCE]


def test_injected_store_text_is_flagged(app_engine: Engine) -> None:
    store = create_store(app_engine, name="Hostile shop")
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        product = s.product("10.00", "4.00", "0")
        s.order("2026-01-05T10:00:00", [(product, 1, "10.00", "4.00", "0")])
        conn.execute(
            text("UPDATE products SET name = :n WHERE id = :p"),
            {"n": f"Mug {INJECTION_TEXT}", "p": product},
        )

    def answer_clean(body: dict[str, Any]) -> f.Reply:
        return f.structured(
            answer("The product is out of stock data.", [], flags=["abstain_insufficient_evidence"])
        )

    steps = [
        f.structured({"question_type": "lookup"}),
        f.ok([f.function_call("get_inventory_context", {"product_id": str(product)})]),
        answer_clean,
    ]
    result, h = run(app_engine, store, "How is my mug doing?", steps)
    assert result.status == "answered"
    assert Flag.NO_INSTRUCTION_FOLLOWING_FROM_DATA in result.answer.flags
    assert h.transport.requests[0]["model"] == "muse-spark-1.3"  # a real store: Standard mode


def test_contract_checks() -> None:
    check = contract_checks(QuestionType.DIAGNOSE)
    base = Answer.model_validate(
        answer(
            "ok",
            [1],
            alternatives=["x"],
            ranked_causes=[
                {
                    "cause_family": "tracking_break",
                    "entities": ["{{E:store}}"],
                    "confidence": "high",
                }
            ],
        )
    )
    assert check(base) == []
    no_mind = base.model_copy(update={"recommendation": "Fix the pixel."})
    assert [v.path for v in check(no_mind)] == ["would_change_my_mind"]
    pause = base.model_copy(
        update={
            "flags": [Flag.DATA_QUALITY],
            "recommendation": "Pause the campaign now.",
            "would_change_my_mind": "Orders falling too.",
        }
    )
    assert [v.kind for v in check(pause)] == ["safety"]
    cut = base.model_copy(
        update={
            "flags": [Flag.DATA_QUALITY],
            "action_family": ActionFamily.PAUSE_OR_REDUCE_CAMPAIGN,
        }
    )
    assert [v.kind for v in check(cut)] == ["safety"]
    fix = cut.model_copy(update={"action_family": ActionFamily.FIX_TRACKING})
    assert check(fix) == []
    claim = base.model_copy(update={"answer": "I paused the campaign for you."})
    assert [v.kind for v in check(claim)] == ["safety"]
    empty = base.model_copy(update={"evidence": []})
    assert [v.path for v in check(empty)] == ["evidence"]
    healthy = Answer.model_validate(answer("Nothing is wrong.", [], flags=["no_material_issue"]))
    assert check(healthy) == []
    assert (
        contract_checks(QuestionType.LOOKUP)(
            base.model_copy(update={"ranked_causes": [], "alternatives": []})
        )
        == []
    )
    assert classification_routing(DataOrigin.SYNTHETIC) is Routing.ECONOMY
    assert classification_routing(DataOrigin.REAL) is Routing.PRODUCTION


def test_a_named_metric_is_attached_without_a_regeneration(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    """The answer names ad spend but cites only the campaign's ROAS: code attaches the
    campaign's ad spend fact for the same period (ADR 0022), no second model call."""
    campaign = golden_stockout["campaign"]
    found: dict[str, int] = {}

    def cite(body: dict[str, Any]) -> f.Reply:
        views = re.findall(
            r'fact_id\\?":\s*(\d+).{0,40}?metric\\?":\s*\\?"([a-z_.]+)', json.dumps(body["input"])
        )
        found.update({metric: int(fid) for fid, metric in reversed(views)})
        roas = found["roas"]
        return f.structured(
            answer(
                f"{{{{E:campaign:{campaign}}}}} turns its ad spend into a ROAS of {{{{F{roas}}}}}.",
                [roas],
            )
        )

    steps = [
        classify("lookup"),
        f.ok([f.function_call("get_campaign_context", {"campaign_id": str(campaign)})]),
        cite,
    ]
    result, h = run(app_engine, golden_stockout["id"], "Is this campaign worth it?", steps)
    assert result.status == "answered"
    assert (result.regenerations, result.citations_attached) == (0, 1)
    assert len(h.transport.requests) == 3  # no regeneration
    assert len(result.answer.evidence) == 2
