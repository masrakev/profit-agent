"""Synthetic-store flag and persisted incidents.

`stores.synthetic` marks benchmark stores: only their data may be sent to a model in Contributor
mode (ADR 0009). `incidents` keeps the latest detection run's incidents per store so that agent
tools can read them by id.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        ALTER TABLE stores ADD COLUMN synthetic boolean NOT NULL DEFAULT false;

        CREATE TABLE incidents (
            store_id            uuid NOT NULL REFERENCES stores (store_id),
            incident_id         text NOT NULL,
            as_of               date NOT NULL,
            thresholds_version  integer NOT NULL,
            category            text NOT NULL
                                CHECK (category IN ('profitability', 'data_quality')),
            alert               text NOT NULL,
            first_seen          date NOT NULL,
            last_seen           date NOT NULL,
            payload             jsonb NOT NULL,
            updated_at          timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (store_id, incident_id)
        );
        ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
        ALTER TABLE incidents FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON incidents
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT, UPDATE ON incidents TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS incidents; ALTER TABLE stores DROP COLUMN IF EXISTS synthetic")
