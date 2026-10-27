"""Shapley properties (efficiency, symmetry, null player) and sum-preserving rounding."""

from decimal import Decimal
from fractions import Fraction
from itertools import combinations
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.causes.drivers import (
    LEVEL1_DRIVERS,
    PRODUCT_GAME_DRIVERS,
    Driver,
    PeriodFigures,
    ProductFigures,
    _Factors,
    _factors,
    decompose,
)
from app.causes.shapley import round_to_grid, shapley

fractions = st.fractions(min_value=-1000, max_value=1000, max_denominator=50)


@st.composite
def games(
    draw: st.DrawFn, max_players: int = 6
) -> tuple[list[int], dict[frozenset[int], Fraction]]:
    n = draw(st.integers(min_value=1, max_value=max_players))
    players = list(range(n))
    table = {frozenset(c): draw(fractions) for k in range(n + 1) for c in combinations(players, k)}
    return players, table


@given(games())
def test_efficiency(game: tuple[list[int], dict[frozenset[int], Fraction]]) -> None:
    players, table = game
    phi = shapley(players, table.__getitem__)
    assert sum(phi.values(), Fraction(0)) == table[frozenset(players)] - table[frozenset()]


@given(games(max_players=5), st.data())
def test_null_player_gets_exactly_zero(
    game: tuple[list[int], dict[frozenset[int], Fraction]], data: st.DataObject
) -> None:
    players, table = game
    null = len(players)  # an extra player that never changes the value

    def value(coalition: frozenset[int]) -> Fraction:
        return table[coalition - {null}]

    phi = shapley([*players, null], value)
    assert phi[null] == 0


@given(games(max_players=4), fractions, fractions)
def test_symmetry(
    game: tuple[list[int], dict[frozenset[int], Fraction]], a: Fraction, b: Fraction
) -> None:
    players, table = game
    i, j = len(players), len(players) + 1  # interchangeable: each adds the same amount

    def value(coalition: frozenset[int]) -> Fraction:
        bonus = (a if i in coalition else 0) + (a if j in coalition else 0)
        both = b if {i, j} <= coalition else 0
        return table[coalition - {i, j}] + bonus + both

    phi = shapley([*players, i, j], value)
    assert phi[i] == phi[j]


def test_shapley_validates_players() -> None:
    with pytest.raises(ValueError, match="distinct"):
        shapley([1, 1], lambda s: Fraction(0))
    with pytest.raises(ValueError, match="limited"):
        shapley(list(range(13)), lambda s: Fraction(0))


@given(st.lists(fractions, min_size=1, max_size=10), st.integers(min_value=-3, max_value=3))
def test_rounding_preserves_sum_and_zeros(values: list[Fraction], offset: int) -> None:
    quantum = Decimal("0.01")
    exact = sum(values, Fraction(0))
    target = Decimal(round(exact * 100)) / 100 + offset * quantum if any(values) else Decimal(0)
    parts = round_to_grid(values, target, quantum)
    assert sum(parts, Decimal(0)) == target
    assert all(p == 0 for p, v in zip(parts, values, strict=True) if v == 0)
    assert all(p % quantum == 0 for p in parts)


def test_rounding_errors_and_ties() -> None:
    with pytest.raises(ValueError, match="multiple"):
        round_to_grid([Fraction(1)], Decimal("0.001"), Decimal("0.01"))
    with pytest.raises(ValueError, match="all-zero"):
        round_to_grid([Fraction(0)], Decimal("0.01"), Decimal("0.01"))
    third = Fraction(1, 3)
    assert round_to_grid([third, third, third], Decimal(1), Decimal("0.01")) == [
        Decimal("0.34"),
        Decimal("0.33"),
        Decimal("0.33"),
    ]
    assert round_to_grid([third, third, third], Decimal("0.98"), Decimal("0.01")) == [
        Decimal("0.32"),
        Decimal("0.33"),
        Decimal("0.33"),
    ]


# --- profit decomposition ----------------------------------------------------------------------

P1, P2, P3 = UUID(int=1), UUID(int=2), UUID(int=3)
C1 = UUID(int=11)
money = st.integers(min_value=0, max_value=10**6).map(lambda n: Decimal(n) / 100)
units = st.integers(min_value=0, max_value=500).map(Decimal)


@st.composite
def product_figures(draw: st.DrawFn) -> ProductFigures:
    n = draw(units)
    if n == 0:
        return ProductFigures(refunds=draw(money))
    return ProductFigures(
        revenue=draw(money), units=n, cogs=draw(money), fees=draw(money), refunds=draw(money)
    )


@st.composite
def periods(draw: st.DrawFn) -> PeriodFigures:
    chosen = draw(st.lists(st.sampled_from([P1, P2, P3]), unique=True, max_size=3))
    return PeriodFigures(
        products={p: draw(product_figures()) for p in chosen},
        ad_spend={C1: draw(money)} if draw(st.booleans()) else {},
        fixed_costs=draw(money),
    )


@settings(max_examples=150)
@given(periods(), periods())
def test_decomposition_is_efficient_at_both_levels(base: PeriodFigures, cur: PeriodFigures) -> None:
    d = decompose(base, cur)
    assert d.delta == cur.net_profit() - base.net_profit()
    assert sum(d.level1.values(), Fraction(0)) == d.delta
    for driver in LEVEL1_DRIVERS:
        if driver is not Driver.FIXED_COSTS:
            assert sum(d.level2[driver].values(), Fraction(0)) == d.level1[driver]


@given(periods())
def test_unchanged_period_has_all_zero_contributions(base: PeriodFigures) -> None:
    d = decompose(base, base)
    assert d.delta == 0
    assert all(v == 0 for v in d.level1.values())


@given(product_figures(), st.integers(min_value=1, max_value=400))
def test_only_unit_cost_changes(figures: ProductFigures, extra_cost_cents: int) -> None:
    if figures.units == 0:
        return
    extra = Decimal(extra_cost_cents) / 100
    base = PeriodFigures(products={P1: figures, P2: ProductFigures(Decimal(50), Decimal(5))})
    cur = PeriodFigures(
        products={
            P1: ProductFigures(
                figures.revenue, figures.units, figures.cogs + extra, figures.fees, figures.refunds
            ),
            P2: ProductFigures(Decimal(50), Decimal(5)),
        }
    )
    d = decompose(base, cur)
    assert d.level1[Driver.UNIT_COST] == -Fraction(extra)
    assert all(v == 0 for k, v in d.level1.items() if k is not Driver.UNIT_COST)


def test_figures_without_units_cannot_carry_sales() -> None:
    with pytest.raises(ValueError, match="no units sold"):
        ProductFigures(fees=Decimal(1))
    assert ProductFigures(refunds=Decimal(5)).refunds == 5  # refunds alone are fine


def test_hand_computed_volume_and_mix() -> None:
    # One product, 10 -> 12 units at $10, cost $4, fee $1: margin $5/unit, delta = 2 x 5 = 10,
    # all volume (the product is 100% of the mix in both periods).
    base = PeriodFigures({P1: ProductFigures(Decimal(100), Decimal(10), Decimal(40), Decimal(10))})
    cur = PeriodFigures({P1: ProductFigures(Decimal(120), Decimal(12), Decimal(48), Decimal(12))})
    d = decompose(base, cur)
    assert d.level1[Driver.VOLUME] == 10
    assert d.level1[Driver.MIX] == 0
    # Mix: same 20 units, shifting 5 units from a $5-margin product to a $1-margin one.
    hi = (Decimal(10), Decimal(4), Decimal(1))
    lo = (Decimal(10), Decimal(8), Decimal(1))

    def fig(n: int, price: Decimal, cost: Decimal, fee: Decimal) -> ProductFigures:
        return ProductFigures(price * n, Decimal(n), cost * n, fee * n)

    base = PeriodFigures({P1: fig(10, *hi), P2: fig(10, *lo)})
    cur = PeriodFigures({P1: fig(5, *hi), P2: fig(15, *lo)})
    d = decompose(base, cur)
    assert d.level1[Driver.MIX] == -20  # 5 units x ($5 - $1)
    assert d.level1[Driver.VOLUME] == 0
    assert d.level2[Driver.MIX][("product", P1)] == -25
    assert d.level2[Driver.MIX][("product", P2)] == 5


def test_product_sold_in_one_period_only_and_ads_and_fixed() -> None:
    base = PeriodFigures(
        {P1: ProductFigures(Decimal(100), Decimal(10), Decimal(40), Decimal(10), Decimal(5))},
        {C1: Decimal(30)},
        Decimal(200),
    )
    cur = PeriodFigures(
        {P2: ProductFigures(Decimal(90), Decimal(9), Decimal(27), Decimal(9))},
        {C1: Decimal(45)},
        Decimal(210),
    )
    d = decompose(base, cur)
    assert d.level1[Driver.AD_SPEND] == -15
    assert d.level1[Driver.FIXED_COSTS] == -10
    assert d.level1[Driver.REFUNDS] == 5
    assert d.level1[Driver.PRICE] == 0  # undefined per-unit values borrow the other period
    assert sum(d.level1.values(), Fraction(0)) == d.delta


def _full_game(base: PeriodFigures, cur: PeriodFigures) -> dict[Driver, Fraction]:
    """Level 1 by brute force: one 8-player game over the whole profit function."""

    def value(players: frozenset[Driver]) -> Fraction:
        total = Fraction(0)
        for pid in set(base.products) | set(cur.products):
            b = base.products.get(pid, ProductFigures())
            c = cur.products.get(pid, ProductFigures())
            fb = _factors(b, c, base.total_units, cur.total_units)
            fc = _factors(c, b, cur.total_units, base.total_units)

            def x(d: Driver, attr: str, fb: _Factors = fb, fc: _Factors = fc) -> Fraction:
                v: Fraction = getattr(fc if d in players else fb, attr)
                return v

            total += (
                x(Driver.VOLUME, "q")
                * x(Driver.MIX, "s")
                * (x(Driver.PRICE, "price") - x(Driver.UNIT_COST, "cost") - x(Driver.FEES, "fee"))
            )
            refunds = c.refunds if Driver.REFUNDS in players else b.refunds
            total -= Fraction(refunds)
        ads = cur.ad_spend if Driver.AD_SPEND in players else base.ad_spend
        total -= sum((Fraction(a) for a in ads.values()), Fraction(0))
        fixed = cur.fixed_costs if Driver.FIXED_COSTS in players else base.fixed_costs
        return total - Fraction(fixed)

    start = value(frozenset())
    return shapley(LEVEL1_DRIVERS, lambda s: value(s) - start)


@settings(max_examples=40, deadline=None)
@given(periods(), periods())
def test_per_product_decomposition_equals_full_eight_player_game(
    base: PeriodFigures, cur: PeriodFigures
) -> None:
    assert decompose(base, cur).level1 == _full_game(base, cur)
    assert set(PRODUCT_GAME_DRIVERS) < set(LEVEL1_DRIVERS)
