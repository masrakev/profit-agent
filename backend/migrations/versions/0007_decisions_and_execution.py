"""Decisions, approvals, actions, outbox, controls, outcomes and the simulator's state.

The decision state machine is enforced by the database: an insert starts at `proposed`, and an
update must be one of the allowed transitions (proposed -> approved | rejected | expired,
approved -> executing, executing -> executed | failed, executed -> measured); anything else
raises. One approval per decision (unique), so a decision is decided once whatever the channel.
Action idempotency keys are unique per store. The global kill switch lives in the `control`
schema (not tenant data: the application role can only read it).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"
TABLES = (
    "decisions",
    "decision_options",
    "approvals",
    "approval_links",
    "actions",
    "outbox",
    "store_controls",
    "outcomes",
    "simulator_stores",
)
GRANTS = {
    "decisions": "SELECT, INSERT, UPDATE",
    "decision_options": "SELECT, INSERT",
    "approvals": "SELECT, INSERT",
    "approval_links": "SELECT, INSERT, UPDATE",
    "actions": "SELECT, INSERT, UPDATE",
    "outbox": "SELECT, INSERT, UPDATE",
    "store_controls": "SELECT, INSERT, UPDATE",
    "outcomes": "SELECT, INSERT",
    "simulator_stores": "SELECT, INSERT, UPDATE",
}
TRANSITIONS = (
    ("proposed", "approved"),
    ("proposed", "rejected"),
    ("proposed", "expired"),
    ("approved", "executing"),
    ("executing", "executed"),
    ("executing", "failed"),
    ("executed", "measured"),
)


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    allowed = ", ".join(f"('{a}', '{b}')" for a, b in TRANSITIONS)
    op.execute(
        f"""
        CREATE TABLE decisions (
            decision_id          uuid PRIMARY KEY,
            store_id             uuid NOT NULL REFERENCES stores (store_id),
            source               text NOT NULL CHECK (source IN ('incident', 'question', 'owner')),
            incident_id          text,
            cause                text NOT NULL,
            entity               text NOT NULL,
            status               text NOT NULL CHECK (status IN ('proposed', 'approved',
                                 'rejected', 'expired', 'executing', 'executed', 'failed',
                                 'measured')),
            recommended_option_id text NOT NULL,
            approved_option_id   text,
            horizon_days         integer NOT NULL CHECK (horizon_days > 0),
            floor                numeric(18, 4) NOT NULL,
            currency             char(3) NOT NULL,
            as_of                date NOT NULL,
            expires_at           timestamptz NOT NULL,
            payload              jsonb NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            updated_at           timestamptz NOT NULL DEFAULT now(),
            UNIQUE (store_id, decision_id)
        );
        CREATE INDEX decisions_store_status ON decisions (store_id, status);

        CREATE FUNCTION decisions_state_machine() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'proposed' THEN
                    RAISE EXCEPTION 'a decision starts as proposed, not %', NEW.status
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF (OLD.status, NEW.status) NOT IN ({allowed}) THEN
                RAISE EXCEPTION 'illegal decision transition % -> %', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.decision_id <> OLD.decision_id OR NEW.store_id <> OLD.store_id
               OR NEW.payload <> OLD.payload OR NEW.recommended_option_id <>
               OLD.recommended_option_id OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'a decision''s content is immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.approved_option_id IS NOT NULL
               AND NEW.approved_option_id IS DISTINCT FROM OLD.approved_option_id THEN
                RAISE EXCEPTION 'the approved option cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END
        $$;
        CREATE TRIGGER decisions_state_machine BEFORE INSERT OR UPDATE ON decisions
            FOR EACH ROW EXECUTE FUNCTION decisions_state_machine();

        CREATE TABLE decision_options (
            store_id        uuid NOT NULL REFERENCES stores (store_id),
            decision_id     uuid NOT NULL,
            option_id       text NOT NULL,
            rank            smallint NOT NULL,
            kind            text NOT NULL,
            action_family   text NOT NULL,
            entity          text NOT NULL,
            actions         jsonb NOT NULL,
            executable      boolean NOT NULL,
            reversibility   text NOT NULL,
            impact_fact_id  bigint,
            p10             numeric(18, 4),
            p50             numeric(18, 4),
            p90             numeric(18, 4),
            risks           jsonb NOT NULL,
            invalidated_if  jsonb NOT NULL,
            flags           jsonb NOT NULL,
            PRIMARY KEY (store_id, decision_id, option_id),
            FOREIGN KEY (store_id, decision_id) REFERENCES decisions (store_id, decision_id)
        );

        CREATE TABLE approvals (
            approval_id  uuid PRIMARY KEY,
            store_id     uuid NOT NULL REFERENCES stores (store_id),
            decision_id  uuid NOT NULL UNIQUE,
            option_id    text,
            verdict      text NOT NULL CHECK (verdict IN ('approved', 'rejected')),
            channel      text NOT NULL CHECK (channel IN ('api', 'email')),
            actor        text NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (store_id, decision_id) REFERENCES decisions (store_id, decision_id)
        );
        CREATE INDEX approvals_store ON approvals (store_id, decision_id);

        CREATE TABLE approval_links (
            link_id      uuid PRIMARY KEY,
            store_id     uuid NOT NULL REFERENCES stores (store_id),
            decision_id  uuid NOT NULL,
            option_id    text NOT NULL,
            verdict      text NOT NULL CHECK (verdict IN ('approved', 'rejected')),
            expires_at   timestamptz NOT NULL,
            used_at      timestamptz,
            created_at   timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (store_id, decision_id) REFERENCES decisions (store_id, decision_id)
        );
        CREATE INDEX approval_links_store ON approval_links (store_id, decision_id);

        CREATE TABLE actions (
            action_id        uuid PRIMARY KEY,
            store_id         uuid NOT NULL REFERENCES stores (store_id),
            decision_id      uuid NOT NULL,
            option_id        text NOT NULL,
            seq              smallint NOT NULL,
            kind             text NOT NULL CHECK (kind IN ('pause_campaign', 'resume_campaign',
                             'change_budget')),
            campaign_id      uuid NOT NULL,
            provider         text NOT NULL CHECK (provider IN ('meta', 'simulator')),
            params           jsonb NOT NULL,
            idempotency_key  text NOT NULL,
            status           text NOT NULL CHECK (status IN ('pending', 'executing', 'executed',
                             'blocked', 'failed')),
            rollback_of      uuid,
            attempts         integer NOT NULL DEFAULT 0,
            last_error       text,
            before_state     jsonb,
            after_state      jsonb,
            created_at       timestamptz NOT NULL DEFAULT now(),
            executed_at      timestamptz,
            UNIQUE (store_id, idempotency_key),
            UNIQUE (store_id, action_id),
            FOREIGN KEY (store_id, decision_id) REFERENCES decisions (store_id, decision_id),
            FOREIGN KEY (store_id, campaign_id) REFERENCES ad_campaigns (store_id, id)
        );
        CREATE INDEX actions_store_campaign ON actions (store_id, campaign_id, executed_at);

        CREATE TABLE outbox (
            outbox_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            store_id      uuid NOT NULL REFERENCES stores (store_id),
            action_id     uuid NOT NULL,
            status        text NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
            attempts      integer NOT NULL DEFAULT 0,
            available_at  timestamptz NOT NULL DEFAULT now(),
            last_error    text,
            created_at    timestamptz NOT NULL DEFAULT now(),
            processed_at  timestamptz,
            UNIQUE (store_id, action_id),
            FOREIGN KEY (store_id, action_id) REFERENCES actions (store_id, action_id)
        );
        CREATE INDEX outbox_store_ready ON outbox (store_id, status, available_at);

        CREATE TABLE store_controls (
            store_id     uuid PRIMARY KEY REFERENCES stores (store_id),
            kill_switch  boolean NOT NULL,
            reason       text,
            updated_by   text NOT NULL,
            updated_at   timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE outcomes (
            outcome_id     uuid PRIMARY KEY,
            store_id       uuid NOT NULL REFERENCES stores (store_id),
            decision_id    uuid NOT NULL,
            action_id      uuid NOT NULL,
            status         text NOT NULL CHECK (status IN ('measured', 'abstained')),
            method         text NOT NULL,
            window_start   date NOT NULL,
            window_end     date NOT NULL,
            effect_fact_id bigint,
            payload        jsonb NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (store_id, decision_id) REFERENCES decisions (store_id, decision_id),
            FOREIGN KEY (store_id, action_id) REFERENCES actions (store_id, action_id)
        );
        -- An abstention (too little history yet) can be followed by a measurement later.
        CREATE INDEX outcomes_store_action ON outcomes (store_id, action_id, created_at);

        CREATE TABLE simulator_stores (
            store_id       uuid PRIMARY KEY REFERENCES stores (store_id),
            suite          text NOT NULL,
            scenario_id    text NOT NULL,
            current_day    integer NOT NULL,
            events         jsonb NOT NULL,
            updated_at     timestamptz NOT NULL DEFAULT now()
        );

        CREATE SCHEMA control;
        CREATE TABLE control.global_switches (
            name        text PRIMARY KEY,
            enabled     boolean NOT NULL,
            reason      text,
            updated_by  text NOT NULL,
            updated_at  timestamptz NOT NULL DEFAULT now()
        );
        GRANT USAGE ON SCHEMA control TO {role};
        GRANT SELECT ON control.global_switches TO {role};

        -- Stores with outbox rows ready now: the only cross-tenant read, ids only, so the worker
        -- can then claim rows inside each store's own tenant transaction.
        CREATE FUNCTION public.outbox_ready_stores(ready_at timestamptz) RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
            SELECT DISTINCT store_id FROM public.outbox
            WHERE status = 'pending' AND available_at <= ready_at
        $$;
        REVOKE ALL ON FUNCTION public.outbox_ready_stores(timestamptz) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.outbox_ready_stores(timestamptz) TO {role};

        -- The simulator executes actions on a synthetic store's own campaigns.
        GRANT UPDATE (status, daily_budget) ON ad_campaigns TO {role};
        """
    )
    for table in TABLES:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table}
                USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
            GRANT {GRANTS[table]} ON {table} TO {role};
            """
        )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.outbox_ready_stores(timestamptz);
        DROP TABLE IF EXISTS control.global_switches;
        DROP SCHEMA IF EXISTS control;
        DROP TABLE IF EXISTS simulator_stores, outcomes, store_controls, outbox, actions,
            approval_links, approvals, decision_options, decisions;
        DROP FUNCTION IF EXISTS decisions_state_machine();
        """
    )
