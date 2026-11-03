"""Conversations: each answer Ask gives is kept as a turn of a conversation, read again in order;
a question about a decision or a goal carries it (scripted model)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.agent.llm import fake as f
from app.api.deps import get_engine, get_provider
from app.api.main import app
from app.conversations.store import Topic, framed, title_of
from app.db import tenant_transaction
from app.goals import service
from tests.api_helpers import act_as
from tests.llm_helpers import Harness

pytestmark = pytest.mark.db


@pytest.fixture
def harness() -> Harness:
    return Harness([])


@pytest.fixture
def client(app_engine: Engine, harness: Harness) -> Iterator[TestClient]:
    app.dependency_overrides[get_engine] = lambda: app_engine
    app.dependency_overrides[get_provider] = lambda: harness.provider
    act_as(app)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        if "event" in fields:
            out.append((fields["event"], json.loads(fields["data"])))
    return out


def asked(client: TestClient, harness: Harness, base: str, **body: Any) -> list[Any]:
    harness.transport.add(f.structured({"question_type": "out_of_scope"}))
    response = client.post(f"{base}/ask/stream", json=body)
    assert response.status_code == 200, response.text
    return events(response.text)


def test_a_question_starts_a_conversation_the_next_continues_it(
    client: TestClient, harness: Harness, golden_stockout: dict[str, Any]
) -> None:
    base = f"/api/v1/stores/{golden_stockout['id']}"
    first = asked(client, harness, base, question="Should I hire someone?")
    kinds = [k for k, _ in first]
    assert (kinds[0], kinds[-2:]) == ("conversation", ["answer", "done"])
    conversation = first[0][1]["conversation_id"]
    asked(client, harness, base, question="And a designer?", conversation_id=conversation)

    listed = client.get(f"{base}/conversations").json()["items"]
    mine = next(c for c in listed if c["conversation_id"] == conversation)
    assert (mine["title"], mine["questions"]) == ("Should I hire someone?", 2)
    read = client.get(f"{base}/conversations/{conversation}").json()
    turns = read["turns"]
    assert [(t["position"], t["question"], t["via"]) for t in turns] == [
        (1, "Should I hire someone?", "text"),
        (2, "And a designer?", "text"),
    ]
    answer = turns[0]["answer"]  # the answer contract, its facts read again
    assert answer["status"] == "out_of_scope"
    assert {str(i) for i in answer["answer"]["evidence"]} <= set(answer["facts"])
    assert "store" in answer["names"]


def test_the_latest_conversation_comes_first_a_page_at_a_time(
    client: TestClient, harness: Harness, golden_stockout: dict[str, Any]
) -> None:
    base = f"/api/v1/stores/{golden_stockout['id']}"
    older = asked(client, harness, base, question="Older question?")[0][1]["conversation_id"]
    newer = asked(client, harness, base, question="Newer question?")[0][1]["conversation_id"]
    page = client.get(f"{base}/conversations", params={"limit": 1}).json()
    assert [c["conversation_id"] for c in page["items"]] == [newer]
    after = client.get(
        f"{base}/conversations", params={"limit": 1, "cursor": page["next_cursor"]}
    ).json()
    assert [c["conversation_id"] for c in after["items"]] == [older]
    bad = client.get(f"{base}/conversations", params={"cursor": "nope"})
    assert bad.status_code == 422


def test_a_question_about_a_goal_carries_it(
    app_engine: Engine, client: TestClient, harness: Harness, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    base = f"/api/v1/stores/{store}"
    with tenant_transaction(app_engine, store) as conn:
        end = service.data_end(conn, store)
        goal = service.create(
            conn,
            store,
            "net_profit",
            Decimal(50_000),
            end + timedelta(days=30),
            now=datetime.now(UTC),
        )
    topic = {"kind": "goal", "id": str(goal.goal_id), "label": "Net profit of $50,000"}
    streamed = asked(client, harness, base, question="Am I on track?", topic=topic)
    conversation = streamed[0][1]["conversation_id"]
    # The agent reads the question with the goal's label first; the owner's words are kept.
    assert streamed[-2][1]["question"] == "About the goal “Net profit of $50,000”: Am I on track?"
    turn = client.get(f"{base}/conversations/{conversation}").json()["turns"][0]
    assert (turn["question"], turn["topic"]) == ("Am I on track?", topic)


def test_conversations_and_topics_must_be_the_stores(
    client: TestClient, harness: Harness, golden_stockout: dict[str, Any]
) -> None:
    base = f"/api/v1/stores/{golden_stockout['id']}"
    unknown = client.post(
        f"{base}/ask/stream", json={"question": "Why?", "conversation_id": str(uuid4())}
    )
    assert unknown.status_code == 404
    elsewhere = client.post(
        f"{base}/ask/stream",
        json={"question": "Why?", "topic": {"kind": "decision", "id": str(uuid4()), "label": "x"}},
    )
    assert (elsewhere.status_code, elsewhere.json()["code"]) == (422, "invalid_topic")
    assert client.get(f"{base}/conversations/{uuid4()}").status_code == 404


def test_framing_and_titles() -> None:
    topic = Topic(kind="decision", id=uuid4(), label="Pause ‘Trail Jacket’")
    assert framed("What could go wrong?", topic) == (
        "About the decision “Pause ‘Trail Jacket’”: What could go wrong?"
    )
    assert framed("Why?", None) == "Why?"
    assert title_of("  What   is hurting\nmy profit? ") == "What is hurting my profit?"
    long = title_of("word " * 60)
    assert (len(long), long[-1]) == (120, "…")
