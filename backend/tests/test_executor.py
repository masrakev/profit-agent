"""The outbox worker: policy, dry run, execution, read-back, audit, retries, rollback; the Meta
adapter against the documented contract; SKIP LOCKED claiming."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy import Engine, text

from app.db import tenant_transaction
from app.decisions.store import DecisionStatus, get
from app.executor.adapters import AdapterError, CampaignRef, CampaignState, Change
from app.executor.meta import MetaAdsAdapter
from app.executor.worker import MAX_ATTEMPTS, Executor, request_rollback
from bench.meta_fake import (
    ACCOUNT,
    FakeCampaign,
    FakeGraph,
    permission_denied,
    rate_limited,
    server_error,
)
from tests.action_helpers import (
    Rig,
    actions,
    approved,
    audit_actions,
    campaign_row,
    option_set,
    simulator_store,
)

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def sim(app_engine: Engine) -> dict[str, Any]:
    return simulator_store(app_engine, "dev-cpa_drift-03")


def meta_rig(engine: Engine, sim: dict[str, Any], campaign: Any) -> tuple[Rig, FakeGraph]:
    graph = FakeGraph(campaigns={"120200000001": FakeCampaign()})
    adapter = MetaAdsAdapter(
        access_token="test-token",
        ad_account_id=ACCOUNT,
        transport=graph.transport(),
    )
    rig = Rig(engine, extra={"meta": adapter}, meta_links={str(campaign): "120200000001"})
    return rig, graph


def test_a_pause_runs_end_to_end_on_the_simulator(app_engine: Engine, sim: dict[str, Any]) -> None:
    campaign = sim["campaigns"][0]
    rig = Rig(app_engine)
    rig.executor().run_once()  # rows other test modules left ready, in their own stores
    d = approved(app_engine, sim["id"], option_set(campaign, label="pause-sim"))
    assert rig.executor().run_once() == 1
    [action] = actions(app_engine, sim["id"], d.decision_id)
    assert (action.status, action.outbox_status, action.provider) == (
        "executed",
        "done",
        "simulator",
    )
    assert action.before_state["status"] == "ACTIVE"
    assert action.after_state["status"] == "PAUSED"
    assert action.after_state["effective_date"]
    assert campaign_row(app_engine, sim["id"], campaign).status == "paused"
    with tenant_transaction(app_engine, sim["id"]) as conn:
        events = conn.execute(
            text("SELECT events FROM simulator_stores WHERE store_id = :s"), {"s": sim["id"]}
        ).scalar_one()
        assert get(conn, sim["id"], d.decision_id).status is DecisionStatus.EXECUTED
    assert events[-1]["status"] == "PAUSED"
    policy = audit_actions(app_engine, sim["id"], "policy.evaluated")
    assert policy[-1].payload["rule"] == "allowed"
    executed = audit_actions(app_engine, sim["id"], "action.executed")
    assert executed[-1].payload["idempotency_key"] == action.idempotency_key
    assert rig.executor().run_once() == 0  # nothing left

    # Rollback: resume, exempt from the one-change-per-day rule.
    with tenant_transaction(app_engine, sim["id"]) as conn:
        request_rollback(conn, sim["id"], action.action_id, actor="owner", now=rig.clock())
    assert rig.executor().run_once() == 1
    resume = actions(app_engine, sim["id"], d.decision_id)[-1]
    assert (resume.kind, resume.status, resume.rollback_of) == (
        "resume_campaign",
        "executed",
        action.action_id,
    )
    assert campaign_row(app_engine, sim["id"], campaign).status == "active"
    with (
        tenant_transaction(app_engine, sim["id"]) as conn,
        pytest.raises(LookupError, match="does not exist"),
    ):
        request_rollback(conn, sim["id"], d.decision_id, actor="owner")  # not an action


def test_meta_adapter_follows_the_documented_contract(
    app_engine: Engine, sim: dict[str, Any]
) -> None:
    campaign = sim["campaigns"][1]
    rig, graph = meta_rig(app_engine, sim, campaign)
    budget_before = campaign_row(app_engine, sim["id"], campaign).daily_budget
    graph.campaigns["120200000001"].daily_budget = int(budget_before * 100)
    d = approved(
        app_engine,
        sim["id"],
        option_set(campaign, change="-0.2", label="meta"),
        meta_links=rig.meta_links,
    )
    rig.clock.advance(days=2)
    assert rig.executor().run_once() == 1
    [action] = actions(app_engine, sim["id"], d.decision_id)
    assert (action.provider, action.status) == ("meta", "executed")
    cents = str(int((budget_before * 100 * Decimal("0.8")).to_integral_value()))
    assert str(graph.campaigns["120200000001"].daily_budget) == cents  # minor units
    assert graph.mutations == 1
    posts = [c for c in graph.calls if c[0] == "POST"]
    assert posts[0][2] == {"daily_budget": cents, "execution_options": '["validate_only"]'}
    assert posts[1][2] == {"daily_budget": cents}
    gets = [c for c in graph.calls if c[0] == "GET"]
    assert gets[0][2]["fields"] == "status,effective_status,daily_budget,account_id"
    # A synthetic store linked to a sandbox campaign: the simulator mirrors the change.
    assert campaign_row(app_engine, sim["id"], campaign).daily_budget == Decimal(cents) / 100
    with tenant_transaction(app_engine, sim["id"]) as conn:
        events = conn.execute(
            text("SELECT events FROM simulator_stores WHERE store_id = :s"), {"s": sim["id"]}
        ).scalar_one()
    assert events[-1]["campaign_id"] == str(campaign)


def test_the_adapter_refuses_another_account_and_maps_errors() -> None:
    graph = FakeGraph(campaigns={"9": FakeCampaign(account_id="999")})
    adapter = MetaAdsAdapter(
        access_token="t",
        ad_account_id=ACCOUNT,
        transport=graph.transport(),
    )
    ref = CampaignRef(store_id=uuid4(), campaign_id=uuid4(), external_id="9", currency="USD")
    with pytest.raises(AdapterError, match="does not belong") as refused:
        adapter.apply(ref, Change(status="PAUSED"))
    assert not refused.value.retryable
    assert graph.mutations == 0
    graph.campaigns["9"].account_id = "1234567890"
    graph.failures = [
        rate_limited(),
        server_error(),
        permission_denied(),
        httpx2.ReadTimeout("slow"),
    ]
    for retryable in (True, True, False, True):
        with pytest.raises(AdapterError) as err:
            adapter.apply(ref, Change(status="PAUSED"))
        assert err.value.retryable is retryable
    with pytest.raises(AdapterError, match="Invalid parameter"):
        adapter.read(CampaignRef(ref.store_id, ref.campaign_id, "unknown", "USD"))


def test_a_crash_between_execution_and_audit_never_executes_twice(
    app_engine: Engine, sim: dict[str, Any]
) -> None:
    campaign = sim["campaigns"][2]
    rig, graph = meta_rig(app_engine, sim, campaign)

    def crash(_: Any) -> None:
        raise SystemExit("worker killed after the platform call")

    rig.after_apply = crash
    d = approved(
        app_engine, sim["id"], option_set(campaign, label="crash"), meta_links=rig.meta_links
    )
    with pytest.raises(SystemExit):
        rig.executor().run_once()
    assert graph.mutations == 1
    [action] = actions(app_engine, sim["id"], d.decision_id)
    assert action.status == "executing"  # claimed, never finished
    rig.after_apply = None
    assert rig.executor().run_once() == 0  # still leased
    rig.clock.advance(minutes=6)
    assert rig.executor().run_once() == 1
    [action] = actions(app_engine, sim["id"], d.decision_id)
    assert (action.status, action.outbox_status) == ("executed", "done")
    assert graph.mutations == 1  # read before writing: already paused, not paused again
    done = [
        a
        for a in audit_actions(app_engine, sim["id"], "action.executed")
        if a.payload["action_id"] == str(action.action_id)
    ]
    assert len(done) == 1
    assert done[0].payload["already_applied"] is True


def test_retries_then_failure_are_recorded(app_engine: Engine, sim: dict[str, Any]) -> None:
    campaign = sim["campaigns"][0]
    rig, graph = meta_rig(app_engine, sim, campaign)
    graph.campaigns["120200000001"] = FakeCampaign()
    graph.failures = [rate_limited(), httpx2.ReadTimeout("slow")]
    rig.clock.advance(days=5)
    d = approved(
        app_engine,
        sim["id"],
        option_set(campaign, label="retry"),
        meta_links=rig.meta_links,
        now=rig.clock.now,
    )
    executor = rig.executor()
    for _ in range(2):
        assert executor.run_once() == 1
        [action] = actions(app_engine, sim["id"], d.decision_id)
        assert (action.status, action.outbox_status) == ("pending", "pending")
        assert executor.run_once() == 0  # backoff
        rig.clock.advance(hours=2)
    assert executor.run_once() == 1
    [action] = actions(app_engine, sim["id"], d.decision_id)
    assert action.status == "executed"
    assert graph.mutations == 1
    retries = audit_actions(app_engine, sim["id"], "action.retry_scheduled")
    assert len([r for r in retries if r.payload["action_id"] == str(action.action_id)]) == 2

    # A refusal from the platform fails the action and its decision at once.
    other = sim["campaigns"][1]
    rig2, graph2 = meta_rig(app_engine, sim, other)
    graph2.failures = [permission_denied()]
    rig2.clock.advance(days=10)
    d2 = approved(
        app_engine,
        sim["id"],
        option_set(other, label="refused"),
        meta_links=rig2.meta_links,
        now=rig2.clock.now,
    )
    assert rig2.executor().run_once() == 1
    [failed] = actions(app_engine, sim["id"], d2.decision_id)
    assert (failed.status, failed.outbox_status) == ("failed", "failed")
    assert "code 200" in failed.last_error
    with tenant_transaction(app_engine, sim["id"]) as conn:
        assert get(conn, sim["id"], d2.decision_id).status is DecisionStatus.FAILED
    assert MAX_ATTEMPTS >= 2


def test_a_locked_row_is_skipped(app_engine: Engine, sim: dict[str, Any]) -> None:
    campaign = sim["campaigns"][2]
    rig = Rig(app_engine)
    rig.clock.advance(days=20)
    d = approved(
        app_engine, sim["id"], option_set(campaign, change="0.1", label="locked"), now=rig.clock.now
    )
    [action] = actions(app_engine, sim["id"], d.decision_id)
    with (
        tenant_transaction(app_engine, sim["id"]) as conn,
        pytest.raises(ValueError, match="only an executed action"),
    ):
        request_rollback(conn, sim["id"], action.action_id, actor="owner")
    with tenant_transaction(app_engine, sim["id"]) as other:
        other.execute(
            text("SELECT 1 FROM outbox WHERE action_id = :a FOR UPDATE"), {"a": action.action_id}
        )
        assert rig.executor().run_once() == 0  # another worker holds it
    assert rig.executor().run_once() == 1
    restore = Executor.target(
        "change_budget", {"daily_budget_minor": 1234}, CampaignState("ACTIVE", 1000)
    )
    assert restore.daily_budget_minor == 1234


def test_the_worker_command(monkeypatch: pytest.MonkeyPatch, app_engine: Engine) -> None:
    from pydantic import SecretStr

    from app.config import get_settings
    from app.executor import __main__ as command

    settings = get_settings().model_copy(
        update={"meta_access_token": SecretStr("t"), "meta_ad_account_id": ACCOUNT}
    )
    monkeypatch.setattr(command, "get_settings", lambda: settings)
    monkeypatch.setattr(command, "make_engine", lambda url: app_engine)
    built = command.build()
    assert set(built.adapters) == {"simulator", "meta"}
    monkeypatch.setattr(Executor, "run_once", lambda self: 0)
    assert command.main([]) == 0
