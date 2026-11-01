"""A goal's weekly status while its plan's steps wait for the owner's approval.

`waiting_for_approval`: steps due so far are proposed decisions not yet approved. The plan has
not started, so its milestones and verdict cannot be judged: no `behind`, no verdict drop, no
revision proposal, a prompt to approve instead.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE goal_progress DROP CONSTRAINT goal_progress_status_check;
        ALTER TABLE goal_progress ADD CONSTRAINT goal_progress_status_check
            CHECK (status IN ('ahead', 'on_track', 'behind', 'waiting_for_approval'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE goal_progress SET status = NULL WHERE status = 'waiting_for_approval';
        ALTER TABLE goal_progress DROP CONSTRAINT goal_progress_status_check;
        ALTER TABLE goal_progress ADD CONSTRAINT goal_progress_status_check
            CHECK (status IN ('ahead', 'on_track', 'behind'));
        """
    )
