"""The "do nothing" option of a decision, with its zero fact.

Every decision compares its options with doing nothing; the comparison itself is shown as an
option with an exact fact of zero (`decision.do_nothing.net_profit`, whose parent is the twin's
do-nothing outcome), so the owner sees the baseline next to the options and can open its proof.
It is not a row of `decision_options`: it is never approved, never executed, and no channel
offers it. Decisions proposed before have none (the column stays null).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE decisions ADD COLUMN do_nothing_fact_id bigint")


def downgrade() -> None:
    op.execute("ALTER TABLE decisions DROP COLUMN do_nothing_fact_id")
