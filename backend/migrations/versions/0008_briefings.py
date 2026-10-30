"""Briefings: the daily brief, weekly report and monthly review, as generated.

One briefing per store, kind and store-local day (the scheduler's key, so a briefing is never
generated twice for the same slot). Rows are immutable: the application role can insert and
read them, not change them.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE TABLE briefings (
            briefing_id      uuid PRIMARY KEY,
            store_id         uuid NOT NULL REFERENCES stores (store_id),
            kind             text NOT NULL CHECK (kind IN ('daily', 'weekly', 'monthly')),
            local_date       date NOT NULL,
            period_start     date NOT NULL,
            period_end       date NOT NULL,
            status           text NOT NULL CHECK (status IN ('narrated', 'facts_only')),
            content          jsonb NOT NULL,
            narrative        text,
            fact_ids         bigint[] NOT NULL,
            prompt_version   text,
            model            text,
            attempts         integer NOT NULL DEFAULT 0,
            fallback_reason  text,
            input_tokens     integer NOT NULL DEFAULT 0,
            output_tokens    integer NOT NULL DEFAULT 0,
            cost_usd         numeric(12, 6) NOT NULL DEFAULT 0,
            created_at       timestamptz NOT NULL DEFAULT now(),
            CHECK (period_end > period_start),
            UNIQUE (store_id, kind, local_date),
            UNIQUE (store_id, briefing_id)
        );
        CREATE INDEX briefings_store_created ON briefings (store_id, created_at);
        ALTER TABLE briefings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE briefings FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON briefings
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT ON briefings TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS briefings")
