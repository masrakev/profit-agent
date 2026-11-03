"""Conversations: the owner's questions and the answers they got, kept to be read again and
continued (step 4 of the web platform's redesign).

A conversation is a title (its first question) and its turns, in order. A turn keeps the
question as the owner asked it (typed or said), what it was about when asked about a decision
or a goal (by kind, id and the label the owner saw), and the Ask result as Ask returned it: the
facts and names it cites are read again when the turn is shown (facts never change). Store
deletion and export find both tables by their `store_id`.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE TABLE conversations (
            conversation_id  uuid PRIMARY KEY,
            store_id         uuid NOT NULL REFERENCES stores (store_id),
            title            text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now(),
            UNIQUE (store_id, conversation_id)
        );
        CREATE INDEX conversations_store ON conversations (store_id, updated_at);

        CREATE TABLE conversation_turns (
            turn_id          uuid PRIMARY KEY,
            store_id         uuid NOT NULL REFERENCES stores (store_id),
            conversation_id  uuid NOT NULL,
            position         integer NOT NULL CHECK (position >= 1),
            question         text NOT NULL CHECK (length(question) BETWEEN 1 AND 2000),
            via              text NOT NULL CHECK (via IN ('text', 'voice')),
            topic_kind       text CHECK (topic_kind IN ('decision', 'goal')),
            topic_id         uuid,
            topic_label      text CHECK (length(topic_label) BETWEEN 1 AND 200),
            ask_id           uuid NOT NULL,
            result           jsonb NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),
            UNIQUE (store_id, conversation_id, position),
            FOREIGN KEY (store_id, conversation_id)
                REFERENCES conversations (store_id, conversation_id),
            CHECK ((topic_kind IS NULL) = (topic_id IS NULL)
                   AND (topic_kind IS NULL) = (topic_label IS NULL))
        );

        ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON conversations
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT, UPDATE ON conversations TO {role};

        ALTER TABLE conversation_turns ENABLE ROW LEVEL SECURITY;
        ALTER TABLE conversation_turns FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON conversation_turns
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT ON conversation_turns TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_turns; DROP TABLE IF EXISTS conversations;")
