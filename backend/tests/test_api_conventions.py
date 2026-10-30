"""API conventions (ADR 0020): problem details, request ids, security headers, rate limits,
health and readiness, cursor pagination."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.deps import get_engine
from app.api.main import app, create_app
from app.api.middleware import Limits, RateLimiter
from app.api.pagination import paginate
from tests.api_helpers import act_as


@pytest.fixture
def client(app_engine: Engine) -> Iterator[TestClient]:
    app.dependency_overrides[get_engine] = lambda: app_engine
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_errors_are_problem_details(client: TestClient) -> None:
    anonymous = client.get("/api/v1/stores/00000000-0000-0000-0000-000000000001/decisions")
    assert anonymous.status_code == 401
    assert anonymous.headers["content-type"] == "application/problem+json"
    body = anonymous.json()
    assert (body["type"], body["title"], body["status"], body["code"]) == (
        "urn:profit-agent:problem:unauthenticated",
        "Unauthorized",
        401,
        "unauthenticated",
    )
    assert body["request_id"] == anonymous.headers["x-request-id"]
    act_as(app)
    invalid = client.get("/api/v1/stores/not-a-uuid/decisions")
    assert (invalid.status_code, invalid.json()["code"]) == (422, "invalid_request")
    assert invalid.json()["errors"][0]["field"] == "path.store_id"
    assert "not-a-uuid" not in invalid.text  # values are not echoed
    assert client.get("/api/v1/nowhere").json()["code"] == "not_found"


def test_request_ids_and_security_headers(client: TestClient) -> None:
    mine = client.get("/api/v1/health", headers={"X-Request-ID": "trace-12345678"})
    assert mine.headers["x-request-id"] == "trace-12345678"
    made = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\x7f"})
    assert len(made.headers["x-request-id"]) == 32
    for name, value in (
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "no-referrer"),
        ("cache-control", "no-store"),
    ):
        assert mine.headers[name] == value
    assert "default-src 'none'" in mine.headers["content-security-policy"]
    assert "max-age=" in mine.headers["strict-transport-security"]
    assert "content-security-policy" not in client.get("/docs").headers  # the docs page loads


def test_health_and_readiness(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok", "version": "v1"}
    ready = client.get("/api/v1/ready").json()
    assert (ready["status"], ready["database"]) == ("ready", "ok")


def test_rate_limits(app_engine: Engine) -> None:
    clock = [0.0]
    limited = create_app(
        RateLimiter(Limits(per_ip=3, per_store=2, sign_in_per_ip=1), lambda: clock[0])
    )
    limited.dependency_overrides[get_engine] = lambda: app_engine
    client = TestClient(limited)
    assert [client.get("/api/v1/health").status_code for _ in range(4)] == [200, 200, 200, 429]
    over = client.get("/api/v1/health")
    assert (over.json()["code"], int(over.headers["retry-after"])) == ("rate_limited", 60)
    clock[0] = 60.0  # the next window
    assert client.get("/api/v1/health").status_code == 200
    first = client.post("/api/v1/auth/magic-links", json={"email": "a@example.com"})
    second = client.post("/api/v1/auth/magic-links", json={"email": "a@example.com"})
    assert (first.status_code, second.status_code) == (202, 429)
    clock[0] = 120.0
    store = "/api/v1/stores/00000000-0000-0000-0000-000000000001/decisions"
    assert [client.get(store).status_code for _ in range(3)] == [401, 401, 429]


def test_pagination() -> None:
    items = [{"id": f"{i:02d}"} for i in range(5)]

    def key(item: dict[str, Any]) -> tuple[str]:
        return (item["id"],)

    first = paginate(items, key=key, limit=2, cursor=None)
    assert [i["id"] for i in first.items] == ["04", "03"]
    second = paginate(items, key=key, limit=2, cursor=first.next_cursor)
    assert [i["id"] for i in second.items] == ["02", "01"]
    last = paginate(items, key=key, limit=2, cursor=second.next_cursor)
    assert ([i["id"] for i in last.items], last.next_cursor) == (["00"], None)
    oldest = paginate(items, key=key, limit=3, cursor=None, descending=False)
    assert [i["id"] for i in oldest.items] == ["00", "01", "02"]


def test_an_invalid_cursor(client: TestClient) -> None:
    act_as(app)
    store = "00000000-0000-0000-0000-000000000001"
    bad = client.get(f"/api/v1/stores/{store}/journal", params={"cursor": "%%%"})
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_cursor")
    page = client.get(f"/api/v1/stores/{store}/journal", params={"limit": 1}).json()
    assert page == {"items": [], "next_cursor": None}
