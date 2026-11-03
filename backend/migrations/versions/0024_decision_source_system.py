"""A decision the agent proposed on its own: source `system`.

Besides an alert (`incident`), a question, the owner's own change (`owner`) and a goal's plan
(`goal`), the agent proposes changes it simulated by itself, such as a budget review; their
options carry their simulated impact like any other.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE decisions DROP CONSTRAINT decisions_source_check;
        ALTER TABLE decisions ADD CONSTRAINT decisions_source_check
            CHECK (source IN ('incident', 'question', 'owner', 'goal', 'system'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE decisions DROP CONSTRAINT decisions_source_check;
        ALTER TABLE decisions ADD CONSTRAINT decisions_source_check
            CHECK (source IN ('incident', 'question', 'owner', 'goal'));
        """
    )
