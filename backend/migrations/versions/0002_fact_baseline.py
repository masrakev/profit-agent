"""Facts may name a baseline period (comparison facts such as Shapley contributions).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE facts
            ADD COLUMN baseline_start timestamptz,
            ADD COLUMN baseline_end timestamptz,
            ADD CONSTRAINT facts_baseline_check CHECK (
                (baseline_start IS NULL AND baseline_end IS NULL)
                OR (baseline_start < baseline_end AND baseline_end <= period_start)
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE facts
            DROP CONSTRAINT facts_baseline_check,
            DROP COLUMN baseline_end,
            DROP COLUMN baseline_start;
        """
    )
