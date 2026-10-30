"""The agent's step trace for each investigation (model calls, tool calls, regenerations).

Written as the investigation runs, each step in its own short transaction, so a client can
follow it (server-sent events) while it runs. These are the product's model traces: kept 30
days (the retention job deletes older ones), while the verified investigation stays.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE TABLE investigation_steps (
            store_id          uuid NOT NULL REFERENCES stores (store_id),
            investigation_id  uuid NOT NULL,
            seq               integer NOT NULL CHECK (seq >= 1),
            kind              text NOT NULL,
            name              text,
            detail            jsonb NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (store_id, investigation_id, seq)
        );
        CREATE INDEX investigation_steps_created ON investigation_steps (store_id, created_at);
        ALTER TABLE investigation_steps ENABLE ROW LEVEL SECURITY;
        ALTER TABLE investigation_steps FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON investigation_steps
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT, DELETE ON investigation_steps TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS investigation_steps")
