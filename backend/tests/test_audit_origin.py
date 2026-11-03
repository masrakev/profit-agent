"""The audit log answers, in one query, who decided an action, by which channel, with which
session or API token, from which request and user agent, and what then carried it out."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

from app.api.auth import get_principal
from app.api.deps import get_app_settings, get_engine, get_owner_engine
from app.api.main import app
from app.auth.service import Principal
from app.config import get_settings
from app.db import tenant_transaction
from app.decisions.store import propose, read_link
from app.facts.engine import FactEngine
from app.twin import fit_twin
from tests.action_helpers import Rig, option_set, simulator_store
from tests.api_helpers import AnyStore

pytestmark = pytest.mark.db
SECRET = "audit-origin-link-secret"
OWNER = "owner:owner@example.com"
SESSION = uuid4()
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/142"

# Who decided each action, as one query reads it from the log.
WHO = """
SELECT seq, action, actor,
       COALESCE(payload->>'channel', payload->'authorized_by'->>'channel') AS channel,
       COALESCE(payload->'origin', payload->'authorized_by'->'origin') AS origin,
       payload->'authorized_by'->>'actor' AS decided_by
FROM audit_log
WHERE store_id = :s
  AND action IN ('decision.approved', 'decision.rejected', 'action.rollback_requested',
                 'action.executed', 'action.failed')
  AND (payload->>'decision_id' = :d OR payload->>'action_id' = ANY(:a))
ORDER BY seq
"""


@pytest.fixture(scope="module")
def sim(app_engine: Engine) -> dict[str, Any]:
    return simulator_store(app_engine, "dev-refund_spike-06")


@pytest.fixture
def client(app_engine: Engine, owner_engine: Engine) -> Iterator[TestClient]:
    settings = get_settings().model_copy(update={"approval_link_secret": SecretStr(SECRET)})
    app.dependency_overrides[get_engine] = lambda: app_engine
    app.dependency_overrides[get_owner_engine] = lambda: owner_engine
    app.dependency_overrides[get_app_settings] = lambda: settings
    owner = Principal(kind="session", store_ids=AnyStore(), label=OWNER, session_id=SESSION)
    app.dependency_overrides[get_principal] = lambda: owner
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def proposed(engine: Engine, store: UUID, campaign: UUID, label: str) -> Any:
    with tenant_transaction(engine, store) as conn:
        return propose(
            conn,
            FactEngine(conn, store),
            fit_twin(conn, store),
            option_set(campaign, label=label),
            source="owner",
        )


def who(engine: Engine, store: UUID, decision: UUID) -> list[Any]:
    with tenant_transaction(engine, store) as conn:
        actions = [
            str(a)
            for a in conn.execute(
                text("SELECT action_id FROM actions WHERE decision_id = :d"), {"d": decision}
            ).scalars()
        ]
        return list(conn.execute(text(WHO), {"s": store, "d": str(decision), "a": actions}))


def test_a_web_approval_and_its_execution_say_who_and_from_where(
    app_engine: Engine, sim: dict[str, Any], client: TestClient
) -> None:
    d = proposed(app_engine, sim["id"], sim["campaigns"][0], "web")
    approved = client.post(
        f"/api/v1/stores/{sim['id']}/decisions/{d.decision_id}/approve",
        json={"option_id": d.recommended_option_id},
        headers={"User-Agent": BROWSER, "X-Request-ID": "req-web-approve-0001"},
    )
    assert approved.status_code == 200, approved.text
    Rig(app_engine).executor().run_once()

    approval, executed = who(app_engine, sim["id"], d.decision_id)
    origin = {
        "session_id": str(SESSION),
        "token_id": None,
        "request_id": "req-web-approve-0001",
        "user_agent": BROWSER,
        "link_id": None,
    }
    assert (approval.action, approval.actor, approval.channel) == (
        "decision.approved",
        OWNER,
        "api",
    )
    assert approval.origin == origin
    assert (executed.action, executed.actor, executed.decided_by) == (
        "action.executed",
        "system:executor",
        OWNER,
    )
    assert (executed.channel, executed.origin) == ("api", origin)

    # Undone from the app: the rollback names its own request, and its execution cites it.
    with tenant_transaction(app_engine, sim["id"]) as conn:
        action_id = conn.execute(
            text("SELECT action_id FROM actions WHERE decision_id = :d"), {"d": d.decision_id}
        ).scalar_one()
    undone = client.post(
        f"/api/v1/stores/{sim['id']}/actions/{action_id}/rollback",
        headers={"User-Agent": BROWSER, "X-Request-ID": "req-web-rollback-01"},
    )
    assert undone.status_code == 200, undone.text
    Rig(app_engine).executor().run_once()
    rollback = undone.json()["action_id"]
    rows = who(app_engine, sim["id"], d.decision_id)
    requested = next(r for r in rows if r.action == "action.rollback_requested")
    assert (requested.actor, requested.origin["request_id"]) == (OWNER, "req-web-rollback-01")
    with tenant_transaction(app_engine, sim["id"]) as conn:
        cited = conn.execute(
            text(
                "SELECT payload->'authorized_by' FROM audit_log WHERE action = 'action.executed' "
                "AND payload->>'action_id' = :a"
            ),
            {"a": rollback},
        ).scalar_one()
    assert (cited["actor"], cited["origin"]["request_id"]) == (OWNER, "req-web-rollback-01")


def test_an_email_approval_names_its_link_and_request(
    app_engine: Engine, sim: dict[str, Any], client: TestClient
) -> None:
    d = proposed(app_engine, sim["id"], sim["campaigns"][1], "email")
    token = client.post(
        f"/api/v1/stores/{sim['id']}/decisions/{d.decision_id}/links",
        json={"option_id": d.recommended_option_id},
    ).json()["token"]
    confirmed = client.post(
        f"/api/v1/approval-links/{token}",
        headers={"User-Agent": BROWSER, "X-Request-ID": "req-email-confirm-1"},
    )
    assert confirmed.status_code == 200, confirmed.text
    approval = who(app_engine, sim["id"], d.decision_id)[0]
    assert (approval.actor, approval.channel) == ("owner:email", "email")
    assert approval.origin == {
        "session_id": None,
        "token_id": None,
        "request_id": "req-email-confirm-1",
        "user_agent": BROWSER,
        "link_id": str(read_link(token, secret=SECRET).link_id),
    }
