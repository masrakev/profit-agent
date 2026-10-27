"""Row-level security: a store can neither read nor write another store's rows."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db import refresh_planner_statistics, tenant_transaction
from app.domain.models import Product
from app.domain.repositories import ProductRepository
from tests.builders import Scenario
from tests.conftest import create_store

pytestmark = pytest.mark.db

TENANT_TABLES = (
    "stores",
    "products",
    "orders",
    "order_lines",
    "refunds",
    "inventory_snapshots",
    "ad_campaigns",
    "ad_campaign_products",
    "ad_metrics_daily",
    "cost_items",
    "facts",
    "fact_lineage",
    "audit_log",
)


def _store_with_data(engine: Engine) -> tuple[UUID, UUID]:
    store = create_store(engine)
    with tenant_transaction(engine, store) as conn:
        s = Scenario(conn, store)
        product = s.product("10.00", "4.00", "0.50")
        s.order("2026-01-05T10:00:00", [(product, 1, "10.00", "4.00", "0.50")], payment_fee="0.59")
    return store, product


def test_app_role_is_not_privileged(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    assert (row.rolsuper, row.rolbypassrls) == (False, False)


def test_app_role_can_refresh_statistics(app_engine: Engine) -> None:
    refresh_planner_statistics(app_engine)


def test_role_without_grant_cannot_refresh_statistics(owner_engine: Engine) -> None:
    probe = f"probe_{uuid4().hex[:12]}"
    with owner_engine.begin() as conn:
        conn.execute(text(f"CREATE ROLE {probe} NOLOGIN"))
    try:
        with owner_engine.begin() as conn:
            conn.execute(text(f"SET LOCAL ROLE {probe}"))
            with pytest.raises(ProgrammingError, match="permission denied for function"):
                conn.execute(text("SELECT public.refresh_planner_statistics()"))
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text(f"DROP ROLE {probe}"))


def test_refresh_statistics_function_is_hardened(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        fn = conn.execute(
            text(
                "SELECT p.prosecdef, p.pronargs, p.proconfig, "
                "has_function_privilege('public', p.oid, 'EXECUTE') AS public_can_execute, "
                "ARRAY(SELECT r.rolname FROM aclexplode(p.proacl) a "
                "      JOIN pg_roles r ON r.oid = a.grantee "
                "      WHERE a.privilege_type = 'EXECUTE' AND a.grantee <> p.proowner) AS grantees "
                "FROM pg_proc p WHERE p.oid = 'public.refresh_planner_statistics()'::regprocedure"
            )
        ).one()
    assert fn.prosecdef is True
    assert fn.pronargs == 0
    assert fn.proconfig == ["search_path=pg_catalog, public, pg_temp"]
    assert fn.public_can_execute is False
    assert fn.grantees == ["profit_app"]


def test_every_tenant_table_has_an_index_leading_with_store_id(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.relname, bool_or(a.attname = 'store_id') AS leads_with_store "
                "FROM pg_index i "
                "JOIN pg_class t ON t.oid = i.indrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace AND n.nspname = 'public' "
                "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = i.indkey[0] "
                "GROUP BY t.relname"
            )
        ).all()
    leading = {r.relname for r in rows if r.leads_with_store}
    assert set(TENANT_TABLES) <= leading, set(TENANT_TABLES) - leading


def test_every_table_has_store_id_and_forced_rls(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "EXISTS (SELECT 1 FROM information_schema.columns k WHERE k.table_name = c.relname "
                "AND k.column_name = 'store_id' AND k.table_schema = 'public') AS has_store "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'"
            )
        ).all()
    assert sorted(t.relname for t in tables) == sorted(TENANT_TABLES)
    assert all(t.relrowsecurity and t.relforcerowsecurity and t.has_store for t in tables)


def test_store_cannot_read_other_store(app_engine: Engine) -> None:
    store_a, _ = _store_with_data(app_engine)
    store_b, _ = _store_with_data(app_engine)
    with tenant_transaction(app_engine, store_a) as conn:
        for table in TENANT_TABLES:
            seen = set(conn.execute(text(f"SELECT DISTINCT store_id FROM {table}")).scalars())
            assert store_b not in seen, table
        assert set(conn.execute(text("SELECT store_id FROM order_lines")).scalars()) == {store_a}
        # Even an explicit filter on B's id returns nothing.
        count = conn.execute(
            text("SELECT count(*) FROM products WHERE store_id = :b"), {"b": store_b}
        ).scalar_one()
        assert count == 0


def test_store_cannot_write_other_store(app_engine: Engine) -> None:
    store_a, _ = _store_with_data(app_engine)
    store_b, product_b = _store_with_data(app_engine)
    with tenant_transaction(app_engine, store_a) as conn:
        updated = conn.execute(
            text("UPDATE products SET price = 0 WHERE id = :p"), {"p": product_b}
        ).rowcount
        deleted = conn.execute(
            text("DELETE FROM order_lines WHERE store_id = :b"), {"b": store_b}
        ).rowcount
        assert (updated, deleted) == (0, 0)
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        tenant_transaction(app_engine, store_a) as conn,
    ):
        ProductRepository(conn).add_many(
            [
                Product(
                    id=uuid4(),
                    store_id=store_b,
                    sku="EVIL",
                    name="x",
                    price=1,
                    unit_cost=1,
                    unit_fee=0,
                    currency="USD",
                )
            ]
        )
    with tenant_transaction(app_engine, store_b) as conn:
        price = conn.execute(text("SELECT price FROM products WHERE id = :p"), {"p": product_b})
        assert price.scalar_one() == 10


def test_no_tenant_means_no_rows(app_engine: Engine) -> None:
    _store_with_data(app_engine)
    with app_engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar_one() == 0
        conn.execute(text("SELECT set_config('app.store_id', '', true)"))
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar_one() == 0


def test_cross_store_references_are_rejected(app_engine: Engine) -> None:
    """Composite foreign keys stop a store from pointing at another store's rows."""
    _, product_b = _store_with_data(app_engine)
    store_a = create_store(app_engine)
    with pytest.raises(DBAPIError), tenant_transaction(app_engine, store_a) as conn:
        Scenario(conn, store_a).order("2026-01-05T10:00:00", [(product_b, 1, "1.00", "0", "0")])


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET actor = 'x'",
        "DELETE FROM audit_log",
        "UPDATE facts SET method = 'x'",
        "DELETE FROM facts",
        "UPDATE fact_lineage SET role = 'x'",
        "DELETE FROM fact_lineage",
    ],
)
def test_audit_log_and_facts_are_append_only(app_engine: Engine, statement: str) -> None:
    store, _ = _store_with_data(app_engine)
    with (
        pytest.raises(ProgrammingError, match="permission denied"),
        tenant_transaction(app_engine, store) as conn,
    ):
        conn.execute(text(statement))
