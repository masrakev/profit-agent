"""Privacy (ADR 0021): store deletion, its record, encrypted platform tokens, retention.

- `delete_store(target, actor)`: deletes every row of the store from every public table that
  has a `store_id` (found at run time, so a new tenant table is never missed), retrying across
  foreign keys, then the store itself (its owner memberships and API tokens cascade). It runs
  only inside the store's own tenant transaction (`app.store_id` = the store), and records the
  deletion, with the number of rows per table and the last hash of the store's audit chain, in
  `control.store_deletions`: the store's own audit log is deleted with everything else.
- `store_connections`: a store's Meta and Shopify access tokens, encrypted (envelope: a data
  key per token encrypts it, the master key from the environment wraps the data key).
- The retention job may delete expired sign-in links and sessions.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE TABLE store_connections (
            store_id      uuid NOT NULL REFERENCES stores (store_id),
            provider      text NOT NULL CHECK (provider IN ('meta', 'shopify')),
            account_id    text NOT NULL,
            key_id        text NOT NULL,
            wrapped_key   bytea NOT NULL,
            key_nonce     bytea NOT NULL,
            ciphertext    bytea NOT NULL,
            nonce         bytea NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (store_id, provider)
        );
        ALTER TABLE store_connections ENABLE ROW LEVEL SECURITY;
        ALTER TABLE store_connections FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON store_connections
            USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        GRANT SELECT, INSERT, UPDATE, DELETE ON store_connections TO {role};

        CREATE TABLE control.store_deletions (
            deletion_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id      uuid NOT NULL,
            requested_by  text NOT NULL,
            rows_deleted  jsonb NOT NULL,
            audit_head    text,
            deleted_at    timestamptz NOT NULL DEFAULT now()
        );
        GRANT SELECT ON control.store_deletions TO {role};

        CREATE FUNCTION public.delete_store(target uuid, actor text) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        DECLARE
            t record;
            counts jsonb := '{{}}'::jsonb;
            n bigint;
            blocked integer;
            pass integer := 0;
            head text;
        BEGIN
            IF current_setting('app.store_id', true) IS DISTINCT FROM target::text THEN
                RAISE EXCEPTION 'delete_store runs only in the store''s own tenant transaction'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            SELECT entry_hash INTO head FROM public.audit_log WHERE store_id = target
                ORDER BY seq DESC LIMIT 1;
            LOOP
                pass := pass + 1;
                blocked := 0;
                FOR t IN
                    SELECT c.table_name FROM information_schema.columns c
                    JOIN information_schema.tables tb
                      ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name
                    WHERE c.table_schema = 'public' AND c.column_name = 'store_id'
                      AND tb.table_type = 'BASE TABLE' AND c.table_name <> 'stores'
                    ORDER BY c.table_name
                LOOP
                    BEGIN
                        EXECUTE format('DELETE FROM public.%I WHERE store_id = $1', t.table_name)
                            USING target;
                        GET DIAGNOSTICS n = ROW_COUNT;
                        IF n > 0 THEN
                            counts := counts || jsonb_build_object(
                                t.table_name, coalesce((counts ->> t.table_name)::bigint, 0) + n
                            );
                        END IF;
                    EXCEPTION WHEN foreign_key_violation THEN
                        blocked := blocked + 1;  -- children first: retried next pass
                    END;
                END LOOP;
                EXIT WHEN blocked = 0;
                IF pass >= 25 THEN
                    RAISE EXCEPTION 'store % could not be deleted (foreign keys)', target;
                END IF;
            END LOOP;
            DELETE FROM public.stores WHERE store_id = target;
            GET DIAGNOSTICS n = ROW_COUNT;
            counts := counts || jsonb_build_object('stores', n);
            INSERT INTO control.store_deletions (store_id, requested_by, rows_deleted, audit_head)
                VALUES (target, actor, counts, head);
            RETURN counts;
        END
        $$;
        REVOKE ALL ON FUNCTION public.delete_store(uuid, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.delete_store(uuid, text) TO {role};

        GRANT DELETE ON auth.login_links, auth.sessions TO {role};
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.delete_store(uuid, text);
        DROP TABLE IF EXISTS control.store_deletions;
        DROP TABLE IF EXISTS store_connections;
        """
    )
