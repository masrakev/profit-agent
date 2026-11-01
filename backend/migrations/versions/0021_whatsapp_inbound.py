"""WhatsApp inbound messages (Task 8 part B, ADR 0027), in a schema of their own.

A message arrives before any store is known (the webhook reads the sender first), so, like the
`auth` schema, these tables are not tenant data under row-level security:

- `whatsapp.inbound`: one row per WhatsApp message id (the primary key: a message Meta delivers
  again is stored and processed once), written by the webhook and processed by a job. Its
  content (a text, a media id, a button id) is cleared once processed, and so is the sender's
  number; the row stays, for idempotency, until the retention job deletes it after 30 days.
- `whatsapp.refusals`: the HMAC of each unknown number already refused, so that it gets one polite
  refusal and nothing else; never the number itself.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE SCHEMA whatsapp;

        CREATE TABLE whatsapp.inbound (
            message_id    text PRIMARY KEY CHECK (length(message_id) BETWEEN 1 AND 256),
            phone         text NOT NULL,
            kind          text NOT NULL CHECK (kind IN ('text', 'audio', 'button', 'other')),
            content       jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            status        text NOT NULL CHECK (status IN ('pending', 'done', 'refused', 'failed')),
            attempts      integer NOT NULL DEFAULT 0,
            store_id      uuid,
            outcome       text,
            received_at   timestamptz NOT NULL DEFAULT now(),
            leased_until  timestamptz,
            processed_at  timestamptz
        );
        CREATE INDEX inbound_pending ON whatsapp.inbound (status, received_at);
        CREATE INDEX inbound_store ON whatsapp.inbound (store_id);

        CREATE TABLE whatsapp.refusals (
            phone_hash  bytea PRIMARY KEY,
            refused_at  timestamptz NOT NULL DEFAULT now()
        );

        GRANT USAGE ON SCHEMA whatsapp TO {role};
        GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp.inbound TO {role};
        GRANT SELECT, INSERT ON whatsapp.refusals TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS whatsapp CASCADE;")
