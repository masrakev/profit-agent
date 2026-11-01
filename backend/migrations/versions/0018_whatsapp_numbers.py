"""The owner's WhatsApp number, verified by a code (Task 8 part B, ADR 0027).

- `store_settings.whatsapp_number`: the number the owner enters (E.164, with its `+`).
- `whatsapp_numbers`: one per store, the number as WhatsApp writes it (digits only), `pending`
  until the owner types on the web the code sent to it on WhatsApp, then `verified`. The code is
  kept as an HMAC digest with its expiry and attempts; `last_inbound_at` opens the 24-hour window
  in which session messages may be sent. A verified number belongs to one store only.
- `whatsapp_store_for(number)`: the store of a verified number, for the webhook, which knows no
  tenant before it reads the sender (SECURITY DEFINER, like `deliveries_ready_stores`).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        ALTER TABLE store_settings ADD COLUMN whatsapp_number text
            CHECK (whatsapp_number ~ '^[+][1-9][0-9]{{6,14}}$');

        CREATE TABLE whatsapp_numbers (
            store_id         uuid PRIMARY KEY REFERENCES stores (store_id),
            phone            text NOT NULL CHECK (phone ~ '^[1-9][0-9]{{6,14}}$'),
            status           text NOT NULL CHECK (status IN ('pending', 'verified')),
            code_hash        bytea,
            code_expires_at  timestamptz,
            code_attempts    integer NOT NULL DEFAULT 0,
            codes_sent       integer NOT NULL DEFAULT 0,
            last_code_at     timestamptz,
            verified_at      timestamptz,
            last_inbound_at  timestamptz,
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX whatsapp_numbers_verified ON whatsapp_numbers (phone)
            WHERE status = 'verified';

        ALTER TABLE whatsapp_numbers ENABLE ROW LEVEL SECURITY;
        ALTER TABLE whatsapp_numbers FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON whatsapp_numbers
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_numbers TO {role};

        CREATE FUNCTION public.whatsapp_store_for(number text) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
            SELECT store_id FROM public.whatsapp_numbers
            WHERE phone = number AND status = 'verified'
        $$;
        REVOKE ALL ON FUNCTION public.whatsapp_store_for(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.whatsapp_store_for(text) TO {role};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.whatsapp_store_for(text);
        DROP TABLE IF EXISTS whatsapp_numbers;
        ALTER TABLE store_settings DROP COLUMN IF EXISTS whatsapp_number;
        """
    )
