"""HTTP API: Ask and investigations, with the engine and a scripted provider injected."""

import re
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.agent.llm import fake as f
from app.api.main import app, get_engine, get_provider
from tests.llm_helpers import Harness

pytestmark = pytest.mark.db


@pytest.fixture
def harness() -> Harness:
    return Harness([])


@pytest.fixture
def client(app_engine: Engine, harness: Harness) -> Iterator[TestClient]:
    app.dependency_overrides[get_engine] = lambda: app_engine
    app.dependency_overrides[get_provider] = lambda: harness.provider
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_openapi_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == "v1"
    assert set(spec["paths"]) == {
        "/api/v1/stores/{store_id}/ask",
        "/api/v1/incidents/{incident_id}/investigate",
        "/api/v1/investigations/{investigation_id}",
        "/api/v1/stores/{store_id}/decisions",
        "/api/v1/stores/{store_id}/decisions/{decision_id}",
        "/api/v1/stores/{store_id}/decisions/{decision_id}/approve",
        "/api/v1/stores/{store_id}/decisions/{decision_id}/reject",
        "/api/v1/stores/{store_id}/decisions/{decision_id}/links",
        "/api/v1/approval-links/{token}",
        "/api/v1/stores/{store_id}/actions/{action_id}/rollback",
        "/api/v1/stores/{store_id}/journal",
        "/api/v1/stores/{store_id}/policy/preview",
        "/api/v1/stores/{store_id}/trust",
        "/api/v1/stores/{store_id}/kill-switch",
        "/api/v1/admin/kill-switch",
    }


def test_ask_route(client: TestClient, harness: Harness, golden_stockout: dict[str, Any]) -> None:
    harness.transport.add(f.structured({"question_type": "out_of_scope"}))
    response = client.post(
        f"/api/v1/stores/{golden_stockout['id']}/ask", json={"question": "Should I hire someone?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["answer"]["flags"]) == ("out_of_scope", ["out_of_scope"])
    assert (
        client.post(
            f"/api/v1/stores/{golden_stockout['id']}/ask", json={"question": ""}
        ).status_code
        == 422
    )
    assert (
        client.post(f"/api/v1/stores/{uuid4()}/ask", json={"question": "Profit?"}).status_code
        == 404
    )


def test_investigation_routes(
    client: TestClient, harness: Harness, golden_stockout: dict[str, Any]
) -> None:
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
    store = {"X-Store-Id": str(golden_stockout["id"])}
    path = f"/api/v1/incidents/{golden_stockout['incident']}/investigate"
    created = client.post(path, headers=store, params={"refresh": True})
    assert created.status_code == 200, created.text
    investigation = created.json()
    assert investigation["status"] == "complete"
    fetched = client.get(
        f"/api/v1/investigations/{investigation['investigation_id']}", headers=store
    )
    assert fetched.json() == investigation
    other = {"X-Store-Id": str(uuid4())}
    assert (
        client.get(
            f"/api/v1/investigations/{investigation['investigation_id']}", headers=other
        ).status_code
        == 404
    )  # row-level security
    assert (
        client.post("/api/v1/incidents/inc-000000000000/investigate", headers=store).status_code
        == 404
    )
    assert client.post("/api/v1/incidents/not-an-id/investigate", headers=store).status_code == 422
    assert client.post(path).status_code == 422  # the store header is required
