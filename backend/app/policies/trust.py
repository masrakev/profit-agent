"""Trust ledger: how well predictions held, per action type (Task 4 B2, ADR 0016).

From measured outcomes: how many, the mean absolute error between the predicted P50 and the
measured effect, the share of measured effects inside the predicted P10-P90 (the predictions that
held: confirmations), and rollbacks. A promotion to the next autonomy level is only *proposed*
(never applied) after `CONFIRMATIONS` confirmations, with at least `MIN_INSIDE` of the measured
predictions held and no rollback. The progress is written here, in words, for the owner.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.causal.verdict import Consistency, consistency
from app.policies.engine import ACTION_TYPES
from app.settings.models import ActionType, AutonomyLevel
from app.settings.repository import StoreSettingsRepository

CONFIRMATIONS = 10  # predictions that held before a promotion can be proposed
MIN_INSIDE = Decimal("0.75")
NEXT = {  # what the next level would let the agent do, in the owner's words
    AutonomyLevel.OBSERVE: "recommend this",
    AutonomyLevel.RECOMMEND: "do this alone",
    AutonomyLevel.EXECUTE_CAPPED: "manage this within its scope",
}


@dataclass(frozen=True)
class TrustEntry:
    action_type: str
    measured: int
    abstained: int
    mean_abs_error: Decimal | None
    inside_share: Decimal | None
    rollbacks: int
    level: int
    proposal: str | None  # a proposed promotion; nothing is changed
    confirmations: int = 0  # measured predictions that held
    threshold: int = CONFIRMATIONS  # confirmations needed before a promotion is proposed
    proposed_level: int | None = None  # the level a proposed promotion would set
    progress: str | None = None  # "1 of 10 confirmations before I can ask to do this alone"


def trust_ledger(conn: Connection, store_id: UUID) -> list[TrustEntry]:
    settings = StoreSettingsRepository(conn).get_or_default(store_id)
    rows = conn.execute(
        text(
            "SELECT a.kind, o.status, o.payload FROM outcomes o JOIN actions a "
            "ON a.store_id = o.store_id AND a.action_id = o.action_id WHERE o.store_id = :s"
        ),
        {"s": store_id},
    ).all()
    rollbacks: dict[str, int] = {
        str(kind): int(count)
        for kind, count in conn.execute(
            text(
                "SELECT original.kind, count(*) FROM actions r JOIN actions original "
                "ON original.store_id = r.store_id AND original.action_id = r.rollback_of "
                "WHERE r.store_id = :s GROUP BY original.kind"
            ),
            {"s": store_id},
        )
    }
    return [
        entry(
            action_type,
            settings.autonomy[action_type],
            [(r.status, r.payload) for r in rows if r.kind == kind],
            int(rollbacks.get(kind, 0)),
        )
        for kind, action_type in ACTION_TYPES.items()
    ]


def entry(
    action_type: ActionType,
    level: AutonomyLevel,
    outcomes: list[tuple[str, dict[str, Any]]],
    rollbacks: int,
) -> TrustEntry:
    """One action type's ledger, from its outcomes (status, payload) and its rollbacks."""
    measured = [payload for status, payload in outcomes if status == "measured"]
    errors: list[Decimal] = []
    inside = 0
    for p in measured:
        found = consistency(p)
        if found is None:
            continue
        errors.append(abs(Decimal(p["effect"]["p50"]) - Decimal(p["predicted"]["p50"])))
        inside += found is Consistency.INSIDE
    share = (Decimal(inside) / len(errors)).quantize(Decimal("0.0001")) if errors else None
    mae = (sum(errors, Decimal(0)) / len(errors)).quantize(Decimal("0.01")) if errors else None
    proposal, proposed_level = None, None
    if (
        inside >= CONFIRMATIONS
        and share is not None
        and share >= MIN_INSIDE
        and rollbacks == 0
        and level < AutonomyLevel.MANAGE_SCOPE
    ):
        proposed_level = int(level) + 1
        proposal = f"propose autonomy level {proposed_level} for {action_type.value}"
    return TrustEntry(
        action_type=action_type.value,
        measured=len(measured),
        abstained=sum(1 for status, _ in outcomes if status == "abstained"),
        mean_abs_error=mae,
        inside_share=share,
        rollbacks=rollbacks,
        level=int(level),
        proposal=proposal,
        confirmations=inside,
        proposed_level=proposed_level,
        progress=progress(inside, level, proposed_level),
    )


def progress(confirmations: int, level: AutonomyLevel, proposed_level: int | None) -> str | None:
    """Where the earned autonomy stands, as the owner reads it; None at the top level."""
    goal = NEXT.get(level)
    if goal is None:
        return None
    if proposed_level is not None:
        return f"My predictions held {confirmations} times: I can ask to {goal}."
    plural = "" if CONFIRMATIONS == 1 else "s"
    return f"{confirmations} of {CONFIRMATIONS} confirmation{plural} before I can ask to {goal}"
