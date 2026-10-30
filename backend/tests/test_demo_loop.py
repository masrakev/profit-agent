"""The demo loop on the golden stockout store, end to end (Task 4, SPEC section 0): critical
alert, pause option, email approval, execution on the Meta sandbox (the documented-contract fake
without credentials) mirrored on the simulator, restock, resume as rollback, measured outcome."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.deps import get_engine
from app.api.main import app
from app.config import get_settings
from app.db import make_engine
from bench.demo import markdown, run
from bench.runner.__main__ import prepare_database

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def loop(database_urls: tuple[str, str]) -> dict[str, Any]:
    engine = make_engine(prepare_database("profit_demo_test"))
    settings = get_settings().model_copy(
        update={"meta_access_token": None, "meta_campaign_links": {}}
    )
    result = run(engine, settings)
    result["engine"] = engine
    return result


def test_the_loop_runs_end_to_end(loop: dict[str, Any]) -> None:
    assert loop["alert"].alert.value == "critical"
    decision = loop["decision"]
    assert decision.recommended_option_id.startswith("stockout_on_promoted:pause_until_restock")
    assert loop["approval"]["decision"]["status"] == "approved"
    assert loop["approval"]["confirmation_required"] is False
    assert loop["replay_status"] == 409  # the link works once
    assert loop["meta_mode"].startswith("documented-contract fake")
    assert loop["meta_mutations"] == 2  # pause, then resume: nothing twice
    meta_posts = [c for c in loop["meta_calls"] if c[0] == "POST"]
    statuses = [c[2].get("status") for c in meta_posts if "execution_options" not in c[2]]
    assert statuses == ["PAUSED", "ACTIVE"]
    assert all(o["status"] in ("measured", "abstained") for o in loop["outcomes"])
    assert all(o["predicted"] is not None for o in loop["outcomes"])
    measured = any(o["status"] == "measured" for o in loop["outcomes"])
    assert loop["final_status"] == ("measured" if measured else "executed")
    kinds = [e["kind"] for e in loop["journal"]]
    for kind in ("incident", "decision", "approval", "action", "outcome"):
        assert kind in kinds
    assert kinds.index("decision") < kinds.index("approval") < kinds.index("outcome")
    text = markdown(loop, datetime.now(UTC))
    assert "Demo: the stockout loop" in text


def test_the_api_reads_the_loop(loop: dict[str, Any]) -> None:
    engine: Engine = loop["engine"]
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app)
        store = loop["store"]
        decisions = client.get(f"/api/v1/stores/{store}/decisions").json()
        assert [d["decision_id"] for d in decisions] == [str(loop["decision"].decision_id)]
        trust = {t["action_type"]: t for t in client.get(f"/api/v1/stores/{store}/trust").json()}
        assert trust["pause_campaign"]["rollbacks"] >= 1
        assert trust["pause_campaign"]["proposal"] is None
        campaign = loop["decision"].option(loop["decision"].recommended_option_id).actions[0]
        preview = client.post(
            f"/api/v1/stores/{store}/policy/preview",
            json={"kind": "change_budget", "campaign_id": campaign["entity"], "change": "0.5"},
        ).json()
        assert (preview["allowed"], preview["rule"]) == (False, "budget_cap")
        missing = client.get(f"/api/v1/stores/{store}/decisions/{store}")
        assert missing.status_code == 404
        unknown = client.post(f"/api/v1/stores/{store}/actions/{store}/rollback")
        assert unknown.status_code == 404
        no_secret = client.post(
            f"/api/v1/stores/{store}/decisions/{loop['decision'].decision_id}/links",
            json={"option_id": loop["decision"].recommended_option_id},
        )
        assert no_secret.status_code == 503  # links need the signing secret
    finally:
        app.dependency_overrides.clear()
