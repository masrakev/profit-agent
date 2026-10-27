"""Money primitives. Amounts are `Decimal` with at most 4 decimal places (NUMERIC(18,4))."""

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Annotated

from pydantic import Field, StringConstraints

MONEY_QUANTUM = Decimal("0.0001")

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Money = Annotated[Decimal, Field(max_digits=18, decimal_places=4)]
NonNegativeMoney = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]


def round_for_display(amount: Decimal, places: int = 2) -> Decimal:
    """Presentation rounding only. Never store the result."""
    return amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)


def allocate_pro_rata(
    total: Decimal, weights: Sequence[Decimal], quantum: Decimal = MONEY_QUANTUM
) -> list[Decimal]:
    """Split `total` across `weights` in multiples of `quantum`; the parts sum exactly to `total`.

    Largest-remainder method on exact rationals. Ties go to the earliest index, so the result is
    deterministic. Zero total weight splits evenly.
    """
    if not weights:
        if total != 0:
            raise ValueError("cannot allocate a non-zero total across no weights")
        return []
    if any(w < 0 for w in weights):
        raise ValueError("weights must be non-negative")
    units = Fraction(total) / Fraction(quantum)
    if units.denominator != 1:
        raise ValueError(f"total {total} is not a multiple of {quantum}")
    total_units = int(units)
    sign = -1 if total_units < 0 else 1
    total_units = abs(total_units)
    fractions_ = [Fraction(w) for w in weights]
    weight_sum = sum(fractions_, Fraction(0))
    if weight_sum == 0:
        fractions_ = [Fraction(1)] * len(weights)
        weight_sum = Fraction(len(weights))
    raw = [total_units * w / weight_sum for w in fractions_]
    floors = [int(r) for r in raw]
    remaining = total_units - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:remaining]:
        floors[i] += 1
    return [sign * f * quantum for f in floors]
