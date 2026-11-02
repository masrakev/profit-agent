"""How many draws an estimate was simulated or resampled from.

An estimate's range comes from a number of simulated or resampled draws (the store twin's Monte
Carlo, a goal forecast's paths, an impact's block bootstrap); the proof says how many. Null for
exact facts and for estimates made without draws (a fitted interval, a sum of ranges). Part of
the fact's hash when present, like `significant`, so existing facts keep their hashes.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE facts ADD COLUMN draws integer "
        "CONSTRAINT facts_draws_check CHECK (draws IS NULL OR (draws > 0 AND kind = 'estimate'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE facts DROP COLUMN draws")
