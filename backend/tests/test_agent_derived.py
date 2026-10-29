"""Derived facts: compute rules (units, currencies, periods, undefined) and series helpers."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.agent.tools.derived import ComputeError, change_point, compute, difference, mean, slope
from app.facts.model import Fact, FactKind, FactStatus, Period, Scope, Unit

STORE = UUID(int=1)
P = Scope.product(UUID(int=2))
JAN = Period.days(date(2026, 1, 1), date(2026, 2, 1))
FEB = Period.days(date(2026, 2, 1), date(2026, 3, 1))
D = Decimal


def fact(
    fid: int,
    value: str | None,
    unit: Unit = Unit.MONEY,
    *,
    period: Period = JAN,
    scope: Scope = P,
    kind: FactKind = FactKind.EXACT,
    currency: str | None = "USD",
) -> Fact:
    defined = value is not None
    return Fact(
        id=fid,
        store_id=STORE,
        formula_id="m",
        formula_version=1,
        kind=kind,
        scope=scope,
        period=period,
        status=FactStatus.DEFINED if defined else FactStatus.UNDEFINED,
        value=D(value) if defined else None,
        unit=unit,
        currency=currency if unit is Unit.MONEY else None,
        undefined_reason=None if defined else "no data",
        p10=D(value) if kind is FactKind.ESTIMATE and defined else None,
        p50=D(value) if kind is FactKind.ESTIMATE and defined else None,
        p90=D(value) if kind is FactKind.ESTIMATE and defined else None,
        method="x" if kind is FactKind.ESTIMATE else None,
        inputs_hash="0" * 64,
    )


REV, COST, UNITS = fact(1, "300.00"), fact(2, "120.00"), fact(3, "30", Unit.COUNT)
RATE, DAYS = fact(4, "0.25", Unit.RATIO), fact(5, "7", Unit.DAYS)


def ops(*facts: Fact) -> dict[int, Fact]:
    return {f.id: f for f in facts if f.id is not None}


@pytest.mark.parametrize(
    ("expression", "operands", "value", "unit"),
    [
        ("F1 - F2", ops(REV, COST), "180.00", Unit.MONEY),
        ("-(F1 - F2)", ops(REV, COST), "-180.00", Unit.MONEY),
        ("(F1 - F2) / F1", ops(REV, COST), "0.6", Unit.RATIO),
        ("F1 * F4", ops(REV, RATE), "75.0000", Unit.MONEY),
        ("F4 * F1", ops(REV, RATE), "75.0000", Unit.MONEY),
        ("F1 / F4", ops(REV, RATE), "1200", Unit.MONEY),
        ("F1 / F3", ops(REV, UNITS), "10", Unit.MONEY),
        ("F1 / F5", ops(REV, DAYS), "42.85714285714285714285714286", Unit.MONEY),
        ("F3 / F3", ops(UNITS), "1", Unit.RATIO),
        ("F4 + F4", ops(RATE), "0.50", Unit.RATIO),
    ],
)
def test_compute_rules(expression: str, operands: dict[int, Fact], value: str, unit: Unit) -> None:
    out = compute(expression, operands)
    assert (out.value, out.unit, out.kind) == (D(value), unit, FactKind.EXACT)
    assert out.currency == ("USD" if unit is Unit.MONEY else None)
    assert out.formula_id == "derived.compute"


@pytest.mark.parametrize(
    ("expression", "operands", "message"),
    [
        ("F1 + F3", ops(REV, UNITS), "add or subtract money USD and count"),
        ("F1 * F2", ops(REV, COST), "one factor must be a ratio"),
        ("F3 / F1", ops(REV, UNITS), "cannot divide count by money"),
        ("F1 % F2", ops(REV, COST), "only"),
        ("F1 + 100", ops(REV), "literal numbers"),
        ("abs(F1)", ops(REV), "unsupported syntax"),
        ("revenue + F1", ops(REV), "unknown name"),
        ("F1 + F9", ops(REV), "F9 is not in fact_ids"),
        ("F1 +", ops(REV), "invalid expression"),
        ("F1 + " * 80 + "F1", ops(REV), "too long"),
        ("F1", {}, "at least one"),
        ("F6", ops(fact(6, "1", kind=FactKind.ESTIMATE)), "exact facts only"),
    ],
)
def test_compute_refusals(expression: str, operands: dict[int, Fact], message: str) -> None:
    with pytest.raises(ComputeError, match=message):
        compute(expression, operands)


def test_currencies_must_match() -> None:
    eur = fact(7, "10.00", currency="EUR")
    with pytest.raises(ComputeError, match="USD and money EUR"):
        compute("F1 + F7", ops(REV, eur))


def test_undefined_results() -> None:
    zero = fact(8, "0", Unit.COUNT)
    out = compute("F1 / F8", ops(REV, zero))
    assert (out.status, out.value, out.undefined_reason) == (
        FactStatus.UNDEFINED,
        None,
        "the divisor is zero",
    )
    missing = fact(9, None)
    out = compute("F1 - F9", ops(REV, missing))
    assert out.undefined_reason == "F9 is undefined (no data)"
    assert out.unit is Unit.MONEY


def test_periods_and_scopes_of_derived_facts() -> None:
    feb_rev = fact(10, "330.00", period=FEB)
    growth = compute("F10 - F1", ops(REV, feb_rev))
    assert (growth.period, growth.baseline) == (FEB, JAN)  # a comparison
    overlapping = fact(11, "5.00", period=Period.days(date(2026, 1, 15), date(2026, 2, 15)))
    span = compute("F1 + F11", ops(REV, overlapping))
    assert span.period == Period.days(date(2026, 1, 1), date(2026, 2, 15))
    assert span.baseline is None
    other = fact(12, "1.00", scope=Scope.store())
    assert compute("F1 + F12", ops(REV, other)).scope == Scope.store()
    assert compute("F1 - F2", ops(REV, COST)).scope == P
    a, b = compute("F1 - F2", ops(REV, COST)), compute("F1 - F2", ops(REV, COST))
    assert a.fact_hash == b.fact_hash  # deterministic


def daily(values: list[str | None]) -> list[Fact]:
    return [
        fact(
            100 + i,
            v,
            Unit.COUNT,
            period=Period.days(
                date(2026, 1, 1) + timedelta(days=i), date(2026, 1, 2) + timedelta(days=i)
            ),
        )
        for i, v in enumerate(values)
    ]


def test_series_helpers() -> None:
    days = daily(["10", "11", "9", "10", "10", "11", "2", "3", "2", "1", "2", "3"])
    window = Period.days(date(2026, 1, 1), date(2026, 1, 13))
    diff = difference(days[0], days[-1], window)
    assert diff.value == D(-7)
    assert [p.role for p in diff.lineage.parents] == ["start", "end"]
    assert change_point(days) == 6
    before, after = mean(days[:6], window, days[0]), mean(days[6:], window, days[0])
    assert before.value == D("10.16666666666666666666666667")
    assert after.value == D("2.166666666666666666666666667")
    s = slope(days, window, days[0])
    assert s.kind is FactKind.ESTIMATE
    assert None not in (s.p10, s.p50, s.p90)
    assert s.p10 < s.p50 < s.p90 < 0  # type: ignore[operator]
    flat = daily(["5"] * 12)
    assert change_point(flat) is None  # no variance anywhere
    assert slope(flat, window, flat[0]).value == D(0)


def test_series_helpers_with_undefined_days() -> None:
    window = Period.days(date(2026, 1, 1), date(2026, 1, 13))
    sparse = daily([None, "1", None] + [None] * 9)
    assert slope(sparse, window, sparse[1]).undefined_reason == "fewer than three defined days"
    assert mean(daily([None, None]), window, sparse[1]).undefined_reason == "no defined day"
    assert difference(sparse[0], sparse[1], window).undefined_reason == (
        "the first or last day is undefined"
    )
    gappy = daily(["1", None, "1", None, "1", None, "9", None, "9", None, "9", None])
    assert change_point(gappy) is None  # fewer than five defined days on a side
