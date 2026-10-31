"""The demo store and the demo loop on it, end to end (Task 4, SPEC section 0; Task 5 B7).

The seed replays the recorded model exchanges (backend/tests/cassettes/demo): history, the
critical stockout alert with its pending decision, an investigation and its trace, past
decisions measured, briefings, an owner's token. The loop then approves the pending pause by
email link, executes it on the Meta sandbox (the documented-contract fake without credentials)
mirrored on the simulator, restocks, resumes as a rollback, and measures the outcome."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

import bench.demo
import bench.demo_seed
from app.api.deps import get_engine
from app.api.main import app
from app.config import get_settings
from app.db import make_engine
from bench.demo import markdown, run
from bench.demo_seed import demo_provider, seed
from bench.demo_seed import markdown as seed_markdown
from bench.runner.__main__ import prepare_database

pytestmark = pytest.mark.db

# Named after the test database, so that two test runs on one server never share it.
DEMO_DB = os.environ.get("TEST_DATABASE_NAME", "profit_test") + "_demo"


def _read(engine: Engine, token: str, store: str, paths: dict[str, str]) -> dict[str, Any]:
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
        return {k: client.get(f"/api/v1/stores/{store}{p}").json() for k, p in paths.items()}
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def demo(database_urls: tuple[str, str]) -> dict[str, Any]:
    engine = make_engine(prepare_database(DEMO_DB))
    settings = get_settings().model_copy(
        update={"meta_access_token": None, "meta_campaign_links": {}}
    )
    seeded = seed(engine, demo_provider(settings))
    before = _read(
        engine,
        seeded.api_token,
        str(seeded.store_id),
        {
            "overview": "/overview",
            "incidents": "/incidents",
            "decisions": "/decisions",
            "steps": f"/investigations/{seeded.investigation_id}/steps",
            "investigation": f"/investigations/{seeded.investigation_id}",
            "briefings": "/briefings",
            "journal": "/journal?limit=200",
            "goal": f"/goals/{seeded.goal.goal_id}",
            "goal_progress": f"/goals/{seeded.goal.goal_id}/progress",
        },
    )
    result = run(engine, settings, seeded)
    result.update(engine=engine, seeded=seeded, before=before)
    return result


def test_the_demo_store_is_seeded(demo: dict[str, Any]) -> None:
    seeded, before = demo["seeded"], demo["before"]
    assert seeded.incident.alert.value == "critical"
    statuses = {d["decision_id"]: d["status"] for d in before["decisions"]["items"]}
    assert statuses.pop(str(seeded.decision_id)) == "proposed"  # the owner's to approve
    goal = seeded.goal  # the plan's due steps, proposed: the owner's to approve too
    assert goal.decisions
    assert {statuses.pop(str(d)) for d in goal.decisions} == {"proposed"}
    assert set(statuses) == {str(p.decision_id) for p in seeded.past}
    assert all(p.outcome["status"] in ("measured", "abstained") for p in seeded.past)
    assert set(statuses.values()) <= {"measured", "executed"}
    assert [p.label for p in seeded.past] == ["budget -30%", "budget +20%"]
    kinds = [s["kind"] for s in before["steps"]]
    assert (kinds[0], kinds[-1]) == ("started", "done")
    assert {"model", "tool"} <= set(kinds)
    assert before["investigation"]["status"] == "complete"
    assert before["incidents"]["items"][0]["incident_id"] == seeded.incident.incident_id
    assert before["overview"]["sections"]
    briefings = before["briefings"]["items"]
    assert sorted(b["kind"] for b in briefings) == ["daily", "monthly", "weekly"]
    journal = {e["kind"] for e in before["journal"]["items"]}
    assert {"incident", "decision", "approval", "action", "outcome"} <= journal
    assert seeded.counts["briefings"] == 3
    assert before["goal"]["status"] == "planned"
    assert [w["day"] for w in goal.progress] == [7, 14]  # a week, then another
    assert [p["day"] for p in before["goal_progress"]] == [7, 14]
    assert all(w["adherence"]["pending"] == len(goal.decisions) for w in goal.progress)
    assert (seeded.counts["goals"], seeded.counts["goal_progress"]) == (1, 2)
    assert seeded.counts["investigation_steps"] == len(before["steps"])
    text = seed_markdown(seeded, datetime.now(UTC))
    assert "| budget -30% |" in text
    assert seeded.api_token not in text  # the token is printed once, never written


def test_the_loop_runs_end_to_end(demo: dict[str, Any]) -> None:
    loop = demo
    assert loop["alert"].alert.value == "critical"
    decision = loop["decision"]
    assert decision.decision_id == loop["seeded"].decision_id
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
    mine = str(decision.decision_id)
    kinds = [
        e["kind"] for e in loop["journal"] if mine in (e["id"], e["summary"].get("decision_id"))
    ]
    for kind in ("decision", "approval", "action", "outcome"):
        assert kind in kinds
    assert kinds.index("decision") < kinds.index("approval") < kinds.index("outcome")
    text = markdown(loop, datetime.now(UTC))
    assert "Demo: the stockout loop" in text
    assert "a budget -30% decision" in text


def test_the_api_reads_the_loop(demo: dict[str, Any]) -> None:
    loop = demo
    engine: Engine = loop["engine"]
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, headers={"Authorization": f"Bearer {loop['api_token']}"})
        store = loop["store"]
        decisions = client.get(f"/api/v1/stores/{store}/decisions").json()["items"]
        assert decisions[0]["decision_id"] == str(loop["decision"].decision_id)
        assert len(decisions) == 1 + len(loop["past"]) + len(loop["seeded"].goal.decisions)
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


def test_the_entry_points_write_their_reports(
    demo: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`make demo-seed` and `make demo`, on the store already seeded and looped above."""
    url = demo["engine"].url.render_as_string(hide_password=False)
    for module in (bench.demo_seed, bench.demo):
        monkeypatch.setattr(module, "prepare_database", lambda _name: url)
        monkeypatch.setattr(module, "REPORT_DIR", tmp_path)
        monkeypatch.setattr(module, "seed", lambda _engine, _provider: demo["seeded"])
    monkeypatch.setattr(bench.demo, "run", lambda _engine, _settings, _seeded: demo)
    assert bench.demo_seed.main([]) == 0
    assert (tmp_path / "demo-seed.md").read_text(encoding="utf-8").startswith("# Demo store")
    assert f"(shown once): {demo['api_token']}" in capsys.readouterr().out
    assert bench.demo.main() == 0
    report = (tmp_path / "demo-stockout.md").read_text(encoding="utf-8")
    assert report.startswith("# Demo: the stockout loop")
