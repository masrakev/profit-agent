"""WhatsApp in the delivery pipeline (Task 8 part B, ADR 0027).

Two subjects only WhatsApp delivers, one row per message as for the others:
- `goal_progress` (`<goal id>:<day>`): a goal's weekly tracking line;
- `decision_status` (`<decision id>:<status>`): a decision done or failed, so the owner who
  approved from the phone hears how it went.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE deliveries DROP CONSTRAINT deliveries_subject_check;
        ALTER TABLE deliveries ADD CONSTRAINT deliveries_subject_check
            CHECK (subject IN ('briefing', 'alert', 'decision', 'goal_progress',
                               'decision_status'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM deliveries WHERE subject IN ('goal_progress', 'decision_status');
        ALTER TABLE deliveries DROP CONSTRAINT deliveries_subject_check;
        ALTER TABLE deliveries ADD CONSTRAINT deliveries_subject_check
            CHECK (subject IN ('briefing', 'alert', 'decision'));
        """
    )
