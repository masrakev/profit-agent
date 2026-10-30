"""The scheduler's list of stores: ids only, through a SECURITY DEFINER function.

The scheduler runs each store's briefings and detection inside that store's own tenant
transaction; this is how it learns which stores exist (the application role cannot list
`stores` across tenants).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE FUNCTION public.scheduled_store_ids() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$ SELECT store_id FROM public.stores ORDER BY store_id $$;
        REVOKE ALL ON FUNCTION public.scheduled_store_ids() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.scheduled_store_ids() TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.scheduled_store_ids()")
