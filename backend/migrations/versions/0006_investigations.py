"""Investigations: the agent's verified analysis of an incident, cached by content.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE TABLE investigations (
            investigation_id  uuid PRIMARY KEY,
            store_id          uuid NOT NULL REFERENCES stores (store_id),
            incident_id       text NOT NULL,
            cache_key         char(64) NOT NULL,
            status            text NOT NULL
                              CHECK (status IN ('complete', 'fallback', 'partial', 'invalid')),
            model             text NOT NULL,
            prompt_version    text NOT NULL,
            payload           jsonb NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX investigations_store_cache ON investigations (store_id, cache_key);
        ALTER TABLE investigations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE investigations FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON investigations
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT ON investigations TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS investigations")
