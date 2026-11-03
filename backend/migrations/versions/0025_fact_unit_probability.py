"""Facts get a `probability` unit: a chance, 0 to 1, shown as a percentage.

Goal chances were `ratio` facts and read "0.48× to 0.51×"; as `probability` they read
"48 to 51%". Existing facts keep their unit (a fact never changes: a recomputed chance is a new
fact).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE facts DROP CONSTRAINT facts_unit_check;
        ALTER TABLE facts ADD CONSTRAINT facts_unit_check
            CHECK (unit IN ('money', 'count', 'ratio', 'days', 'probability'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE facts DROP CONSTRAINT facts_unit_check;
        ALTER TABLE facts ADD CONSTRAINT facts_unit_check
            CHECK (unit IN ('money', 'count', 'ratio', 'days'));
        """
    )
