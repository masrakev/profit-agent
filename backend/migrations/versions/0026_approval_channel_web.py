"""Approvals get a `web` channel: the signed-in web app, apart from an API token.

An owner who approves in the app (a session) and a script that approves with an API token were
both recorded as `api`. The audit log now tells them apart: `web`, `api`, `email` (a signed link)
and `whatsapp` (a reply button). Earlier approvals keep their channel; their origin (session or
token) still says which it was.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE approvals DROP CONSTRAINT approvals_channel_check;
        ALTER TABLE approvals ADD CONSTRAINT approvals_channel_check
            CHECK (channel IN ('web', 'api', 'email', 'whatsapp'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE approvals SET channel = 'api' WHERE channel = 'web';
        ALTER TABLE approvals DROP CONSTRAINT approvals_channel_check;
        ALTER TABLE approvals ADD CONSTRAINT approvals_channel_check
            CHECK (channel IN ('api', 'email', 'whatsapp'));
        """
    )
