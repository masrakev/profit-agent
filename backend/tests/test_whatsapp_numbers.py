"""The owner's WhatsApp number, verified by a code (app/whatsapp/numbers.py and the API): set in
the settings, a code sent on WhatsApp, typed on the web; limits on codes and attempts; one store
per verified number; only a verified number is found from a sender."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine

from app.api.deps import get_app_settings, get_engine
from app.api.main import app
from app.api.whatsapp import get_whatsapp_sender
from app.channels.whatsapp import FakeWhatsApp, WhatsAppError
from app.config import get_settings
from app.db import tenant_transaction
from app.whatsapp import numbers
from tests.api_helpers import act_as
from tests.conftest import create_store

pytestmark = pytest.mark.db
SECRET = "test-signing-secret"


@pytest.fixture
def fake() -> FakeWhatsApp:
    return FakeWhatsApp()


@pytest.fixture
def client(app_engine: Engine, fake: FakeWhatsApp) -> Iterator[TestClient]:
    settings = get_settings().model_copy(update={"approval_link_secret": SecretStr(SECRET)})
    app.dependency_overrides[get_engine] = lambda: app_engine
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_whatsapp_sender] = lambda: fake
    act_as(app)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def set_number(client: TestClient, store: UUID, number: str | None) -> dict[str, Any]:
    base = f"/api/v1/stores/{store}"
    current = client.get(f"{base}/settings").json()
    saved = client.put(f"{base}/settings", json={**current, "whatsapp_number": number})
    assert saved.status_code == 200, saved.text
    body: dict[str, Any] = client.get(f"{base}/whatsapp").json()
    return body


def sent_code(fake: FakeWhatsApp) -> str:
    _, message, session = fake.sent[-1]
    assert (message.template, session) == ("verification_code", False)  # it has not written
    assert message.copy_code == message.params[0]
    return message.params[0]


def test_a_number_is_verified_by_the_code_sent_to_it(
    client: TestClient, app_engine: Engine, fake: FakeWhatsApp
) -> None:
    store = create_store(app_engine)
    base = f"/api/v1/stores/{store}/whatsapp"
    assert client.get(base).json() == {
        "number": None,
        "verified": False,
        "verified_at": None,
        "code_expires_at": None,
        "window_open": False,
    }
    assert client.post(f"{base}/verification").json()["code"] == "no_number"
    assert set_number(client, store, "+15551230001")["verified"] is False
    assert numbers.store_for(app_engine, "15551230001") is None  # pending: it cannot act
    sent = client.post(f"{base}/verification")
    assert sent.status_code == 202
    assert sent.json()["sent_to_ending"] == "0001"
    assert fake.sent[-1][0] == "15551230001"
    code = sent_code(fake)
    assert client.get(base).json()["code_expires_at"] is not None
    wrong = "000000" if code != "000000" else "111111"
    refused = client.post(f"{base}/verification/confirm", json={"code": wrong})
    assert (refused.status_code, refused.json()["code"]) == (422, "invalid_code")
    assert client.post(f"{base}/verification/confirm", json={"code": "12"}).status_code == 422
    done = client.post(f"{base}/verification/confirm", json={"code": code}).json()
    assert (done["number"], done["verified"]) == ("+15551230001", True)
    assert numbers.store_for(app_engine, "15551230001") == store
    again = client.post(f"{base}/verification")
    assert (again.status_code, again.json()["code"]) == (409, "already_verified")
    replay = client.post(f"{base}/verification/confirm", json={"code": code})
    assert replay.json()["code"] == "already_verified"


def test_wrong_codes_are_counted_and_codes_are_limited(
    client: TestClient, app_engine: Engine, fake: FakeWhatsApp
) -> None:
    store = create_store(app_engine)
    base = f"/api/v1/stores/{store}/whatsapp"
    set_number(client, store, "+15551230002")
    client.post(f"{base}/verification")
    code = sent_code(fake)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(numbers.MAX_ATTEMPTS):
        assert client.post(f"{base}/verification/confirm", json={"code": wrong}).status_code == 422
    locked = client.post(f"{base}/verification/confirm", json={"code": code})
    assert locked.json()["code"] == "too_many_attempts"  # even the right code, now
    for _ in range(numbers.MAX_CODES_PER_HOUR - 1):
        assert client.post(f"{base}/verification").status_code == 202
    limited = client.post(f"{base}/verification")
    assert (limited.status_code, limited.json()["code"]) == (429, "too_many_codes")


def test_a_code_expires(app_engine: Engine) -> None:
    store = create_store(app_engine)
    now = datetime.now(UTC)
    with tenant_transaction(app_engine, store) as conn:
        numbers.sync_number(conn, store, "+15551230003")
        _, code = numbers.start(conn, store, secret=SECRET, now=now)
    later = now + numbers.CODE_TTL + timedelta(seconds=1)
    with (
        pytest.raises(numbers.NumberError, match="expired"),
        tenant_transaction(app_engine, store) as conn,
    ):
        numbers.confirm(conn, store, code, secret=SECRET, actor="owner:test", now=later)
    with tenant_transaction(app_engine, store) as conn:  # a new code later in the hour works
        _, code = numbers.start(conn, store, secret=SECRET, now=later)
        found = numbers.confirm(conn, store, code, secret=SECRET, actor="owner:test", now=later)
    assert isinstance(found, numbers.NumberState)
    assert found.verified


def test_a_verified_number_belongs_to_one_store(app_engine: Engine) -> None:
    first, second = create_store(app_engine), create_store(app_engine)
    now = datetime.now(UTC)
    for store in (first, second):
        with tenant_transaction(app_engine, store) as conn:
            numbers.sync_number(conn, store, "+15551230004")
    with tenant_transaction(app_engine, first) as conn:
        _, code = numbers.start(conn, first, secret=SECRET, now=now)
        numbers.confirm(conn, first, code, secret=SECRET, actor="owner:test", now=now)
    with tenant_transaction(app_engine, second) as conn:
        _, code = numbers.start(conn, second, secret=SECRET, now=now)
    with (
        pytest.raises(numbers.NumberError, match="another store"),
        tenant_transaction(app_engine, second) as conn,
    ):
        numbers.confirm(conn, second, code, secret=SECRET, actor="owner:test", now=now)
    assert numbers.store_for(app_engine, "15551230004") == first


def test_changing_or_removing_the_number_starts_over(
    client: TestClient, app_engine: Engine, fake: FakeWhatsApp
) -> None:
    store = create_store(app_engine)
    base = f"/api/v1/stores/{store}/whatsapp"
    set_number(client, store, "+15551230005")
    client.post(f"{base}/verification")
    client.post(f"{base}/verification/confirm", json={"code": sent_code(fake)})
    with tenant_transaction(app_engine, store) as conn:
        numbers.touch_inbound(conn, store)
    unchanged = set_number(client, store, "+15551230005")
    assert (unchanged["verified"], unchanged["window_open"]) == (True, True)
    changed = set_number(client, store, "+15551230006")
    assert (changed["number"], changed["verified"], changed["window_open"]) == (
        "+15551230006",
        False,
        False,
    )
    assert numbers.store_for(app_engine, "15551230005") is None
    assert set_number(client, store, None)["number"] is None
    bad = client.put(
        f"/api/v1/stores/{store}/settings",
        json={**client.get(f"/api/v1/stores/{store}/settings").json(), "whatsapp_number": "555"},
    )
    assert bad.status_code == 422


def test_without_whatsapp_or_a_secret_nothing_is_sent(
    client: TestClient, app_engine: Engine, fake: FakeWhatsApp
) -> None:
    store = create_store(app_engine)
    base = f"/api/v1/stores/{store}/whatsapp"
    set_number(client, store, "+15551230007")
    fake.failures.append(WhatsAppError("down", retryable=True))
    failed = client.post(f"{base}/verification")
    assert (failed.status_code, failed.json()["code"]) == (503, "whatsapp_failed")
    app.dependency_overrides[get_whatsapp_sender] = lambda: None
    missing = client.post(f"{base}/verification")
    assert (missing.status_code, missing.json()["code"]) == (503, "whatsapp_unavailable")
    app.dependency_overrides[get_whatsapp_sender] = lambda: fake
    app.dependency_overrides[get_app_settings] = lambda: get_settings().model_copy(
        update={"approval_link_secret": None}
    )
    assert client.post(f"{base}/verification").json()["code"] == "whatsapp_unavailable"


def test_the_code_goes_as_a_text_when_meta_refuses_its_template(
    client: TestClient, app_engine: Engine, fake: FakeWhatsApp
) -> None:
    store = create_store(app_engine)
    base = f"/api/v1/stores/{store}/whatsapp"
    set_number(client, store, "+15551230009")
    # The template is not approved yet: the owner may still have written to the business number.
    fake.failures.append(WhatsAppError("template not approved", retryable=False, code=132001))
    assert client.post(f"{base}/verification").status_code == 202
    _, message, session = fake.sent[-1]
    assert session is True
    assert message.params[0] in message.text
    confirmed = client.post(f"{base}/verification/confirm", json={"code": message.params[0]})
    assert confirmed.json()["verified"] is True
    # A passing failure is not a refusal: no text after it, the owner retries.
    fake.failures.append(WhatsAppError("timeout", retryable=True, code=131000))
    sent = len(fake.sent)
    set_number(client, store, "+15551230010")
    assert client.post(f"{base}/verification").status_code == 503
    assert len(fake.sent) == sent
