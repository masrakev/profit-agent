"""Goals set, confirmed, planned, accepted, tracked and revised; their API, jobs and weekly
report section (app/goals/service.py, app/api/goals.py)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api.deps import get_engine
from app.api.main import app
from app.briefings.content import build
from app.briefings.models import BriefingKind
from app.db import tenant_transaction
from app.decisions.store import Channel, Verdict, decide
from app.decisions.store import get as get_decision
from app.goals import service
from app.goals.service import GoalError
from app.scheduler.jobs import goals_monthly_tick, goals_weekly_tick
from app.verifier import verify
from bench.scenarios.manifest import load_suite
from bench.simulator import advance, register
from tests.api_helpers import act_as
from tests.conftest import create_store

pytestmark = pytest.mark.db
NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def store(app_engine: Engine) -> UUID:
    manifest = next(m for m in load_suite("dev") if m.scenario_id == "dev-cannibalization-07")
    return register(app_engine, manifest, 70)


@pytest.fixture
def client(app_engine: Engine) -> Iterator[TestClient]:
    app.dependency_overrides[get_engine] = lambda: app_engine
    act_as(app)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _end(engine: Engine, store: UUID) -> Any:
    with tenant_transaction(engine, store) as conn:
        return service.data_end(conn, store)


def test_a_goal_is_restated_then_confirmed(app_engine: Engine, store: UUID) -> None:
    end = _end(app_engine, store)
    with tenant_transaction(app_engine, store) as conn:
        goal = service.create(
            conn,
            store,
            "net_profit",
            Decimal("50000"),
            end + timedelta(days=45),
            now=NOW,
            question="I want 50,000 in net profit in six weeks",
        )
        assert (goal.status, goal.as_of, goal.horizon) == ("draft", end, 45)
        words = service.restate(goal)
        assert f"{{{{F{goal.target_fact_id}}}}}" in words
        assert (end + timedelta(days=44)).isoformat() in words
        assert not verify(words)
        assessment = service.confirm(conn, store, goal.goal_id, now=NOW)
        again = service.confirm(conn, store, goal.goal_id, now=NOW)  # confirming twice is fine
        confirmed = service.get(conn, store, goal.goal_id)
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_at is not None
    assert assessment.probability.id == again.probability.id
    assert assessment.feasibility.horizon == 45
    assert sorted(assessment.forecast)[-1] == 45


def test_invalid_goals(app_engine: Engine, store: UUID) -> None:
    end = _end(app_engine, store)
    with tenant_transaction(app_engine, store) as conn:
        for metric, days in (("units", 30), ("revenue", 0), ("revenue", 200)):
            with pytest.raises(GoalError) as caught:
                service.create(conn, store, metric, Decimal(1), end + timedelta(days=days), now=NOW)
            assert caught.value.code == "invalid_goal"
        with pytest.raises(GoalError, match="no such goal"):
            service.get(conn, store, uuid4())
        with pytest.raises(GoalError, match="no such plan"):
            service.get_plan(conn, store, uuid4())
    empty = create_store(app_engine)
    with tenant_transaction(app_engine, empty) as conn, pytest.raises(GoalError) as caught:
        service.create(conn, empty, "revenue", Decimal(1), end, now=NOW)
    assert caught.value.code == "no_data"


def test_plan_accept_track_and_report(app_engine: Engine, store: UUID) -> None:
    end = _end(app_engine, store)
    with tenant_transaction(app_engine, store) as conn:
        goal = service.create(
            conn, store, "net_profit", Decimal("200000"), end + timedelta(days=40), now=NOW
        )
        with pytest.raises(GoalError) as caught:
            service.make_plan(conn, store, goal.goal_id, now=NOW)
        assert caught.value.code == "not_confirmed"
        service.confirm(conn, store, goal.goal_id, now=NOW)
        first = service.make_plan(conn, store, goal.goal_id, now=NOW)
        plan = service.make_plan(conn, store, goal.goal_id, now=NOW)  # supersedes the first
        assert service.get_plan(conn, store, first.plan_id).status == "superseded"
        assert plan.status == "proposed"
        assert plan.days == 40
        payload = plan.payload
        assert len(payload["milestones"]) == 6  # weeks 1 to 5, and day 40
        assert payload["shows_point"] is True
        assert payload["checkpoints"] == []
        assert len(payload["assumptions"]) == 5
        assert "yearly seasonality not learned" in payload["low_evidence"]  # under a year of data
        assert all(not verify(s.summary) for s in plan.steps)
        assert service.track(conn, store, goal.goal_id, now=NOW) is None  # no accepted plan
        accepted = service.accept(conn, store, plan.plan_id, now=NOW, actor="owner:test")
        with pytest.raises(GoalError, match="the plan is accepted"):
            service.accept(conn, store, plan.plan_id, now=NOW, actor="owner:test")
        assert service.get(conn, store, goal.goal_id).status == "planned"
        assert service.current_plan(conn, store, goal.goal_id) == accepted
        for step in accepted.steps:
            if step.kind == "decision":
                assert step.status == "proposed"
                assert step.decision_id is not None
                decision = get_decision(conn, store, step.decision_id)
                assert decision.source == "goal"
        assert service.track(conn, store, goal.goal_id, now=NOW) is None  # day zero
    advance(app_engine, store, 7)
    with tenant_transaction(app_engine, store) as conn:
        week = service.track(conn, store, goal.goal_id, now=NOW)
        assert week is not None
        assert service.track(conn, store, goal.goal_id, now=NOW) == week  # once a day
        assert (week.kind, week.day, week.plan_id) == ("weekly", 7, plan.plan_id)
        decisions = [s for s in accepted.steps if s.kind == "decision"]
        assert decisions
        # its steps wait for the owner: no milestone judgement, no revision, a prompt instead
        assert week.status == "waiting_for_approval"
        assert not week.revision_proposed
        assert week.reason == service.APPROVAL_PROMPT
        assert week.adherence["awaiting_approval"] == len(decisions)
        assert week.milestone_fact_id is not None
        assert week.probability_fact_id is not None
        assert week.adherence["due"] == len(
            [s for s in accepted.steps if s.due_date <= end + timedelta(days=7)]
        )
        content = build(
            conn, store, BriefingKind.WEEKLY, local_today=end + timedelta(days=7), now=NOW
        )
    [goals] = [s for s in content.sections if s.key == "goals"]
    [item] = goals.items
    assert item.text.startswith("Your goal of {{F")
    assert "waiting for your approval" in item.text
    assert "revision" not in item.text
    assert item.decision_id in {str(s.decision_id) for s in decisions}
    assert item.buttons
    assert not verify(item.text)
    with tenant_transaction(app_engine, store) as conn:  # the owner decides: here, no
        for s in decisions:
            assert s.decision_id is not None
            decide(
                conn,
                store,
                s.decision_id,
                None,
                Verdict.REJECTED,
                channel=Channel.API,
                actor="owner:test",
                now=NOW,
            )
    advance(app_engine, store, 7)
    with tenant_transaction(app_engine, store) as conn:
        second = service.track(conn, store, goal.goal_id, now=NOW)
        assert second is not None
        assert second.status in ("ahead", "on_track", "behind")  # judged by its milestones
        assert second.adherence["skipped"] == len(decisions)
        assert [p.progress_id for p in service.progress(conn, store, goal.goal_id)] == [
            week.progress_id,
            second.progress_id,
        ]


def test_revision_reforecast_and_jobs(app_engine: Engine, store: UUID) -> None:
    end = _end(app_engine, store)
    with tenant_transaction(app_engine, store) as conn:
        long = service.create(
            conn, store, "revenue", Decimal("10"), end + timedelta(days=120), now=NOW
        )
        assert service.reforecast(conn, store, long.goal_id, now=NOW) is None  # a draft
        service.confirm(conn, store, long.goal_id, now=NOW)
        plan = service.make_plan(conn, store, long.goal_id, now=NOW)
        assert plan.days == 90  # the first 90 days in detail
        assert plan.payload["shows_point"] is False
        assert len(plan.payload["checkpoints"]) == 2
        refreshed = service.reforecast(conn, store, long.goal_id, now=NOW)
        assert refreshed is not None
        assert refreshed.kind == "reforecast"
        assert refreshed.verdict == "likely-likely"  # a tiny target, as a band
        short = service.create(
            conn, store, "revenue", Decimal("10"), end + timedelta(days=30), now=NOW
        )
        service.confirm(conn, store, short.goal_id, now=NOW)
        assert service.reforecast(conn, store, short.goal_id, now=NOW) is None  # within 90 days
        revised = service.revise(
            conn,
            store,
            long.goal_id,
            now=NOW,
            target=Decimal("20"),
            deadline=end + timedelta(days=100),
        )
        assert (revised.target, revised.status, revised.horizon) == (
            Decimal("20"),
            "confirmed",
            100,
        )
        assert service.get_plan(conn, store, plan.plan_id).status == "superseded"
        conn.execute(
            text("UPDATE goals SET status = 'cancelled' WHERE store_id = :s AND goal_id = :g"),
            {"s": store, "g": short.goal_id},
        )
        with pytest.raises(GoalError, match="the goal is cancelled"):
            service.revise(conn, store, short.goal_id, now=NOW, target=Decimal(1))
        assert short.goal_id not in {g.goal_id for g in service.active_goals(conn, store)}
    assert goals_monthly_tick(app_engine, NOW, only=[store])
    assert all(d.ok for d in goals_weekly_tick(app_engine, NOW, only=[store]))


def test_a_goal_past_its_deadline_is_closed(app_engine: Engine, store: UUID) -> None:
    end = _end(app_engine, store)
    with tenant_transaction(app_engine, store) as conn:
        goal = service.create(
            conn, store, "revenue", Decimal("1"), end + timedelta(days=7), now=NOW
        )
        service.confirm(conn, store, goal.goal_id, now=NOW)
        plan = service.make_plan(conn, store, goal.goal_id, now=NOW)
        service.accept(conn, store, plan.plan_id, now=NOW, actor="owner:test")
    advance(app_engine, store, 7)
    with tenant_transaction(app_engine, store) as conn:
        week = service.track(conn, store, goal.goal_id, now=NOW)
        assert week is not None
        assert week.probability_fact_id is None
        assert week.reason == "the deadline has passed: the goal is achieved"
        assert service.get(conn, store, goal.goal_id).status == "achieved"
        with pytest.raises(GoalError, match="deadline has passed"):
            service.make_plan(conn, store, goal.goal_id, now=NOW)


def test_the_goals_api(client: TestClient, app_engine: Engine, store: UUID) -> None:
    end = _end(app_engine, store)
    base = f"/api/v1/stores/{store}/goals"
    bad = client.post(base, json={"metric": "revenue", "target": "100", "deadline": "2099-01-01"})
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_goal")
    made = client.post(
        base,
        json={
            "metric": "revenue",
            "target": "100000",
            "deadline": (end + timedelta(days=30)).isoformat(),
        },
    )
    assert made.status_code == 201, made.text
    goal = made.json()
    assert goal["status"] == "draft"
    assert str(goal["target_fact_id"]) in goal["facts"]
    gid = goal["goal_id"]
    assert client.get(f"{base}/{gid}/feasibility").json()["code"] == "not_confirmed"
    feas = client.post(f"{base}/{gid}/confirm").json()
    assert feas["verdict"] in ("likely", "possible", "stretch", "unlikely")
    assert feas["probability"] is not None
    assert str(feas["probability_fact_id"]) in feas["facts"]
    assert (
        client.get(f"{base}/{gid}/feasibility").json()["probability_fact_id"]
        == feas["probability_fact_id"]
    )
    plan = client.post(f"{base}/{gid}/plans").json()
    assert plan["status"] == "proposed"
    assert str(plan["payload"]["probability_with_fact_id"]) in plan["facts"]
    assert [p["plan_id"] for p in client.get(f"{base}/{gid}/plans").json()] == [plan["plan_id"]]
    other = client.post(f"{base}/{uuid4()}/plans/{plan['plan_id']}/accept")
    assert other.status_code == 404
    accepted = client.post(f"{base}/{gid}/plans/{plan['plan_id']}/accept").json()
    assert accepted["status"] == "accepted"
    assert client.get(f"{base}/{gid}/progress").json() == []
    assert client.get(base).json()[0]["goal_id"] == gid
    assert client.get(f"{base}/{gid}").json()["status"] == "planned"
    revised = client.post(f"{base}/{gid}/revise", json={"target": "90000"}).json()
    assert revised["status"] == "confirmed"
    assert client.get(f"{base}/{uuid4()}").status_code == 404
    assert client.get(f"{base}/{uuid4()}/plans").status_code == 404
    assert client.get(f"{base}/{uuid4()}/progress").status_code == 404
    long = client.post(
        base,
        json={
            "metric": "revenue",
            "target": "100000",
            "deadline": (end + timedelta(days=150)).isoformat(),
        },
    ).json()
    far = client.post(f"{base}/{long['goal_id']}/confirm").json()
    assert (far["verdict"], far["probability"]) == (None, None)
    assert [c["day"] for c in far["checkpoints"]] == [90, 150]
    assert far["low_evidence"][-1] == "yearly seasonality not learned"
    assert client.post(f"{base}/{uuid4()}/revise", json={}).status_code == 404
    assert client.post(f"{base}/{uuid4()}/confirm").status_code == 404
