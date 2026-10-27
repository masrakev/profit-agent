from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.money import MONEY_QUANTUM, allocate_pro_rata, round_for_display
from app.facts.arith import UndefinedValue, exact_mul, exact_sub, exact_sum, ratio

amounts = st.integers(min_value=0, max_value=10**12).map(lambda n: Decimal(n) * MONEY_QUANTUM)
weights = st.lists(
    st.integers(min_value=0, max_value=10**8).map(lambda n: Decimal(n) / 100),
    min_size=1,
    max_size=12,
)


@given(amounts, weights)
def test_allocation_sums_exactly_and_stays_on_grid(total: Decimal, ws: list[Decimal]) -> None:
    parts = allocate_pro_rata(total, ws)
    assert sum(parts, Decimal(0)) == total
    assert all(p % MONEY_QUANTUM == 0 and p >= 0 for p in parts)
    assert parts == allocate_pro_rata(total, ws)  # deterministic
    weight_sum = sum(ws, Decimal(0))
    if weight_sum:
        for part, w in zip(parts, ws, strict=True):
            assert abs(part - total * w / weight_sum) < MONEY_QUANTUM  # within one unit


def test_allocation_examples() -> None:
    assert allocate_pro_rata(Decimal("1.01"), [Decimal(30), Decimal(10)]) == [
        Decimal("0.7575"),
        Decimal("0.2525"),
    ]
    assert allocate_pro_rata(Decimal("0.01"), [Decimal(1)] * 3) == [
        Decimal("0.0034"),
        Decimal("0.0033"),
        Decimal("0.0033"),
    ]
    assert allocate_pro_rata(Decimal("1.00"), [Decimal(0), Decimal(0)]) == [
        Decimal("0.5000"),
        Decimal("0.5000"),
    ]
    assert allocate_pro_rata(Decimal("-0.03"), [Decimal(1), Decimal(2)]) == [
        Decimal("-0.0100"),
        Decimal("-0.0200"),
    ]
    assert allocate_pro_rata(Decimal(0), []) == []
    with pytest.raises(ValueError, match="no weights"):
        allocate_pro_rata(Decimal(1), [])
    with pytest.raises(ValueError, match="non-negative"):
        allocate_pro_rata(Decimal(1), [Decimal(-1)])
    with pytest.raises(ValueError, match="multiple"):
        allocate_pro_rata(Decimal("0.00001"), [Decimal(1)])


def test_presentation_rounding_is_half_even() -> None:
    assert round_for_display(Decimal("0.125")) == Decimal("0.12")
    assert round_for_display(Decimal("0.135")) == Decimal("0.14")
    assert round_for_display(Decimal("2.5"), 0) == Decimal("2")


def test_exact_arithmetic_refuses_to_round() -> None:
    assert exact_sum(Decimal("0.1"), Decimal("0.2")) == Decimal("0.3")
    assert exact_sub(Decimal("1"), Decimal("0.3"), Decimal("0.2")) == Decimal("0.5")
    assert exact_mul(Decimal("1.5"), Decimal("4")) == Decimal("6.0")
    with pytest.raises(ArithmeticError):
        exact_sum(Decimal("1E+60"), Decimal("1E-10"))
    assert ratio(Decimal(1), Decimal(3), denominator_name="d") == Decimal(
        "0.3333333333333333333333333333"
    )
    with pytest.raises(UndefinedValue, match="d is zero"):
        ratio(Decimal(1), Decimal(0), denominator_name="d")
