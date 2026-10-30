"""Owners, sign-in links, sessions and API tokens (schema `auth`, ADR 0020).

Not tenant data: an owner can have several stores, and signing in happens before any tenant is
known, so these tables live outside `public` (whose every table is tenant data under row-level
security). Secrets are never stored: sign-in links, sessions, CSRF tokens and API tokens are
kept as SHA-256 digests. The application role can read and write them; nothing here holds store
data.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        f"""
        CREATE SCHEMA auth;

        CREATE TABLE auth.owners (
            owner_id    uuid PRIMARY KEY,
            email       text NOT NULL UNIQUE CHECK (email = lower(email)),
            created_at  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE auth.memberships (
            owner_id    uuid NOT NULL REFERENCES auth.owners (owner_id) ON DELETE CASCADE,
            store_id    uuid NOT NULL REFERENCES public.stores (store_id) ON DELETE CASCADE,
            role        text NOT NULL DEFAULT 'owner' CHECK (role IN ('owner')),
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (owner_id, store_id)
        );
        CREATE INDEX memberships_store ON auth.memberships (store_id);

        CREATE TABLE auth.login_links (
            link_id     uuid PRIMARY KEY,
            owner_id    uuid NOT NULL REFERENCES auth.owners (owner_id) ON DELETE CASCADE,
            token_hash  bytea NOT NULL UNIQUE,
            expires_at  timestamptz NOT NULL,
            used_at     timestamptz,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX login_links_owner ON auth.login_links (owner_id, created_at);

        CREATE TABLE auth.sessions (
            session_id    uuid PRIMARY KEY,
            owner_id      uuid NOT NULL REFERENCES auth.owners (owner_id) ON DELETE CASCADE,
            token_hash    bytea NOT NULL UNIQUE,
            csrf_hash     bytea NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            expires_at    timestamptz NOT NULL,
            last_seen_at  timestamptz NOT NULL DEFAULT now(),
            revoked_at    timestamptz
        );

        CREATE TABLE auth.api_tokens (
            token_id      uuid PRIMARY KEY,
            store_id      uuid NOT NULL REFERENCES public.stores (store_id) ON DELETE CASCADE,
            name          text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
            prefix        text NOT NULL,
            token_hash    bytea NOT NULL UNIQUE,
            created_by    uuid REFERENCES auth.owners (owner_id) ON DELETE SET NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            last_used_at  timestamptz,
            revoked_at    timestamptz
        );
        CREATE INDEX api_tokens_store ON auth.api_tokens (store_id);

        GRANT USAGE ON SCHEMA auth TO {role};
        GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA auth TO {role};
        GRANT DELETE ON auth.memberships TO {role};
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS auth CASCADE")
