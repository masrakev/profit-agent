"""Trust ledger: how well predictions held, per action type (Task 4 B2, ADR 0016).

From measured outcomes: how many, the mean absolute error between the predicted P50 and the
measured effect, the share of measured effects inside the predicted P10-P90, and rollbacks. A
promotion to the next autonomy level is only *proposed* (never applied) after
`MIN_OUTCOMES` measured outcomes with at least `MIN_INSIDE` of them inside the predicted range
and no rollback.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, text

from app.policies.engine import ACTION_TYPES
from app.settings.models import AutonomyLevel
from app.settings.repository import StoreSettingsRepository

MIN_OUTCOMES = 10
MIN_INSIDE = Decimal("0.75")


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
    out: list[TrustEntry] = []
    for kind, action_type in ACTION_TYPES.items():
        mine = [r for r in rows if r.kind == kind]
        measured = [r.payload for r in mine if r.status == "measured"]
        errors: list[Decimal] = []
        inside = 0
        for p in measured:
            predicted, effect = p.get("predicted"), p.get("effect")
            if not predicted or not effect:
                continue
            errors.append(abs(Decimal(effect["p50"]) - Decimal(predicted["p50"])))
            inside += (
                Decimal(predicted["p10"]) <= Decimal(effect["p50"]) <= Decimal(predicted["p90"])
            )
        level = settings.autonomy[action_type]
        share = (Decimal(inside) / len(errors)).quantize(Decimal("0.0001")) if errors else None
        mae = (sum(errors, Decimal(0)) / len(errors)).quantize(Decimal("0.01")) if errors else None
        n_rollbacks = int(rollbacks.get(kind, 0))
        proposal = None
        if (
            len(errors) >= MIN_OUTCOMES
            and share is not None
            and share >= MIN_INSIDE
            and n_rollbacks == 0
            and level < AutonomyLevel.MANAGE_SCOPE
        ):
            proposal = f"propose autonomy level {int(level) + 1} for {action_type.value}"
        out.append(
            TrustEntry(
                action_type=action_type.value,
                measured=len(measured),
                abstained=sum(1 for r in mine if r.status == "abstained"),
                mean_abs_error=mae,
                inside_share=share,
                rollbacks=n_rollbacks,
                level=int(level),
                proposal=proposal,
            )
        )
    return out
