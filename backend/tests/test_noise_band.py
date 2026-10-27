"""Noise bands of profit drivers and the significance flag."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine

from app.causes.drivers import LEVEL1_DRIVERS, Driver, PeriodFigures, ProductFigures, decompose
from app.causes.noise import (
    DailyFigures,
    WindowTotals,
    decompose_totals,
    is_significant,
    noise_band,
    significance,
)
from app.causes.profit import attribute_profit_change
from app.db import tenant_transaction
from app.facts.engine import FactEngine
from app.facts.model import Period
from app.facts.repository import get_facts
from tests.test_profit_attribution import BASE, CUR, _cost_increase_store

amount = st.integers(min_value=0, max_value=10**5).map(float)


def totals(
    rows: list[tuple[float, float, float, float, float]], spend: float, fixed: float
) -> WindowTotals:
    a = np.array([rows], dtype=np.float64)  # 1 resample x products x 5
    return WindowTotals(
        revenue=a[..., 0],
        units=a[..., 1],
        cogs=a[..., 2],
        fees=a[..., 3],
        refunds=a[..., 4],
        spend=np.array([[spend]]),
        fixed=np.array([fixed]),
    )


def figures(
    rows: list[tuple[float, float, float, float, float]], spend: float, fixed: float
) -> PeriodFigures:
    return PeriodFigures(
        {
            UUID(int=i + 1): ProductFigures(*(Decimal(str(x)) for x in r))
            for i, r in enumerate(rows)
        },
        {UUID(int=99): Decimal(str(spend))},
        Decimal(str(fixed)),
    )


# Real figures: revenue, COGS and fees only with units sold (every order line has quantity > 0).
product = st.one_of(
    st.tuples(amount, st.integers(min_value=1, max_value=50).map(float), amount, amount, amount),
    st.tuples(st.just(0.0), st.just(0.0), st.just(0.0), st.just(0.0), amount),
)


@settings(max_examples=60, deadline=None)
@given(
    st.lists(product, min_size=1, max_size=3),
    st.lists(product, min_size=1, max_size=3),
    amount,
    amount,
    amount,
    amount,
)
def test_vectorized_decomposition_matches_exact(
    b: list[tuple[float, ...]],
    c: list[tuple[float, ...]],
    sb: float,
    sc: float,
    kb: float,
    kc: float,
) -> None:
    n = min(len(b), len(c))
    b, c = b[:n], c[:n]
    exact = decompose(figures(b, sb, kb), figures(c, sc, kc)).level1  # type: ignore[arg-type]
    fast = decompose_totals(totals(b, sb, kb), totals(c, sc, kc))  # type: ignore[arg-type]
    for driver in LEVEL1_DRIVERS:
        assert fast[driver][0] == pytest.approx(float(exact[driver]), rel=1e-9, abs=1e-6)


def daily(days: int, seed: int, products: int = 3) -> DailyFigures:
    rng = np.random.default_rng(seed)
    units = rng.poisson(5, (products, days)).astype(np.float64)
    return DailyFigures(
        revenue=units * 20,
        units=units,
        cogs=units * 8,
        fees=units * 1.5,
        refunds=rng.poisson(1, (products, days)) * 20.0,
        spend=np.full((1, days), 50.0),
        fixed=np.full(days, 10.0),
    )


def test_band_from_adjacent_pairs_and_from_block_bootstrap() -> None:
    long = daily(400, 1)
    pairs = noise_band(long, length=14, history_end=400, rng=np.random.default_rng(0), min_pairs=20)
    boot = noise_band(
        daily(70, 1),
        length=14,
        history_end=70,
        rng=np.random.default_rng(0),
        resamples=500,
        min_pairs=20,
    )
    for band in (pairs, boot):
        assert band[Driver.VOLUME][0] < 0 < band[Driver.VOLUME][1]
        assert band[Driver.AD_SPEND] == (0.0, 0.0)  # constant spend: no noise
        assert band[Driver.FIXED_COSTS] == (0.0, 0.0)
        assert band[Driver.PRICE] == pytest.approx((0.0, 0.0), abs=1e-6)  # constant prices
    again = noise_band(daily(70, 1), length=14, history_end=70, rng=np.random.default_rng(0))
    assert again == boot  # seeded
    assert noise_band(
        long, length=14, history_end=3, rng=np.random.default_rng(0)
    ) == dict.fromkeys(LEVEL1_DRIVERS, (0.0, 0.0))


def test_significance() -> None:
    assert is_significant(-5.0, (-1.0, 1.0))
    assert not is_significant(0.5, (-1.0, 1.0))
    assert significance({Driver.MIX: 3.0}, {Driver.MIX: (-1.0, 1.0)}) == {Driver.MIX: True}


@pytest.mark.db
def test_attribution_flags_significant_drivers(app_engine: Engine) -> None:
    store, _, _ = _cost_increase_store(app_engine)
    band = dict.fromkeys(LEVEL1_DRIVERS, (-1.0, 1.0))
    with tenant_transaction(app_engine, store) as conn:
        result = attribute_profit_change(FactEngine(conn, store), BASE, CUR, band)
    assert result.level1[Driver.UNIT_COST].significant is True  # -10 is outside [-1, 1]
    assert result.level1[Driver.VOLUME].significant is False
    with tenant_transaction(app_engine, store) as conn:
        fact = get_facts(conn, store, [result.level1[Driver.UNIT_COST].fact_id])
    assert next(iter(fact.values())).significant is True
    with tenant_transaction(app_engine, store) as conn:
        plain = attribute_profit_change(FactEngine(conn, store), BASE, CUR)
    assert plain.level1[Driver.UNIT_COST].significant is None
    assert plain.level1[Driver.UNIT_COST].fact_id != result.level1[Driver.UNIT_COST].fact_id
    assert Period.days(date(2026, 1, 1), date(2026, 1, 15)) == BASE
