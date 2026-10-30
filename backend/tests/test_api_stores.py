"""The web platform's endpoints: overview, incidents, investigations streamed, facts with
lineage, the profit bridge, briefings, Ask streamed, settings; and the frozen contract."""

import json
import re
from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.agent.llm import fake as f
from app.agent.steps import Step, emit, recording
from app.api.deps import get_engine, get_provider
from app.api.main import app
from app.api.openapi import OPENAPI_FILE, document, main
from app.briefings.models import BriefingKind
from app.briefings.service import generate
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


def test_the_contract_is_frozen() -> None:
    assert OPENAPI_FILE.read_text(encoding="utf-8") == document(), (
        "the API changed: review it, then `make openapi`"
    )


def test_overview_incidents_and_facts(client: TestClient, golden_stockout: dict[str, Any]) -> None:
    base = f"/api/v1/stores/{golden_stockout['id']}"
    overview = client.get(f"{base}/overview").json()
    assert overview["sections"][0]["key"] == "health"
    text = json.dumps(overview["sections"])
    for fid in re.findall(r"\{\{F(\d+)\}\}", text):
        assert fid in overview["facts"]
    assert "store" in overview["names"]
    incidents = client.get(f"{base}/incidents").json()
    first = incidents["items"][0]
    assert (first["incident_id"], first["alert"]) == (golden_stockout["incident"], "critical")
    assert first["monthly_impact"]["kind"] == "estimate"
    one = client.get(f"{base}/incidents", params={"limit": 1}).json()
    assert len(one["items"]) == 1
    detail = client.get(f"{base}/incidents/{golden_stockout['incident']}").json()
    assert detail["incident"]["incident_id"] == golden_stockout["incident"]
    assert detail["facts"]
    assert client.get(f"{base}/incidents/inc-000000000000").status_code == 404
    net = next(v for v in overview["facts"].values() if v["metric"] == "net_profit")
    fact = client.get(f"{base}/facts/{net['fact_id']}").json()
    assert fact["formula"]["formula_id"] == "net_profit"
    assert fact["formula"]["description"]
    assert {p["fact"]["metric"] for p in fact["parents"]} >= {"contribution_after_ads"}
    derived = next(v for v in overview["facts"].values() if v["metric"] == "derived.compute")
    assert client.get(f"{base}/facts/{derived['fact_id']}").json()["formula"] is None
    assert client.get(f"{base}/facts/999999999").status_code == 404
    bridge = client.get(f"{base}/profit-bridge").json()
    assert len(bridge["drivers"]) == 8
    assert bridge["change"]["metric"] == "profit_delta"
    month = client.get(f"{base}/profit-bridge", params={"period": "month"}).json()
    assert month["period_start"] == "2026-08-01"


def scripted_investigation(harness: Harness) -> None:
    def sensitivity(body: dict[str, Any]) -> f.Reply:
        incident = re.search(r"inc-[0-9a-f]{12}", body["input"][1]["content"][0]["text"])
        assert incident is not None
        return f.ok([f.function_call("run_sensitivity", {"incident_id": incident.group(0)})])

    def report(body: dict[str, Any]) -> f.Reply:
        text = body["input"][1]["content"][0]["text"]
        entity = re.findall(r"\{\{E:[a-z]+:[0-9a-f-]{36}\}\}", text)[0]
        return f.structured(
            {
                "hypotheses": [
                    {
                        "cause_family": "stockout_on_promoted",
                        "entities": [entity],
                        "confidence": "medium",
                        "evidence": [],
                        "tests_performed": [],
                        "counter_evidence": [],
                    }
                ],
                "narrative": "Stock ran out while the product was promoted.",
                "flags": [],
                "open_questions": [],
                "audit_findings": [],
            }
        )

    harness.transport.add(sensitivity, report)


def test_an_investigation_is_streamed(
    client: TestClient, harness: Harness, golden_stockout: dict[str, Any]
) -> None:
    base = f"/api/v1/stores/{golden_stockout['id']}"
    scripted_investigation(harness)
    started = client.post(
        f"{base}/incidents/{golden_stockout['incident']}/investigations", params={"refresh": True}
    )
    assert started.status_code == 202
    run = started.json()
    streamed = events(client.get(run["events"]).text)
    kinds = [e["kind"] for _, e in streamed]
    assert kinds[0] == "started"
    assert "model" in kinds
    assert "tool" in kinds
    assert streamed[-1][0] == "done"
    assert streamed[-1][1]["detail"]["status"] == "complete"
    tool = next(e for _, e in streamed if e["kind"] == "tool")
    assert tool["name"] == "run_sensitivity"
    steps = client.get(f"{base}/investigations/{run['investigation_id']}/steps").json()
    assert [s["kind"] for s in steps] == kinds
    result = client.get(run["result"]).json()
    assert result["investigation_id"] == run["investigation_id"]
    resumed = events(client.get(run["events"], headers={"Last-Event-ID": str(len(steps) - 1)}).text)
    assert [k for k, _ in resumed] == ["done"]
    # The same investigation again: served from the cache, at once.
    cached = client.post(f"{base}/incidents/{golden_stockout['incident']}/investigations").json()
    again = events(client.get(cached["events"]).text)
    assert [e["kind"] for _, e in again] == ["started", "cache_hit", "done"]
    assert again[-1][1]["detail"]["investigation_id"] == run["investigation_id"]
    assert client.get(f"{base}/investigations/{uuid4()}/events").status_code == 404
    missing = client.post(f"{base}/incidents/inc-000000000000/investigations")
    assert missing.status_code == 404


def test_briefings(client: TestClient, app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    store = golden_stockout["id"]
    record = generate(
        app_engine,
        store,
        BriefingKind.WEEKLY,
        Harness([f.overloaded()], max_attempts=1).provider,
        local_today=date(2026, 9, 30),
    )
    base = f"/api/v1/stores/{store}"
    listed = client.get(f"{base}/briefings", params={"kind": "weekly"}).json()
    assert [b["briefing_id"] for b in listed["items"]] == [str(record.briefing_id)]
    one = client.get(f"{base}/briefings/{record.briefing_id}").json()
    assert (one["kind"], one["status"], one["headline"]) == ("weekly", "facts_only", "Your week.")
    assert one["sections"][0]["key"] == "summary"
    cited = set(re.findall(r"\{\{F(\d+)\}\}", json.dumps(one["sections"])))
    assert cited
    assert set(one["facts"]) == cited  # the facts the text cites, each with its value
    assert client.get(f"{base}/briefings/{uuid4()}").status_code == 404


def test_ask_is_streamed(
    client: TestClient, harness: Harness, golden_stockout: dict[str, Any]
) -> None:
    harness.transport.add(f.structured({"question_type": "out_of_scope"}))
    base = f"/api/v1/stores/{golden_stockout['id']}"
    body = client.post(f"{base}/ask/stream", json={"question": "Should I hire someone?"}).text
    streamed = events(body)
    assert [k for k, _ in streamed][-2:] == ["answer", "done"]
    assert streamed[-2][1]["status"] == "out_of_scope"
    assert client.post(f"{base}/ask/stream", json={"question": ""}).status_code == 422


def test_settings_and_the_kill_switch(client: TestClient, golden_stockout: dict[str, Any]) -> None:
    base = f"/api/v1/stores/{golden_stockout['id']}"
    current = client.get(f"{base}/settings").json()
    changed = {**current, "alert_budget_per_day": 2, "notification_email": "owner@example.com"}
    saved = client.put(f"{base}/settings", json=changed).json()
    assert (saved["alert_budget_per_day"], saved["notification_email"]) == (2, "owner@example.com")
    wrong = client.put(f"{base}/settings", json={**changed, "store_id": str(uuid4())})
    assert wrong.status_code == 422
    invalid = client.put(f"{base}/settings", json={**changed, "alert_budget_per_day": -1})
    assert invalid.status_code == 422
    client.put(f"{base}/settings", json=current)
    assert client.get(f"{base}/kill-switch").json() == {"enabled": False}


def test_a_failing_trace_never_stops_the_agent() -> None:
    emit(Step("model"))  # nobody listening: nothing happens
    seen: list[str] = []

    def broken(step: Step) -> None:
        seen.append(step.kind)
        raise RuntimeError("the trace store is down")

    with recording(broken):
        emit(Step("tool", "get_incident"))
    assert seen == ["tool"]


def test_the_export_command(tmp_path: Any) -> None:
    target = tmp_path / "openapi.json"
    assert main([str(target)]) == 0
    assert target.read_text(encoding="utf-8") == document()
