"""HTTP API: Ask and investigations, with the engine and a scripted provider injected."""

import json
import re
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.agent.llm import fake as f
from app.api.main import app, get_engine, get_provider
from app.api.views import duration_text
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


def test_openapi_contract(client: TestClient) -> None:
    """The full contract is frozen in docs/api/openapi.json (test_api_stores.py)."""
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == "v1"
    assert "/api/v1/stores/{store_id}/overview" in spec["paths"]


def test_ask_route(client: TestClient, harness: Harness, golden_stockout: dict[str, Any]) -> None:
    harness.transport.add(f.structured({"question_type": "out_of_scope"}))
    response = client.post(
        f"/api/v1/stores/{golden_stockout['id']}/ask", json={"question": "Should I hire someone?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["answer"]["flags"]) == ("out_of_scope", ["out_of_scope"])
    # The answer carries every fact it cites (its evidence and its references) and its names.
    evidence = {str(i) for i in body["answer"]["evidence"]}
    assert evidence
    assert evidence <= set(body["facts"])
    assert body["names"]["store"] == "Bench store 70400"
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


def test_a_duration_reads_as_said() -> None:
    assert [duration_text(s) for s in (0, 41, 60, 65, 3600)] == [
        "under a second",
        "41 s",
        "1 min",
        "1 min 5 s",
        "60 min",
    ]


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
        fid = int(re.findall(r'fact_id\\?":\s*(\d+)', json.dumps(body["input"]))[0])
        return f.structured(
            {
                "hypotheses": [
                    {
                        "cause_family": "stockout_on_promoted",
                        "entities": [entity],
                        "confidence": "medium",
                        "evidence": [fid],
                        "tests_performed": [],
                        "counter_evidence": [],
                    }
                ],
                "narrative": f"Stock ran out while the product was promoted: {{{{F{fid}}}}}.",
                "flags": [],
                "open_questions": [],
                "audit_findings": [],
            }
        )

    harness.transport.add(sensitivity, report)
    base = f"/api/v1/stores/{golden_stockout['id']}"
    path = f"{base}/incidents/{golden_stockout['incident']}/investigate"
    created = client.post(path, params={"refresh": True})
    assert created.status_code == 200, created.text
    investigation = created.json()
    assert investigation["status"] == "complete"
    # When it ran, and what it cites (its evidence, and the names of the entities it names).
    assert investigation["started_at"] <= investigation["finished_at"]
    assert investigation["finished_at"] == investigation["created_at"]
    assert investigation["duration"] == duration_text(investigation["duration_seconds"])
    [top] = investigation["report"]["hypotheses"]
    assert set(investigation["facts"]) == {str(i) for i in top["evidence"]}
    assert top["entities"][0].strip("{}").removeprefix("E:") in investigation["names"]
    fetched = client.get(f"{base}/investigations/{investigation['investigation_id']}")
    assert fetched.json() == investigation
    other = f"/api/v1/stores/{uuid4()}/investigations/{investigation['investigation_id']}"
    assert client.get(other).status_code == 404  # row-level security
    assert client.post(f"{base}/incidents/inc-000000000000/investigate").status_code == 404
    assert client.post(f"{base}/incidents/not-an-id/investigate").status_code == 422
