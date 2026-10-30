"""Alerts, deliveries, and the address messages go to.

- `alerts`: one row per incident and level (an escalation is a new alert, a repeat is not);
  sent, held for quiet hours, or deferred to the next briefing (over the daily budget).
- `deliveries`: one per message and channel (unique), with attempts, the provider's message id
  and the last error; the worker retries pending rows with backoff.
- `store_settings.notification_email`: where email goes (none: email deliveries are skipped).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        ALTER TABLE store_settings ADD COLUMN notification_email text;

        CREATE TABLE alerts (
            alert_id      uuid PRIMARY KEY,
            store_id      uuid NOT NULL REFERENCES stores (store_id),
            incident_id   text NOT NULL,
            level         text NOT NULL CHECK (level IN ('critical', 'high', 'normal',
                          'data_quality')),
            status        text NOT NULL CHECK (status IN ('sent', 'held', 'deferred',
                          'briefed')),
            reason        text,
            decision_id   uuid,
            local_date    date NOT NULL,
            deliver_at    timestamptz NOT NULL,
            briefing_id   uuid,
            created_at    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (store_id, incident_id, level),
            UNIQUE (store_id, alert_id)
        );
        CREATE INDEX alerts_store_day ON alerts (store_id, local_date);

        CREATE TABLE deliveries (
            delivery_id          uuid PRIMARY KEY,
            store_id             uuid NOT NULL REFERENCES stores (store_id),
            subject              text NOT NULL CHECK (subject IN ('briefing', 'alert',
                                 'decision')),
            subject_id           text NOT NULL,
            channel              text NOT NULL CHECK (channel IN ('web', 'email', 'whatsapp')),
            recipient            text,
            status               text NOT NULL CHECK (status IN ('pending', 'sent', 'failed',
                                 'skipped')),
            attempts             integer NOT NULL DEFAULT 0,
            available_at         timestamptz NOT NULL,
            provider             text,
            provider_message_id  text,
            last_error           text,
            created_at           timestamptz NOT NULL DEFAULT now(),
            sent_at              timestamptz,
            UNIQUE (store_id, subject, subject_id, channel),
            UNIQUE (store_id, delivery_id)
        );
        CREATE INDEX deliveries_store_ready ON deliveries (store_id, status, available_at);

        -- Stores with deliveries due: ids only, the worker then works inside each store's
        -- tenant transaction (as for the outbox).
        CREATE FUNCTION public.deliveries_ready_stores(ready_at timestamptz) RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
            SELECT DISTINCT store_id FROM public.deliveries
            WHERE status = 'pending' AND available_at <= ready_at
        $$;
        REVOKE ALL ON FUNCTION public.deliveries_ready_stores(timestamptz) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.deliveries_ready_stores(timestamptz) TO {role};
        """
    )
    for table in ("alerts", "deliveries"):
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table}
                USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
            GRANT SELECT, INSERT, UPDATE ON {table} TO {role};
            """
        )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.deliveries_ready_stores(timestamptz);
        DROP TABLE IF EXISTS deliveries, alerts;
        ALTER TABLE store_settings DROP COLUMN IF EXISTS notification_email;
        """
    )
