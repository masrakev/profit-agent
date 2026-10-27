"""Per-store settings (one row per store), with row-level security like every tenant table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE TABLE store_settings (
            store_id                    uuid PRIMARY KEY REFERENCES stores (store_id),
            timezone                    text NOT NULL,
            currency                    char(3) NOT NULL CHECK (currency ~ '^[A-Z]{{3}}$'),
            daily_brief_enabled         boolean NOT NULL,
            daily_brief_at              time NOT NULL,
            daily_brief_weekdays        smallint[] NOT NULL,
            weekly_report_enabled       boolean NOT NULL,
            weekly_report_weekday       smallint NOT NULL
                                        CHECK (weekly_report_weekday BETWEEN 1 AND 7),
            weekly_report_at            time NOT NULL,
            monthly_review_enabled      boolean NOT NULL,
            monthly_review_day          smallint NOT NULL
                                        CHECK (monthly_review_day BETWEEN 1 AND 28),
            monthly_review_at           time NOT NULL,
            alert_channels              text[] NOT NULL CHECK (cardinality(alert_channels) > 0),
            quiet_hours_start           time NOT NULL,
            quiet_hours_end             time NOT NULL,
            alert_budget_per_day        integer NOT NULL CHECK (alert_budget_per_day >= 0),
            materiality_absolute        numeric(18, 4) NOT NULL CHECK (materiality_absolute >= 0),
            materiality_relative        numeric(9, 6) NOT NULL
                                        CHECK (materiality_relative BETWEEN 0 AND 1),
            detail_level                text NOT NULL
                                        CHECK (detail_level IN ('brief', 'standard', 'expert')),
            autonomy                    jsonb NOT NULL,
            max_budget_change_ratio     numeric(9, 6) NOT NULL
                                        CHECK (max_budget_change_ratio BETWEEN 0 AND 1),
            max_budget_changes_per_day  integer NOT NULL CHECK (max_budget_changes_per_day >= 0),
            language                    text NOT NULL,
            updated_at                  timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE store_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE store_settings FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON store_settings
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT, UPDATE ON store_settings TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS store_settings")
