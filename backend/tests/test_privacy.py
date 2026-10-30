"""Privacy (ADR 0021): encrypted platform tokens, export, deletion (with the proof that nothing
of the store remains), and retention of model traces."""

import io
import json
import re
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

from app.agent.steps import Step
from app.agent.trace import recorder
from app.api.deps import get_app_settings, get_email_sender, get_engine
from app.api.main import app
from app.auth.service import add_owner, create_api_token
from app.channels.email import RecordingSender
from app.config import get_settings
from app.db import tenant_transaction
from app.delivery.alerts import dispatch_alerts
from app.detection import pipeline
from app.executor.__main__ import store_meta_adapters
from app.executor.meta import MetaAdsAdapter
from app.privacy.connections import credentials, master_key, save_connection
from app.privacy.crypto import CryptoError, MasterKey, open_sealed, rewrap, seal
from app.privacy.retention import purge
from bench.scenarios.manifest import load_suite
from bench.simulator import register
from tests.action_helpers import approved, option_set

KEY = MasterKey.generate()
STORE = UUID(int=7)


def test_envelope_encryption() -> None:
    master = MasterKey.from_base64("k1", KEY)
    sealed = seal(master, STORE, "meta", "EAAB-token")
    assert b"EAAB-token" not in sealed.ciphertext + sealed.wrapped_key
    assert open_sealed(master, STORE, "meta", sealed) == "EAAB-token"
    with pytest.raises(CryptoError, match="does not decrypt"):
        open_sealed(master, UUID(int=8), "meta", sealed)  # copied to another store
    with pytest.raises(CryptoError, match="does not decrypt"):
        open_sealed(master, STORE, "shopify", sealed)  # or another provider
    with pytest.raises(CryptoError, match="does not decrypt"):
        open_sealed(MasterKey.from_base64("k1", MasterKey.generate()), STORE, "meta", sealed)
    rotated = MasterKey.from_base64("k2", MasterKey.generate())
    again = rewrap(master, rotated, STORE, "meta", sealed)
    assert (again.key_id, again.ciphertext) == ("k2", sealed.ciphertext)
    assert open_sealed(rotated, STORE, "meta", again) == "EAAB-token"
    with pytest.raises(CryptoError, match="sealed with key"):
        open_sealed(master, STORE, "meta", again)
    with pytest.raises(CryptoError, match="sealed with key"):
        rewrap(rotated, master, STORE, "meta", sealed)
    with pytest.raises(CryptoError, match="32 bytes"):
        MasterKey.from_base64("k1", "c2hvcnQ")
    with pytest.raises(CryptoError, match="base64url"):
        MasterKey.from_base64("k1", "*")
    with pytest.raises(CryptoError, match="not set"):
        master_key(get_settings().model_copy(update={"token_encryption_key": None}))


# --- through the API ---------------------------------------------------------------------------


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def cassettes(tmp_path: Path) -> Path:
    return tmp_path / "cassettes"


@pytest.fixture
def client(app_engine: Engine, sender: RecordingSender, cassettes: Path) -> Iterator[TestClient]:
    settings = get_settings().model_copy(
        update={
            "token_encryption_key": SecretStr(KEY),
            "llm_cassette_dir": str(cassettes),
        }
    )
    app.dependency_overrides[get_engine] = lambda: app_engine
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_email_sender] = lambda: sender
    try:
        yield TestClient(app, base_url="https://testserver")
    finally:
        app.dependency_overrides.clear()


def sign_in(client: TestClient, sender: RecordingSender, email: str) -> dict[str, str]:
    client.post("/api/v1/auth/magic-links", json={"email": email})
    token = re.search(r"#token=([\w-]+)", sender.sent[-1].text)
    assert token is not None
    opened = client.post("/api/v1/auth/sessions", json={"token": token.group(1)}).json()
    return {"X-CSRF-Token": opened["csrf_token"]}


@pytest.fixture(scope="module")
def lived(app_engine: Engine) -> dict[str, Any]:
    """A store with rows in most tables: data, facts, incidents, alerts, a decision and its
    action, deliveries, an investigation trace, an owner, a token and a connection."""
    manifest = next(m for m in load_suite("dev") if m.scenario_id == "dev-stockout_on_promoted-07")
    store = register(app_engine, manifest, 106)
    pipeline.run_pipeline(app_engine, store)
    dispatch_alerts(app_engine, store)
    campaign = manifest.generate().campaigns[0].id
    approved(app_engine, store, option_set(campaign, label="privacy"))
    trace = recorder(app_engine, store, uuid4())
    trace(Step("started"))
    trace(Step("done"))
    email = f"privacy-{uuid4().hex[:8]}@example.com"
    add_owner(app_engine, email, store)
    create_api_token(app_engine, store, "scripts", None, datetime.now(UTC))
    with tenant_transaction(app_engine, store) as conn:
        save_connection(
            conn,
            store,
            "meta",
            "act_1",
            "EAAB-secret",
            MasterKey.from_base64("k1", KEY),
            datetime.now(UTC),
        )
    return {"id": store, "email": email}


def test_connections_keep_tokens_encrypted(
    client: TestClient, sender: RecordingSender, app_engine: Engine, lived: dict[str, Any]
) -> None:
    headers = sign_in(client, sender, lived["email"])
    base = f"/api/v1/stores/{lived['id']}/connections"
    put = client.put(
        f"{base}/shopify",
        json={"account_id": "shop-1", "access_token": "shpat_secret"},
        headers=headers,
    )
    assert put.status_code == 200
    assert "shpat_secret" not in put.text
    listed = client.get(base).json()
    assert [c["provider"] for c in listed] == ["meta", "shopify"]
    assert "token" not in json.dumps(listed)
    with tenant_transaction(app_engine, lived["id"]) as conn:
        raw = conn.execute(
            text("SELECT ciphertext, wrapped_key FROM store_connections WHERE provider = 'shopify'")
        ).one()
        assert b"shpat_secret" not in bytes(raw.ciphertext) + bytes(raw.wrapped_key)
        assert credentials(conn, lived["id"], "shopify", MasterKey.from_base64("k1", KEY)) == (
            "shop-1",
            "shpat_secret",
        )
    assert client.delete(f"{base}/shopify", headers=headers).status_code == 204
    assert client.delete(f"{base}/shopify", headers=headers).status_code == 404
    keyless = get_settings().model_copy(update={"token_encryption_key": None})
    app.dependency_overrides[get_app_settings] = lambda: keyless
    no_key = client.put(
        f"{base}/meta", json={"account_id": "act_1", "access_token": "x"}, headers=headers
    )
    assert (no_key.status_code, no_key.json()["code"]) == (503, "unavailable")


def test_the_executor_uses_the_store_s_own_meta_token(
    app_engine: Engine, lived: dict[str, Any]
) -> None:
    settings = get_settings().model_copy(update={"token_encryption_key": SecretStr(KEY)})
    resolve = store_meta_adapters(app_engine, settings)
    adapter = resolve("meta", lived["id"])
    assert isinstance(adapter, MetaAdsAdapter)
    assert resolve("simulator", lived["id"]) is None
    assert resolve("meta", uuid4()) is None


def test_the_export_has_everything_and_no_secret(
    client: TestClient, sender: RecordingSender, lived: dict[str, Any]
) -> None:
    sign_in(client, sender, lived["email"])
    response = client.get(f"/api/v1/stores/{lived['id']}/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["store_id"] == str(lived["id"])
    rows = manifest["rows"]
    for table in ("orders", "facts", "incidents", "decisions", "actions", "investigation_steps"):
        assert rows[table] > 0, table
    first = json.loads(archive.read("orders.jsonl").decode().splitlines()[0])
    assert first["store_id"] == str(lived["id"])
    connection = json.loads(archive.read("store_connections.jsonl").decode().splitlines()[0])
    assert set(connection) >= {"provider", "account_id"}
    assert not {"ciphertext", "wrapped_key", "nonce", "key_nonce"} & set(connection)
    access = json.loads(archive.read("access.json"))
    assert [o["email"] for o in access["owners"]] == [lived["email"]]
    assert "token_hash" not in json.dumps(access)
    assert b"EAAB-secret" not in response.content


def test_deleting_a_store_leaves_nothing(
    client: TestClient,
    sender: RecordingSender,
    app_engine: Engine,
    owner_engine: Engine,
    cassettes: Path,
    lived: dict[str, Any],
    golden_stockout: dict[str, Any],
) -> None:
    store = lived["id"]
    cassettes.mkdir(parents=True)
    (cassettes / "mine.json").write_text(json.dumps({"store_id": str(store)}), encoding="utf-8")
    (cassettes / "other.json").write_text(json.dumps({"store_id": str(uuid4())}), encoding="utf-8")
    headers = sign_in(client, sender, lived["email"])
    path = f"/api/v1/stores/{store}"
    wrong = client.request("DELETE", path, json={"confirm_store_id": str(uuid4())}, headers=headers)
    assert wrong.status_code == 422
    _, token = create_api_token(app_engine, store, "x", None, datetime.now(UTC))
    by_token = TestClient(app, base_url="https://testserver").request(
        "DELETE",
        path,
        json={"confirm_store_id": str(store)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert by_token.status_code == 403  # only a signed-in owner
    done = client.request("DELETE", path, json={"confirm_store_id": str(store)}, headers=headers)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["rows"]["stores"] == 1
    assert body["rows"]["orders"] > 0
    assert body["cassettes"] == 1
    # The proof: no row of the store in any tenant table, nor in the access tables.
    with owner_engine.connect() as conn:
        tables = (
            conn.execute(
                text(
                    "SELECT c.table_name FROM information_schema.columns c JOIN "
                    "information_schema.tables t USING (table_schema, table_name) WHERE "
                    "c.table_schema = 'public' AND c.column_name = 'store_id' AND "
                    "t.table_type = 'BASE TABLE'"
                )
            )
            .scalars()
            .all()
        )
        assert len(tables) >= 30
        left = {
            table: conn.execute(
                text(f'SELECT count(*) FROM "{table}" WHERE store_id = :s'), {"s": store}
            ).scalar_one()
            for table in tables
        }
        assert {t: n for t, n in left.items() if n} == {}
        for table in ("auth.memberships", "auth.api_tokens"):
            assert (
                conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE store_id = :s"), {"s": store}
                ).scalar_one()
                == 0
            )
        record = conn.execute(
            text(
                "SELECT requested_by, rows_deleted, audit_head FROM control.store_deletions "
                "WHERE store_id = :s"
            ),
            {"s": store},
        ).one()
        assert record.requested_by == f"owner:{lived['email']}"
        assert record.rows_deleted == body["rows"]
        assert record.audit_head is not None
        other = conn.execute(
            text("SELECT count(*) FROM orders WHERE store_id = :s"), {"s": golden_stockout["id"]}
        ).scalar_one()
    assert other > 0  # other stores are untouched
    assert not (cassettes / "mine.json").exists()
    assert (cassettes / "other.json").exists()
    assert client.get(f"{path}/decisions").status_code == 404  # no longer the owner's store


def test_delete_store_runs_only_in_the_store_s_own_transaction(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    with pytest.raises(Exception, match="own tenant transaction"), app_engine.begin() as conn:
        conn.execute(text("SELECT delete_store(:s, 'attacker')"), {"s": golden_stockout["id"]})


def test_retention_removes_old_traces(app_engine: Engine, owner_engine: Engine) -> None:
    manifest = next(m for m in load_suite("dev") if m.scenario_id == "dev-healthy-11")
    store = register(app_engine, manifest, 60)
    old, new = uuid4(), uuid4()
    for investigation in (old, new):
        trace = recorder(app_engine, store, investigation)
        trace(Step("started"))
        trace(Step("done"))
    now = datetime.now(UTC)
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE investigation_steps SET created_at = :t WHERE investigation_id = :i"),
            {"t": now - timedelta(days=31), "i": old},
        )
    purged = purge(app_engine, now, days=30)
    assert purged.traces >= 2
    with tenant_transaction(app_engine, store) as conn:
        kept = (
            conn.execute(
                text(
                    "SELECT DISTINCT investigation_id FROM investigation_steps WHERE store_id = :s"
                ),
                {"s": store},
            )
            .scalars()
            .all()
        )
    assert kept == [new]
