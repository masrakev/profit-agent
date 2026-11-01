"""WhatsApp buttons that decide (Task 8 part B, ADR 0027).

- `approvals.channel` gains `whatsapp`: a decision approved from a reply button. The button holds
  a short signed token naming an `approval_links` row: the email links' rules (single use, 24
  hours, spending caps) apply unchanged.
- `goal_links`: the single-use, 24-hour rows behind a "Confirm goal" button (confirming a goal
  commits no money).
- `voice_questions.channel` gains `whatsapp`: a voice note.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        ALTER TABLE approvals DROP CONSTRAINT approvals_channel_check;
        ALTER TABLE approvals ADD CONSTRAINT approvals_channel_check
            CHECK (channel IN ('api', 'email', 'whatsapp'));
        ALTER TABLE voice_questions DROP CONSTRAINT voice_questions_channel_check;
        ALTER TABLE voice_questions ADD CONSTRAINT voice_questions_channel_check
            CHECK (channel IN ('web', 'whatsapp'));

        CREATE TABLE goal_links (
            link_id     uuid PRIMARY KEY,
            store_id    uuid NOT NULL REFERENCES stores (store_id),
            goal_id     uuid NOT NULL REFERENCES goals (goal_id),
            expires_at  timestamptz NOT NULL,
            used_at     timestamptz,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX goal_links_store ON goal_links (store_id, goal_id);

        ALTER TABLE goal_links ENABLE ROW LEVEL SECURITY;
        ALTER TABLE goal_links FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON goal_links
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT, UPDATE ON goal_links TO {role};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS goal_links;
        DELETE FROM voice_questions WHERE channel = 'whatsapp';
        ALTER TABLE voice_questions DROP CONSTRAINT voice_questions_channel_check;
        ALTER TABLE voice_questions ADD CONSTRAINT voice_questions_channel_check
            CHECK (channel IN ('web'));
        ALTER TABLE approvals DROP CONSTRAINT approvals_channel_check;
        ALTER TABLE approvals ADD CONSTRAINT approvals_channel_check
            CHECK (channel IN ('api', 'email'));
        """
    )
