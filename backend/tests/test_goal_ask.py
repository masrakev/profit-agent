"""Goal questions through Ask, with a scripted model (app/agent/goal.py)."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.agent.ask import QuestionType, ask, explain_goal
from app.agent.contracts import Flag
from app.agent.goal import _amount
from app.agent.llm import fake as f
from app.api.deps import get_engine, get_provider
from app.api.main import app
from app.db import tenant_transaction
from app.goals import service
from app.verifier import verify
from bench.scenarios.manifest import load_suite
from bench.simulator import register
from tests.api_helpers import act_as
from tests.llm_helpers import Harness

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def store(app_engine: Engine) -> UUID:
    manifest = next(m for m in load_suite("dev") if m.scenario_id == "dev-healthy-02")
    return register(app_engine, manifest, 80)


def today(engine: Engine, store: UUID) -> Any:
    with tenant_transaction(engine, store) as conn:
        return service.data_end(conn, store)


def classify() -> f.Reply:
    return f.structured({"question_type": "goal"}, model="muse-spark-1.3-contributor")


def intent(**fields: Any) -> f.Reply:
    base = {"metric": None, "target": None, "deadline": None, "missing": [], "ambiguous": None}
    return f.structured({**base, **fields})


def data_of(body: dict[str, Any]) -> dict[str, Any]:
    text = next(
        i["content"][0]["text"]
        for i in body["input"]
        if i["content"][0]["text"].startswith("Goal ")
    )
    parsed: dict[str, Any] = json.loads(text.split("\n", 1)[1])
    return parsed


def fid(ref: str) -> int:
    return int(ref.strip("{}F"))


def explanation(body: dict[str, Any]) -> f.Reply:
    data = data_of(body)
    plan = "probability_with_plan" in data
    prob = data["probability_with_plan"] if plan else data["probability"]
    verdict = (data.get("verdict_with_plan") if plan else data.get("verdict")) or "uncertain"
    evidence = [fid(prob)]
    alternatives = []
    if plan and data.get("alternatives"):
        alt = data["alternatives"]
        evidence += [fid(alt["target_with_even_odds"]), fid(alt["target_with_good_odds"])]
        alternatives = [f"{alt['target_with_even_odds']} or {alt['target_with_good_odds']}."]
    if plan and data["goal"]["metric"] == "revenue":
        evidence.append(fid(data["effect_on_net_profit"]))
    return f.structured(
        {
            "answer": f"Reaching the goal is {verdict}: {prob}.",
            "evidence": evidence,
            "reasoning": None,
            "alternatives": alternatives,
            "uncertainty": "A forecast, not a promise.",
            "recommendation": None,
            "would_change_my_mind": None,
            "flags": [],
            "ranked_causes": [],
            "action_family": None,
        }
    )


def test_a_goal_is_parsed_and_restated(app_engine: Engine, store: UUID) -> None:
    end = today(app_engine, store)
    last = end + timedelta(days=44)
    h = Harness(
        [classify(), intent(metric="net_profit", target="50,000", deadline=last.isoformat())]
    )
    result = ask(app_engine, store, "I want 50,000 in net profit by mid-November", h.provider)
    assert (result.status, result.question_type) == ("confirmation", QuestionType.GOAL)
    assert result.goal_id is not None
    assert f"{end.isoformat()} to {last.isoformat()}" in result.answer.answer
    assert not verify(result.answer.answer)
    parse_request = h.transport.requests[1]
    assert f"Store's today: {end.isoformat()}" in json.dumps(parse_request)
    with tenant_transaction(app_engine, store) as conn:
        goal = service.get(conn, store, result.goal_id)
    assert (goal.status, goal.metric, goal.horizon, str(goal.target)) == (
        "draft",
        "net_profit",
        45,
        "50000.0000",
    )
    assert result.answer.evidence == [goal.target_fact_id]


def test_what_is_missing_is_asked_back(app_engine: Engine, store: UUID) -> None:
    end = today(app_engine, store)
    cases = [
        intent(missing=["metric", "target", "deadline"]),
        intent(metric="revenue", target="1000", deadline=end.isoformat(), ambiguous="Which year?"),
        intent(metric="revenue", target="a lot", deadline=end.isoformat()),
        intent(metric="revenue", target="1000", deadline=(end + timedelta(days=400)).isoformat()),
    ]
    for reply in cases:
        h = Harness([classify(), reply])
        result = ask(app_engine, store, "I want to do better", h.provider)
        assert (result.status, result.goal_id) == ("clarification", None)
        assert Flag.ABSTAIN_INSUFFICIENT_EVIDENCE in result.answer.flags
        assert not verify(result.answer.answer)
    broken = Harness([classify(), f.ok([f.message("not json")])])
    assert ask(app_engine, store, "goal", broken.provider).status == "partial"
    assert (_amount("1.2e3"), _amount("-5"), _amount(None)) == (Decimal(1200), None, None)


def _goal(engine: Engine, store: UUID, metric: str, days: int, target: str) -> UUID:
    end = today(engine, store)
    with tenant_transaction(engine, store) as conn:
        goal = service.create(
            conn,
            store,
            metric,
            Decimal(target),
            end + timedelta(days=days),
            now=datetime.now(UTC),
            question="my goal",
        )
    return goal.goal_id


def test_the_feasibility_is_explained(app_engine: Engine, store: UUID) -> None:
    goal = _goal(app_engine, store, "net_profit", 40, "1")
    h = Harness([explanation])
    result = explain_goal(app_engine, store, goal, h.provider, what="feasibility")
    assert (result.status, result.question_type, result.goal_id) == (
        "answered",
        QuestionType.GOAL,
        goal,
    )
    assert "likely" in result.answer.answer  # a tiny target
    with tenant_transaction(app_engine, store) as conn:
        assert service.get(conn, store, goal).status == "confirmed"


def test_an_unusable_answer_falls_back_to_code(app_engine: Engine, store: UUID) -> None:
    goal = _goal(app_engine, store, "revenue", 30, "100000000")
    bad = f.structured({"answer": "Sure, $5 million.", "evidence": []})
    h = Harness([bad, bad, bad])
    result = explain_goal(app_engine, store, goal, h.provider, what="feasibility")
    assert result.status == "fallback"
    assert result.answer.answer.startswith("Reaching the goal is unlikely")
    assert result.answer.evidence
    assert not verify(result.answer.answer)


def test_a_long_goal_shows_a_range_only(app_engine: Engine, store: UUID) -> None:
    goal = _goal(app_engine, store, "contribution_margin", 150, "1000000")
    h = Harness([explanation])
    result = explain_goal(app_engine, store, goal, h.provider, what="feasibility")
    assert result.status == "answered"
    assert Flag.LOW_EVIDENCE in result.answer.flags
    sent = data_of(h.transport.requests[0])
    assert sent["probability_is_a_range_only"] is True
    assert sent["verdict"] is None
    assert len(sent["quarterly_checkpoints"]) == 2


def test_a_plan_is_explained(
    app_engine: Engine, store: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    goal = _goal(app_engine, store, "revenue", 60, "100000000")
    real = service.make_plan

    def lowering(*args: Any, **kwargs: Any) -> Any:
        plan = real(*args, **kwargs)
        return replace(plan, payload={**plan.payload, "lowers_profit": True})

    monkeypatch.setattr(service, "make_plan", lowering)
    h = Harness([explanation])
    result = explain_goal(app_engine, store, goal, h.provider, what="plan")
    assert result.status == "answered"
    assert result.answer.answer.startswith("Careful: this plan grows revenue but lowers net profit")
    sent = data_of(h.transport.requests[0])
    assert sent["alternatives"] is not None  # an unlikely target
    assert "experiments_never_counted" in sent
    assert not verify(result.answer.answer)


def test_the_explanation_through_the_api(app_engine: Engine, store: UUID) -> None:
    goal = _goal(app_engine, store, "net_profit", 40, "1")
    h = Harness([explanation])
    app.dependency_overrides[get_engine] = lambda: app_engine
    app.dependency_overrides[get_provider] = lambda: h.provider
    act_as(app)
    try:
        client = TestClient(app)
        base = f"/api/v1/stores/{store}/goals"
        done = client.post(f"{base}/{goal}/explain", json={"what": "feasibility"}).json()
        assert (done["status"], done["question_type"], done["goal_id"]) == (
            "answered",
            "goal",
            str(goal),
        )
        assert client.get(f"{base}/{goal}").json()["status"] == "confirmed"
        missing = client.post(f"{base}/{UUID(int=1)}/explain", json={})
        assert missing.status_code == 404
        assert client.post(f"{base}/{goal}/explain", json={"what": "x"}).status_code == 422
    finally:
        app.dependency_overrides.clear()
