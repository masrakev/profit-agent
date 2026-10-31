"""Goals, their plans, plan steps and weekly progress (Task 6 B4, ADR 0024).

- `goals`: the owner's goal (metric, target, deadline), from the day of data it counts from;
  `draft` until the owner confirms the restated goal.
- `goal_plans`: a plan built for a goal (its milestones, probabilities and alternatives as
  fact ids in `payload`); `proposed`, then `accepted` by the owner, `superseded` by a revision.
- `goal_steps`: the plan's dated steps; a decision step links the decision proposed for it
  when its day comes (plans never execute anything themselves).
- `goal_progress`: weekly tracking (actual against the milestone, step adherence, updated
  probability) and the monthly re-forecast; one row per goal, kind and day.

Decisions gain the source `goal`.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

from app.config import get_settings

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"
TABLES = ("goals", "goal_plans", "goal_steps", "goal_progress")


def upgrade() -> None:
    role = get_settings().app_db_role
    if not role.isidentifier():
        raise ValueError(f"invalid role name {role!r}")
    op.execute(
        """
        CREATE TABLE goals (
            goal_id        uuid PRIMARY KEY,
            store_id       uuid NOT NULL REFERENCES stores (store_id),
            metric         text NOT NULL
                           CHECK (metric IN ('net_profit', 'contribution_margin', 'revenue')),
            target         numeric(18, 4) NOT NULL,
            currency       char(3) NOT NULL,
            as_of          date NOT NULL,
            deadline       date NOT NULL CHECK (deadline > as_of),
            status         text NOT NULL CHECK (status IN
                           ('draft', 'confirmed', 'planned', 'achieved', 'missed', 'cancelled')),
            question       text,
            target_fact_id bigint REFERENCES facts (id),
            created_at     timestamptz NOT NULL DEFAULT now(),
            confirmed_at   timestamptz,
            updated_at     timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX goals_store ON goals (store_id, status);

        CREATE TABLE goal_plans (
            plan_id     uuid PRIMARY KEY,
            store_id    uuid NOT NULL REFERENCES stores (store_id),
            goal_id     uuid NOT NULL REFERENCES goals (goal_id),
            status      text NOT NULL CHECK (status IN ('proposed', 'accepted', 'superseded')),
            as_of       date NOT NULL,
            days        integer NOT NULL CHECK (days BETWEEN 1 AND 90),
            payload     jsonb NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            accepted_at timestamptz
        );
        CREATE INDEX goal_plans_goal ON goal_plans (store_id, goal_id, created_at);

        CREATE TABLE goal_steps (
            step_id        uuid PRIMARY KEY,
            store_id       uuid NOT NULL REFERENCES stores (store_id),
            plan_id        uuid NOT NULL REFERENCES goal_plans (plan_id),
            position       integer NOT NULL CHECK (position >= 1),
            lever          text NOT NULL,
            kind           text NOT NULL CHECK (kind IN ('decision', 'manual', 'experiment')),
            due_date       date NOT NULL,
            actions        jsonb NOT NULL,
            summary        text NOT NULL,
            evidence       jsonb NOT NULL,
            effect_fact_id bigint REFERENCES facts (id),
            experiment     jsonb,
            status         text NOT NULL
                CHECK (status IN ('planned', 'proposed', 'done', 'skipped')),
            decision_id    uuid REFERENCES decisions (decision_id),
            created_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (plan_id, position)
        );
        CREATE INDEX goal_steps_plan ON goal_steps (store_id, plan_id);

        CREATE TABLE goal_progress (
            progress_id         uuid PRIMARY KEY,
            store_id            uuid NOT NULL REFERENCES stores (store_id),
            goal_id             uuid NOT NULL REFERENCES goals (goal_id),
            plan_id             uuid REFERENCES goal_plans (plan_id),
            kind                text NOT NULL CHECK (kind IN ('weekly', 'reforecast')),
            as_of               date NOT NULL,
            day                 integer NOT NULL CHECK (day >= 0),
            actual_fact_id      bigint REFERENCES facts (id),
            milestone_fact_id   bigint REFERENCES facts (id),
            probability_fact_id bigint REFERENCES facts (id),
            status              text CHECK (status IN ('ahead', 'on_track', 'behind')),
            verdict             text,
            adherence           jsonb NOT NULL DEFAULT '{}'::jsonb,
            revision_proposed   boolean NOT NULL DEFAULT false,
            reason              text,
            created_at          timestamptz NOT NULL DEFAULT now(),
            UNIQUE (store_id, goal_id, kind, as_of)
        );
        CREATE INDEX goal_progress_goal ON goal_progress (store_id, goal_id, as_of);

        ALTER TABLE decisions DROP CONSTRAINT decisions_source_check;
        ALTER TABLE decisions ADD CONSTRAINT decisions_source_check
            CHECK (source IN ('incident', 'question', 'owner', 'goal'));
        """
    )
    for table in TABLES:
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
        DROP TABLE IF EXISTS goal_progress;
        DROP TABLE IF EXISTS goal_steps;
        DROP TABLE IF EXISTS goal_plans;
        DROP TABLE IF EXISTS goals;
        ALTER TABLE decisions DROP CONSTRAINT decisions_source_check;
        ALTER TABLE decisions ADD CONSTRAINT decisions_source_check
            CHECK (source IN ('incident', 'question', 'owner'));
        """
    )
