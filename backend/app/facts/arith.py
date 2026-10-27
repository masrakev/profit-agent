"""Decimal arithmetic for facts derived from other facts.

- `exact_*`: sums and differences under a context that traps any rounding, so a derived exact
  fact is provably equal to the arithmetic on its parents.
- `ratio`: one division, rounded HALF_EVEN to 28 significant digits. A zero denominator raises
  `UndefinedValue`, which the engine turns into an `undefined` fact.
"""

from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
)

EXACT_CONTEXT = Context(
    prec=60,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow, Inexact, Rounded],
)
RATIO_CONTEXT = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)


class UndefinedValue(Exception):  # noqa: N818 - a domain outcome, not an error condition
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def exact_sum(*terms: Decimal) -> Decimal:
    total = Decimal(0)
    for term in terms:
        total = EXACT_CONTEXT.add(total, term)
    return total


def exact_sub(minuend: Decimal, *subtrahends: Decimal) -> Decimal:
    result = minuend
    for term in subtrahends:
        result = EXACT_CONTEXT.subtract(result, term)
    return result


def exact_mul(a: Decimal, b: Decimal) -> Decimal:
    return EXACT_CONTEXT.multiply(a, b)


def ratio(numerator: Decimal, denominator: Decimal, *, denominator_name: str) -> Decimal:
    if denominator == 0:
        raise UndefinedValue(f"{denominator_name} is zero")
    return RATIO_CONTEXT.divide(numerator, denominator)
