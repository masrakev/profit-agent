"""Database engines and tenant-scoped transactions.

The application always talks to PostgreSQL as the non-superuser application role. Every unit of
work runs inside `tenant_transaction`, which sets `app.store_id` for the current transaction only
(`set_config(..., is_local => true)`), so a pooled connection never leaks a tenant to the next user.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

from app.config import get_settings


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, future=True)


def app_engine() -> Engine:
    return make_engine(get_settings().app_database_url)


@contextmanager
def tenant_transaction(engine: Engine, store_id: UUID) -> Iterator[Connection]:
    with engine.begin() as conn:
        set_tenant(conn, store_id)
        yield conn


def set_tenant(conn: Connection, store_id: UUID) -> None:
    conn.execute(text("SELECT set_config('app.store_id', :sid, true)"), {"sid": str(store_id)})


def refresh_planner_statistics(engine: Engine) -> None:
    """ANALYZE the domain tables after a bulk load (see migration 0001). Run after commit."""
    with engine.begin() as conn:
        conn.execute(text("SELECT refresh_planner_statistics()"))
