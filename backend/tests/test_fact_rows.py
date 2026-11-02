"""The rows behind a base fact, with their dates and amounts, add up to the fact."""

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine

from app.api.deps import get_engine
from app.api.main import app
from app.db import tenant_transaction
from app.facts.engine import FactEngine
from app.facts.formulas import REGISTRY
from app.facts.model import Fact, Period, Scope, ScopeKind
from app.facts.rows import VIEWS, data_up_to, source_rows
from tests.api_helpers import act_as

pytestmark = pytest.mark.db


@pytest.fixture
def conn(app_engine: Engine, golden_stockout: dict[str, Any]) -> Iterator[Connection]:
    with tenant_transaction(app_engine, golden_stockout["id"]) as c:
        yield c


def _scope(kind: ScopeKind, store: dict[str, Any]) -> Scope:
    if kind is ScopeKind.PRODUCT:
        return Scope.product(store["product"])
    if kind is ScopeKind.CAMPAIGN:
        return Scope.campaign(store["campaign"])
    return Scope.store()


def _all_rows(conn: Connection, fact: Fact, table: str, page: int = 7) -> list[Any]:
    ids = [s.id for s in fact.lineage.sources if s.table == table]
    out: list[Any] = []
    after = None
    while True:
        chunk = source_rows(conn, fact, table, ids, after=after, limit=page)
        out.extend(chunk)
        if len(chunk) < page:
            return out
        after = (chunk[-1].day, chunk[-1].id)


@pytest.mark.parametrize("formula_id", sorted(VIEWS))
def test_the_rows_add_up_to_the_fact(
    conn: Connection, golden_stockout: dict[str, Any], formula_id: str
) -> None:
    formula = REGISTRY.get(formula_id)
    scope = _scope(min(formula.scopes), golden_stockout)
    day = golden_stockout["fault_day"]
    period = Period.days(day - timedelta(days=14), day)
    fact = FactEngine(conn, golden_stockout["id"]).fact(formula_id, scope, period)
    assert fact.is_defined, fact.undefined_reason
    table = VIEWS[formula_id].table
    rows = _all_rows(conn, fact, table)
    assert len(rows) == len([s for s in fact.lineage.sources if s.table == table])
    assert sum((r.amount for r in rows), Decimal(0)) == fact.value
    days = [r.day for r in rows if r.day is not None]
    assert days == sorted(days)
    assert len({r.id for r in rows}) == len(rows)  # pages neither repeat nor skip a row
    if formula_id != "orders":  # an order is about several products: it names none
        assert all(r.label for r in rows)


def test_sources_say_how_recent_their_data_is(
    conn: Connection, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    last = data_up_to(conn, store, "ad_metrics_daily")
    assert last is not None
    assert last >= golden_stockout["fault_day"]
    assert data_up_to(conn, store, "products") is None
    assert data_up_to(conn, store, "nowhere") is None


@pytest.fixture
def client(app_engine: Engine) -> Iterator[TestClient]:
    app.dependency_overrides[get_engine] = lambda: app_engine
    act_as(app)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_api_pages_through_a_facts_rows(
    client: TestClient, golden_stockout: dict[str, Any], app_engine: Engine
) -> None:
    base = f"/api/v1/stores/{golden_stockout['id']}"
    overview = client.get(f"{base}/overview").json()
    net = next(v for v in overview["facts"].values() if v["metric"] == "net_profit")
    detail = client.get(f"{base}/facts/{net['fact_id']}").json()
    assert detail["sources"] == []  # a derived fact: its parents, no rows
    assert client.get(f"{base}/facts/{net['fact_id']}/rows").json() == {
        "items": [],
        "next_cursor": None,
    }
    after_ads = next(p["fact"] for p in detail["parents"] if p["role"] == "contribution_after_ads")
    spend_id = next(
        p["fact"]["fact_id"]
        for p in client.get(f"{base}/facts/{after_ads['fact_id']}").json()["parents"]
        if p["fact"]["metric"] == "ad_spend"
    )
    spend = client.get(f"{base}/facts/{spend_id}").json()
    (source,) = spend["sources"]
    assert source["table"] == "ad_metrics_daily"
    assert source["source"] == "Meta Ads · Daily spend"
    assert source["data_up_to"] >= spend["fact"]["period_start"][:10]
    first = client.get(f"{base}/facts/{spend_id}/rows", params={"limit": 3}).json()
    assert len(first["items"]) == 3
    assert first["items"][0]["amount"]["formatted"].startswith("$")
    assert first["items"][0]["label"].startswith("Campaign ")  # the golden store's names
    assert first["next_cursor"]
    second = client.get(
        f"{base}/facts/{spend_id}/rows", params={"limit": 3, "cursor": first["next_cursor"]}
    ).json()
    assert {r["id"] for r in first["items"]}.isdisjoint({r["id"] for r in second["items"]})
    assert second["items"][0]["day"] >= first["items"][-1]["day"]
    assert (
        client.get(f"{base}/facts/{spend_id}/rows", params={"table": "orders"}).status_code == 404
    )
    assert (
        client.get(f"{base}/facts/{spend_id}/rows", params={"cursor": "bm90LWEta2V5"}).status_code
        == 422
    )
    assert client.get(f"{base}/facts/999999999/rows").status_code == 404
