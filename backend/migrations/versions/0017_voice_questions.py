"""Voice questions: what an owner's recording said, how long it was and what transcribing it
cost (Task 8 part A, ADR 0026).

The audio itself is never stored. `status` is the Ask status the transcript led to, or
`no_speech` when nothing was heard; `ask_id` links that Ask. `flags` carries
`no_instruction_following_from_data` when the transcript read like an instruction.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE TABLE voice_questions (
            voice_id          uuid PRIMARY KEY,
            store_id          uuid NOT NULL REFERENCES stores (store_id),
            channel           text NOT NULL CHECK (channel IN ('web')),
            transcript        text NOT NULL,
            audio_duration_ms integer NOT NULL CHECK (audio_duration_ms >= 0),
            billed_seconds    integer NOT NULL CHECK (billed_seconds >= 0),
            cost_usd          numeric(12, 6) NOT NULL CHECK (cost_usd >= 0),
            model             text NOT NULL,
            flags             jsonb NOT NULL DEFAULT '[]'::jsonb,
            ask_id            uuid,
            question_type     text,
            status            text,
            created_at        timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX voice_questions_store ON voice_questions (store_id, created_at);

        ALTER TABLE voice_questions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE voice_questions FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON voice_questions
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT, UPDATE ON voice_questions TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS voice_questions;")
