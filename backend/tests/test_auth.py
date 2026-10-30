"""Authentication and access (ADR 0020), through the real flow: email link, session cookie,
CSRF, API tokens; and every store route refuses another store's caller."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api.deps import get_app_settings, get_email_sender, get_engine
from app.api.main import app
from app.auth.service import MAX_LINKS_PER_HOUR, add_owner, request_link
from app.channels.email import RecordingSender
from app.config import get_settings
from tests.conftest import create_store

pytestmark = pytest.mark.db
APP_URL = "https://app.example"


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def client(app_engine: Engine, sender: RecordingSender) -> Iterator[TestClient]:
    settings = get_settings().model_copy(update={"app_base_url": APP_URL})
    app.dependency_overrides[get_engine] = lambda: app_engine
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_email_sender] = lambda: sender
    try:
        yield TestClient(app, base_url="https://testserver")
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def stores(app_engine: Engine) -> dict[str, Any]:
    a, b = create_store(app_engine, name="Store A"), create_store(app_engine, name="Store B")
    email = f"owner-{uuid4().hex[:8]}@example.com"
    add_owner(app_engine, email, a)
    return {"a": a, "b": b, "email": email}


def sign_in(client: TestClient, sender: RecordingSender, email: str) -> str:
    """Request a link, read it from the email, open a session; returns the CSRF token."""
    assert client.post("/api/v1/auth/magic-links", json={"email": email}).status_code == 202
    token = re.search(r"/sign-in#token=([\w-]+)", sender.sent[-1].text)
    assert token is not None
    opened = client.post("/api/v1/auth/sessions", json={"token": token.group(1)})
    assert opened.status_code == 201, opened.text
    csrf: str = opened.json()["csrf_token"]
    return csrf


def test_the_email_link_signs_in_once(
    client: TestClient, sender: RecordingSender, stores: dict[str, Any]
) -> None:
    accepted = client.post("/api/v1/auth/magic-links", json={"email": stores["email"].upper()})
    assert accepted.status_code == 202
    [message] = sender.sent
    assert message.to == stores["email"]
    assert f"{APP_URL}/sign-in#token=" in message.text
    token = re.search(r"#token=([\w-]+)", message.text)
    assert token is not None
    opened = client.post("/api/v1/auth/sessions", json={"token": token.group(1)})
    assert opened.status_code == 201
    body = opened.json()
    assert body["store_ids"] == [str(stores["a"])]
    assert body["actor"] == f"owner:{stores['email']}"
    cookie = opened.headers["set-cookie"].lower()
    assert "pa_session=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    me = client.get("/api/v1/auth/session")
    assert (me.status_code, me.json()["store_ids"]) == (200, [str(stores["a"])])
    again = client.post("/api/v1/auth/sessions", json={"token": token.group(1)})
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "used_link")
    bad = client.post("/api/v1/auth/sessions", json={"token": "x" * 43})
    assert bad.status_code == 401


def test_unknown_addresses_and_expired_links(
    client: TestClient, sender: RecordingSender, app_engine: Engine, stores: dict[str, Any]
) -> None:
    unknown = client.post("/api/v1/auth/magic-links", json={"email": "nobody@example.com"})
    assert unknown.status_code == 202  # the same answer: addresses cannot be probed
    assert sender.sent == []
    old = request_link(app_engine, stores["email"], datetime.now(UTC) - timedelta(minutes=16))
    assert old is not None
    expired = client.post("/api/v1/auth/sessions", json={"token": old})
    assert (expired.status_code, expired.json()["detail"]["code"]) == (410, "expired_link")


def test_links_are_rate_limited_per_address(
    app_engine: Engine, client: TestClient, sender: RecordingSender
) -> None:
    store = create_store(app_engine)
    email = f"busy-{uuid4().hex[:8]}@example.com"
    add_owner(app_engine, email, store)
    for _ in range(MAX_LINKS_PER_HOUR + 2):
        client.post("/api/v1/auth/magic-links", json={"email": email})
    assert len(sender.sent) == MAX_LINKS_PER_HOUR


def test_state_changes_need_the_csrf_token_and_the_origin(
    client: TestClient, sender: RecordingSender, stores: dict[str, Any]
) -> None:
    csrf = sign_in(client, sender, stores["email"])
    path = f"/api/v1/stores/{stores['a']}/kill-switch"
    body = {"enabled": False, "reason": "csrf test"}
    missing = client.put(path, json=body)
    assert (missing.status_code, missing.json()["detail"]["code"]) == (403, "csrf")
    wrong = client.put(path, json=body, headers={"X-CSRF-Token": "not-it"})
    assert wrong.status_code == 403
    foreign = client.put(
        path, json=body, headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"}
    )
    assert foreign.status_code == 403
    ok = client.put(path, json=body, headers={"X-CSRF-Token": csrf, "Origin": APP_URL})
    assert ok.status_code == 200
    assert client.get(f"/api/v1/stores/{stores['a']}/decisions").status_code == 200  # reads: no
    out = client.delete("/api/v1/auth/session", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 204
    assert client.get("/api/v1/auth/session").status_code == 401  # signed out


def test_api_tokens(
    client: TestClient, sender: RecordingSender, app_engine: Engine, stores: dict[str, Any]
) -> None:
    csrf = sign_in(client, sender, stores["email"])
    created = client.post(
        f"/api/v1/stores/{stores['a']}/api-tokens",
        json={"name": "reporting"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("pa_")
    listed = client.get(f"/api/v1/stores/{stores['a']}/api-tokens").json()
    assert [t["name"] for t in listed] == ["reporting"]
    assert "token" not in listed[0]
    with app_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT token_hash FROM auth.api_tokens WHERE token_id = :t"),
            {"t": UUID(created.json()["token_id"])},
        ).scalar_one()
    assert token.encode() not in bytes(stored)  # only the digest is kept
    bearer = TestClient(app, base_url="https://testserver")
    auth = {"Authorization": f"Bearer {token}"}
    assert bearer.get(f"/api/v1/stores/{stores['a']}/decisions", headers=auth).status_code == 200
    assert bearer.get(f"/api/v1/stores/{stores['b']}/decisions", headers=auth).status_code == 404
    minted = bearer.post(
        f"/api/v1/stores/{stores['a']}/api-tokens", json={"name": "x"}, headers=auth
    )
    assert minted.status_code == 403  # a token cannot create tokens
    revoked = client.delete(
        f"/api/v1/stores/{stores['a']}/api-tokens/{created.json()['token_id']}",
        headers={"X-CSRF-Token": csrf},
    )
    assert revoked.status_code == 204
    assert bearer.get(f"/api/v1/stores/{stores['a']}/decisions", headers=auth).status_code == 401


PLACEHOLDERS = {
    "incident_id": "inc-000000000000",
    "fact_id": "1",
}


def _fill(path: str, store: UUID) -> str:
    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "store_id":
            return str(store)
        return PLACEHOLDERS.get(name, str(uuid4()))

    return re.sub(r"\{(\w+)\}", value, path)


def test_no_store_route_reaches_another_store(
    client: TestClient, sender: RecordingSender, stores: dict[str, Any]
) -> None:
    """Every route under /stores/{store_id}, every method: another store's caller gets 404, an
    anonymous caller 401, whatever the rest of the request."""
    csrf = sign_in(client, sender, stores["email"])
    routes = [
        (path, method.upper())
        for path, item in app.openapi()["paths"].items()
        if "{store_id}" in path
        for method in item
    ]
    assert len(routes) >= 15
    anonymous = TestClient(app, base_url="https://testserver")
    for path, method in routes:
        url = _fill(path, stores["b"])
        theirs = client.request(method, url, json={}, headers={"X-CSRF-Token": csrf})
        assert theirs.status_code == 404, (method, path, theirs.text)
        assert theirs.json()["detail"]["message"] == "no such store", (method, path)
        nobody = anonymous.request(method, _fill(path, stores["a"]), json={})
        assert nobody.status_code == 401, (method, path, nobody.text)
