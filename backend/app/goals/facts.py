"""Facts of goals: every number a goal shows is one (ADR 0023, ADR 0024).

- `goal.target.<metric>` (exact): the owner's target, over the goal's days, so an answer cites
  it instead of writing it;
- estimates (`goal.forecast`, `goal.probability`, `goal.gap`, `goal.milestone`,
  `goal.plan.probability`, `goal.step.<lever>`, `goal.alternative.*`, `goal.plan.profit_change`),
  each with its method, its inputs hash and its parents.
"""

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from app.domain.hashing import canonical_json, sha256_hex
from app.facts.engine import FactEngine
from app.facts.model import Fact, FactKind, FactStatus, Lineage, ParentRef, Period, Scope, Unit

FORMULA_VERSION = 1
CENT = Decimal("0.01")
BASIS_POINT = Decimal("0.0001")
TENTH = Decimal("0.1")
TARGET_METHOD = "goal_parameter_v1"


def money(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(CENT, rounding=ROUND_HALF_EVEN)


def ratio(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(BASIS_POINT, rounding=ROUND_HALF_EVEN)


def days_value(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(TENTH, rounding=ROUND_HALF_EVEN)


def _quantize(x: float, unit: Unit) -> Decimal:
    return ratio(x) if unit is Unit.RATIO else days_value(x) if unit is Unit.DAYS else money(x)


def estimate(
    engine: FactEngine,
    store_id: UUID,
    *,
    formula: str,
    period: tuple[date, date],
    unit: Unit,
    quantiles: tuple[float, float, float],
    method: str,
    key: object,
    parents: tuple[tuple[str, Fact], ...],
    currency: str,
) -> Fact:
    """An estimate fact (value: its P50), persisted with its parents."""
    q10, q50, q90 = (_quantize(q, unit) for q in quantiles)
    for _, parent in parents:
        engine.adopt(parent)
    fact = Fact(
        store_id=store_id,
        formula_id=formula,
        formula_version=FORMULA_VERSION,
        kind=FactKind.ESTIMATE,
        scope=Scope.store(),
        period=Period.days(*period),
        status=FactStatus.DEFINED,
        value=q50,
        p10=min(q10, q50),
        p50=q50,
        p90=max(q90, q50),
        method=method,
        unit=unit,
        currency=currency if unit is Unit.MONEY else None,
        inputs_hash=sha256_hex(
            canonical_json(
                {
                    "formula": formula,
                    "method": method,
                    "key": str(key),
                    "parents": [f.fact_hash for _, f in parents],
                }
            )
        ),
        lineage=Lineage(
            parents=tuple(ParentRef(role=r, fact_hash=f.fact_hash) for r, f in parents)
        ),
    )
    return engine.persist(engine.adopt(fact))


def target(
    engine: FactEngine,
    store_id: UUID,
    metric: str,
    value: Decimal,
    period: tuple[date, date],
    *,
    goal_id: UUID,
    currency: str,
) -> Fact:
    """The owner's target as an exact parameter fact."""
    fact = Fact(
        store_id=store_id,
        formula_id=f"goal.target.{metric}",
        formula_version=FORMULA_VERSION,
        kind=FactKind.EXACT,
        scope=Scope.store(),
        period=Period.days(*period),
        status=FactStatus.DEFINED,
        value=value.quantize(CENT, rounding=ROUND_HALF_EVEN),
        method=TARGET_METHOD,
        unit=Unit.MONEY,
        currency=currency,
        inputs_hash=sha256_hex(canonical_json({"goal": str(goal_id), "target": str(value)})),
        lineage=Lineage(parents=()),
    )
    return engine.persist(engine.adopt(fact))
