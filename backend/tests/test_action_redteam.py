"""Action red team (Task 4 B6): attempts to approve twice, replay or outlive links, exceed the
caps, act twice in a day, act under a kill switch, crash mid-execution, and platform errors.

Targets: 0 duplicate executions, 0 actions outside policy, every failure recorded. The crash,
error and timeout cases are in test_executor.py; this module adds the approval and policy
attacks, then checks the targets over every action the two modules executed or refused.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

from app.api.deps import get_app_settings, get_engine, get_owner_engine
from app.api.main import app
from app.config import get_settings
from app.db import tenant_transaction
from app.decisions.store import Verdict, create_link, propose, read_link
from app.facts.engine import FactEngine
from app.policies.engine import set_global_switch
from app.twin import fit_twin
from tests.action_helpers import (
    Rig,
    actions,
    approved,
    audit_actions,
    option_set,
    simulator_store,
)

pytestmark = pytest.mark.db
SECRET = "redteam-link-secret"
ADMIN = "redteam-admin-token"
RESULTS: list[dict[str, Any]] = []


@pytest.fixture(scope="module")
def sim(app_engine: Engine) -> dict[str, Any]:
    return simulator_store(app_engine, "dev-refund_spike-04")


@pytest.fixture
def client(app_engine: Engine, owner_engine: Engine) -> Iterator[TestClient]:
    settings = get_settings().model_copy(
        update={"approval_link_secret": SecretStr(SECRET), "admin_token": SecretStr(ADMIN)}
    )
    app.dependency_overrides[get_engine] = lambda: app_engine
    app.dependency_overrides[get_owner_engine] = lambda: owner_engine
    app.dependency_overrides[get_app_settings] = lambda: settings
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def proposed(engine: Engine, store: UUID, campaign: UUID, change: str | None, label: str) -> Any:
    with tenant_transaction(engine, store) as conn:
        model = fit_twin(conn, store)
        return propose(
            conn,
            FactEngine(conn, store),
            model,
            option_set(campaign, change=change, label=label),
            source="owner",
        )


def record(case: str, ok: bool, detail: str) -> None:
    RESULTS.append({"case": case, "ok": ok, "detail": detail})
    assert ok, detail


def test_two_channels_decide_once(
    app_engine: Engine, sim: dict[str, Any], client: TestClient
) -> None:
    d = proposed(app_engine, sim["id"], sim["campaigns"][0], None, "two-channels")
    link = client.post(
        f"/api/v1/stores/{sim['id']}/decisions/{d.decision_id}/links",
        json={"option_id": d.recommended_option_id},
    ).json()["token"]
    web = client.post(
        f"/api/v1/stores/{sim['id']}/decisions/{d.decision_id}/approve",
        json={"option_id": d.recommended_option_id},
    )
    email = client.get(f"/api/v1/approval-links/{link}")
    again = client.post(f"/api/v1/stores/{sim['id']}/decisions/{d.decision_id}/reject")
    with tenant_transaction(app_engine, sim["id"]) as conn:
        approvals = conn.execute(
            text("SELECT count(*) FROM approvals WHERE decision_id = :d"), {"d": d.decision_id}
        ).scalar_one()
    record(
        "double approval, two channels",
        web.status_code == 200
        and email.status_code == 409
        and again.status_code == 409
        and approvals == 1
        and len(actions(app_engine, sim["id"], d.decision_id)) == 1,
        f"web {web.status_code}, email {email.status_code}, reject {again.status_code}, "
        f"approvals {approvals}",
    )


def test_links_are_single_use_and_expire(
    app_engine: Engine, sim: dict[str, Any], client: TestClient
) -> None:
    d = proposed(app_engine, sim["id"], sim["campaigns"][1], None, "replay")
    token = client.post(
        f"/api/v1/stores/{sim['id']}/decisions/{d.decision_id}/links",
        json={"option_id": d.recommended_option_id, "verdict": "rejected"},
    ).json()["token"]
    first = client.get(f"/api/v1/approval-links/{token}")
    replay = client.get(f"/api/v1/approval-links/{token}")
    record(
        "replayed email link",
        first.status_code == 200 and replay.status_code == 409,
        f"first {first.status_code}, replay {replay.status_code}",
    )
    late = proposed(app_engine, sim["id"], sim["campaigns"][1], None, "expired")
    with tenant_transaction(app_engine, sim["id"]) as conn:
        old = create_link(
            conn,
            sim["id"],
            late.decision_id,
            late.recommended_option_id,
            Verdict.APPROVED,
            secret=SECRET,
            now=late.created_at - timedelta(hours=25),
        )
    expired = client.get(f"/api/v1/approval-links/{old}")
    forged = client.get(f"/api/v1/approval-links/{token[:-4]}AAAA")
    record(
        "expired and forged links",
        expired.status_code == 410 and forged.status_code == 403,
        f"expired {expired.status_code}, forged {forged.status_code}",
    )
    claims = read_link(token, secret=SECRET)
    assert claims.verdict is Verdict.REJECTED


def test_above_the_cap_approval_and_execution(
    app_engine: Engine, sim: dict[str, Any], client: TestClient
) -> None:
    campaign = sim["campaigns"][2]
    d = proposed(app_engine, sim["id"], campaign, "1.0", "above-cap")
    token = client.post(
        f"/api/v1/stores/{sim['id']}/decisions/{d.decision_id}/links",
        json={"option_id": d.recommended_option_id},
    ).json()["token"]
    opened = client.get(f"/api/v1/approval-links/{token}").json()
    record(
        "approval above cap by email link",
        opened["confirmation_required"] and opened["decision"]["status"] == "proposed",
        f"confirmation {opened['confirmation_required']}, status {opened['decision']['status']}",
    )
    # Approved on the web, the change still cannot execute beyond the cap.
    client.post(
        f"/api/v1/stores/{sim['id']}/decisions/{d.decision_id}/approve",
        json={"option_id": d.recommended_option_id},
    )
    rig = Rig(app_engine)
    rig.executor().run_once()
    [action] = actions(app_engine, sim["id"], d.decision_id)
    record(
        "budget change beyond +-30%",
        action.status == "blocked" and "budget_cap" in action.last_error,
        f"{action.status}: {action.last_error}",
    )


def test_a_second_change_within_a_day(app_engine: Engine, sim: dict[str, Any]) -> None:
    campaign = sim["campaigns"][3 % len(sim["campaigns"])]
    rig = Rig(app_engine)
    rig.clock.advance(days=40)
    first = approved(
        app_engine, sim["id"], option_set(campaign, change="-0.1", label="day-1"), now=rig.clock.now
    )
    rig.executor().run_once()
    rig.clock.advance(hours=3)
    second = approved(
        app_engine, sim["id"], option_set(campaign, change="-0.2", label="day-2"), now=rig.clock.now
    )
    rig.executor().run_once()
    [a1] = actions(app_engine, sim["id"], first.decision_id)
    [a2] = actions(app_engine, sim["id"], second.decision_id)
    record(
        "second change within 24 h",
        a1.status == "executed" and a2.status == "blocked" and "change_frequency" in a2.last_error,
        f"{a1.status}, {a2.status}",
    )


def test_kill_switches(
    app_engine: Engine, owner_engine: Engine, sim: dict[str, Any], client: TestClient
) -> None:
    campaign = sim["campaigns"][0]
    rig = Rig(app_engine)
    rig.clock.advance(days=60)
    on = client.put(f"/api/v1/stores/{sim['id']}/kill-switch", json={"enabled": True})
    d = approved(
        app_engine,
        sim["id"],
        option_set(campaign, change="0.1", label="store-switch"),
        now=rig.clock.now,
    )
    rig.executor().run_once()
    [blocked] = actions(app_engine, sim["id"], d.decision_id)
    client.put(f"/api/v1/stores/{sim['id']}/kill-switch", json={"enabled": False})
    record(
        "store kill switch on",
        on.status_code == 200
        and blocked.status == "blocked"
        and "store_kill_switch" in blocked.last_error,
        f"{blocked.status}: {blocked.last_error}",
    )
    denied = client.put(
        "/api/v1/admin/kill-switch", json={"enabled": True}, headers={"X-Admin-Token": "wrong"}
    )
    allowed = client.put(
        "/api/v1/admin/kill-switch",
        json={"enabled": True, "reason": "test"},
        headers={"X-Admin-Token": ADMIN},
    )
    rig.clock.advance(days=2)
    g = approved(
        app_engine, sim["id"], option_set(campaign, change="0.1", label="global"), now=rig.clock.now
    )
    rig.executor().run_once()
    [stopped] = actions(app_engine, sim["id"], g.decision_id)
    with owner_engine.begin() as conn:
        set_global_switch(conn, False, actor="test")
    record(
        "global kill switch on",
        denied.status_code == 403
        and allowed.status_code == 200
        and stopped.status == "blocked"
        and "global_kill_switch" in stopped.last_error,
        f"{denied.status_code}, {allowed.status_code}, {stopped.status}",
    )


def test_targets_over_every_action(
    app_engine: Engine, sim: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """0 duplicate executions, 0 actions outside policy, every failure recorded."""
    assert RESULTS, "run the whole module"
    with tenant_transaction(app_engine, sim["id"]) as conn:
        rows = conn.execute(
            text("SELECT action_id, status FROM actions WHERE store_id = :s"), {"s": sim["id"]}
        ).all()
    executed = audit_actions(app_engine, sim["id"], "action.executed")
    policy = audit_actions(app_engine, sim["id"], "policy.evaluated")
    failures = audit_actions(app_engine, sim["id"], "action.blocked") + audit_actions(
        app_engine, sim["id"], "action.failed"
    )
    per_action: dict[str, int] = {}
    for e in executed:
        per_action[e.payload["action_id"]] = per_action.get(e.payload["action_id"], 0) + 1
    duplicates = sum(n - 1 for n in per_action.values() if n > 1)
    last_verdict = {p.payload["action_id"]: p.payload["allowed"] for p in policy}
    outside = [a for a in per_action if last_verdict.get(a) is not True]
    refused = {str(r.action_id) for r in rows if r.status in ("blocked", "failed")}
    recorded = {f.payload["action_id"] for f in failures}
    RESULTS.append(
        {
            "case": "targets",
            "ok": True,
            "detail": f"{len(per_action)} executed, {len(refused)} refused",
        }
    )
    with capsys.disabled():
        print("\naction red team | ok | detail")
        for r in RESULTS:
            print(f"{r['case']} | {r['ok']} | {r['detail']}")
    assert duplicates == 0
    assert outside == []
    assert refused <= recorded
