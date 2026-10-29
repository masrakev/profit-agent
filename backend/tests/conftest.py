"""Shared fixtures. Database tests run against a fresh `profit_test` database, migrated with
Alembic as the owner role and exercised as the non-superuser application role."""

import os
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.db import make_engine, tenant_transaction
from app.detection import pipeline
from app.domain.models import Store
from app.domain.repositories import StoreRepository
from bench.generator.load import load
from bench.scenarios.manifest import load_suite

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_DB = os.environ.get("TEST_DATABASE_NAME", "profit_test")


def _with_db(url: str, database: str) -> str:
    return make_url(url).set(database=database).render_as_string(hide_password=False)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never reach a live model: the real HTTP transport is disabled."""

    def refuse(self: object, request: object) -> object:
        raise RuntimeError("network access is disabled in tests; use a fake or replay transport")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse)


@pytest.fixture(scope="session")
def database_urls() -> Iterator[tuple[str, str]]:
    """(owner URL, app URL) of a freshly created and migrated test database."""
    settings = get_settings()
    maintenance = create_engine(
        _with_db(settings.database_url, "postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with maintenance.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    except OperationalError as exc:
        pytest.fail(f"PostgreSQL is not reachable ({exc.orig}); run `make up` first.")
    finally:
        maintenance.dispose()

    owner_url = _with_db(settings.database_url, TEST_DB)
    app_url = _with_db(settings.app_database_url, TEST_DB)
    config = Config(os.path.join(ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(ROOT, "backend", "migrations"))
    config.attributes["url"] = owner_url
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")

    # CLIs called from tests read their URLs from settings.
    previous = {k: os.environ.get(k) for k in ("DATABASE_URL", "APP_DATABASE_URL")}
    os.environ["DATABASE_URL"] = owner_url
    os.environ["APP_DATABASE_URL"] = app_url
    get_settings.cache_clear()
    yield owner_url, app_url
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def owner_engine(database_urls: tuple[str, str]) -> Iterator[Engine]:
    engine = make_engine(database_urls[0])
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(database_urls: tuple[str, str]) -> Iterator[Engine]:
    engine = make_engine(database_urls[1])
    yield engine
    engine.dispose()


def create_store(engine: Engine, currency: str = "USD", name: str = "Test store") -> UUID:
    store_id = uuid4()
    with tenant_transaction(engine, store_id) as conn:
        StoreRepository(conn).create(Store(store_id=store_id, name=name, currency=currency))
    return store_id


@pytest.fixture
def store_id(app_engine: Engine) -> UUID:
    return create_store(app_engine)


@pytest.fixture(scope="session")
def golden_stockout(app_engine: Engine) -> dict[str, Any]:
    """The golden stockout-on-promoted store, loaded once and run through detection."""
    manifest = next(
        m for m in load_suite("golden") if m.scenario_id == "golden-stockout_on_promoted"
    )
    data = manifest.generate()
    load(app_engine, data, manifest.config)
    result = pipeline.run_pipeline(app_engine, data.store.store_id)
    label = manifest.labels[0]
    return {
        "id": data.store.store_id,
        "incident": result.incidents[0].incident_id,
        "product": next(e.id for e in label.entities if e.kind.value == "product"),
        "campaign": next(c.id for c in data.campaigns),
        "products": [p.id for p in data.products],
        "fault_day": manifest.config.start_date + timedelta(days=label.start_day),
        "impact_fact": result.incidents[0].monthly_impact_fact_id,
    }
