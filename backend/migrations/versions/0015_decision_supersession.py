"""A pending decision superseded by another acting on the same campaign or product.

When two pending decisions act on the same entity, the one resting on the most recent evidence
stands; the other becomes `superseded`, a terminal state reached from `proposed` only, linked to
the decision that took precedence (`superseded_by`) with the reason. The state machine of
migration 0007 gains that transition; a superseded decision always has both, any other none.

A goal step whose decision is superseded becomes `superseded` too, and its plan proposes a
revision: a `revision` progress row.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSITIONS = (
    ("proposed", "approved"),
    ("proposed", "rejected"),
    ("proposed", "expired"),
    ("approved", "executing"),
    ("executing", "executed"),
    ("executing", "failed"),
    ("executed", "measured"),
)
SUPERSEDED = ("proposed", "superseded")
STATUSES = (
    "'proposed', 'approved', 'rejected', 'expired', 'executing', 'executed', 'failed', 'measured'"
)


def _state_machine(transitions: Sequence[tuple[str, str]]) -> str:
    allowed = ", ".join(f"('{a}', '{b}')" for a, b in transitions)
    return f"""
        CREATE OR REPLACE FUNCTION decisions_state_machine() RETURNS trigger
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
    """


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE decisions
            ADD COLUMN superseded_by uuid REFERENCES decisions (decision_id),
            ADD COLUMN superseded_reason text;
        ALTER TABLE decisions DROP CONSTRAINT decisions_status_check;
        ALTER TABLE decisions ADD CONSTRAINT decisions_status_check
            CHECK (status IN ({STATUSES}, 'superseded'));
        ALTER TABLE decisions ADD CONSTRAINT decisions_superseded_check
            CHECK ((status = 'superseded') = (superseded_by IS NOT NULL
                   AND superseded_reason IS NOT NULL));
        {_state_machine((*TRANSITIONS, SUPERSEDED))}
        ALTER TABLE goal_steps DROP CONSTRAINT goal_steps_status_check;
        ALTER TABLE goal_steps ADD CONSTRAINT goal_steps_status_check
            CHECK (status IN ('planned', 'proposed', 'done', 'skipped', 'superseded'));
        ALTER TABLE goal_progress DROP CONSTRAINT goal_progress_kind_check;
        ALTER TABLE goal_progress ADD CONSTRAINT goal_progress_kind_check
            CHECK (kind IN ('weekly', 'reforecast', 'revision'));
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM goal_progress WHERE kind = 'revision';
        ALTER TABLE goal_progress DROP CONSTRAINT goal_progress_kind_check;
        ALTER TABLE goal_progress ADD CONSTRAINT goal_progress_kind_check
            CHECK (kind IN ('weekly', 'reforecast'));
        UPDATE goal_steps SET status = 'skipped' WHERE status = 'superseded';
        ALTER TABLE goal_steps DROP CONSTRAINT goal_steps_status_check;
        ALTER TABLE goal_steps ADD CONSTRAINT goal_steps_status_check
            CHECK (status IN ('planned', 'proposed', 'done', 'skipped'));
        ALTER TABLE decisions DROP CONSTRAINT decisions_superseded_check;
        ALTER TABLE decisions DISABLE TRIGGER decisions_state_machine;
        UPDATE decisions SET status = 'expired' WHERE status = 'superseded';
        ALTER TABLE decisions ENABLE TRIGGER decisions_state_machine;
        {_state_machine(TRANSITIONS)}
        ALTER TABLE decisions DROP CONSTRAINT decisions_status_check;
        ALTER TABLE decisions ADD CONSTRAINT decisions_status_check
            CHECK (status IN ({STATUSES}));
        ALTER TABLE decisions DROP COLUMN superseded_reason, DROP COLUMN superseded_by;
        """
    )
