"""Noise bands for profit drivers, and the vectorized decomposition they rely on.

A driver's contribution is "significant" when it lies outside the P5-P95 band of contributions
that the same driver shows between pairs of equal-length *healthy* windows of the store's own
history. Statistical outputs, so floats (NumPy); the contributions themselves stay exact facts.

Pairs: adjacent windows of the history, stepping by a week. When the history yields fewer than
`min_pairs` pairs, a seeded block bootstrap builds pseudo-windows from 7-day blocks of the history.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from math import factorial

import numpy as np
from numpy.typing import NDArray

from app.causes.drivers import LEVEL1_DRIVERS, PRODUCT_GAME_DRIVERS, Driver

FloatArray = NDArray[np.float64]
BLOCK_DAYS = 7


@dataclass(frozen=True)
class DailyFigures:
    """Daily amounts: products x days (revenue, units, cogs, fees, refunds), campaigns x days
    (spend), and days (fixed costs)."""

    revenue: FloatArray
    units: FloatArray
    cogs: FloatArray
    fees: FloatArray
    refunds: FloatArray
    spend: FloatArray
    fixed: FloatArray

    @property
    def days(self) -> int:
        return int(self.fixed.shape[0])

    def window_totals(self, index: NDArray[np.int64]) -> "WindowTotals":
        """Totals over the day indexes `index` (resamples x window length)."""
        return WindowTotals(
            revenue=self.revenue[:, index].sum(axis=-1).T,
            units=self.units[:, index].sum(axis=-1).T,
            cogs=self.cogs[:, index].sum(axis=-1).T,
            fees=self.fees[:, index].sum(axis=-1).T,
            refunds=self.refunds[:, index].sum(axis=-1).T,
            spend=self.spend[:, index].sum(axis=-1).T,
            fixed=self.fixed[index].sum(axis=-1),
        )


@dataclass(frozen=True)
class WindowTotals:
    """Per resample: products (R x P), campaigns (R x C), fixed costs (R)."""

    revenue: FloatArray
    units: FloatArray
    cogs: FloatArray
    fees: FloatArray
    refunds: FloatArray
    spend: FloatArray
    fixed: FloatArray


def _per_unit(
    amount: FloatArray, units: FloatArray, other: FloatArray, other_units: FloatArray
) -> FloatArray:
    """Per-unit value, borrowing the other period's when nothing sold (as in drivers.py)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        mine = np.where(units > 0, amount / np.where(units > 0, units, 1), np.nan)
        theirs = np.where(other_units > 0, other / np.where(other_units > 0, other_units, 1), 0.0)
    return np.where(np.isnan(mine), theirs, mine)


def _factors(mine: WindowTotals, other: WindowTotals) -> dict[Driver, FloatArray]:
    q = mine.units.sum(axis=1, keepdims=True)
    other_q = other.units.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(q > 0, mine.units / np.where(q > 0, q, 1), np.nan)
        other_share = np.where(other_q > 0, other.units / np.where(other_q > 0, other_q, 1), 0.0)
    return {
        Driver.VOLUME: np.broadcast_to(q, mine.units.shape),
        Driver.MIX: np.where(np.isnan(share), other_share, share),
        Driver.PRICE: _per_unit(mine.revenue, mine.units, other.revenue, other.units),
        Driver.UNIT_COST: _per_unit(mine.cogs, mine.units, other.cogs, other.units),
        Driver.FEES: _per_unit(mine.fees, mine.units, other.fees, other.units),
    }


def decompose_totals(
    base: WindowTotals,
    cur: WindowTotals,
    products: NDArray[np.bool_] | None = None,
    campaigns: NDArray[np.bool_] | None = None,
) -> dict[Driver, FloatArray]:
    """Level-1 Shapley contributions per resample (same game as `drivers.decompose`).

    With `products` / `campaigns` masks, only those entities' level-2 contributions are summed
    (the game itself, including total volume, always covers every product).
    """
    keep_p = np.ones(base.units.shape[1], dtype=bool) if products is None else products
    keep_c = np.ones(base.spend.shape[1], dtype=bool) if campaigns is None else campaigns
    fb, fc = _factors(base, cur), _factors(cur, base)
    players = PRODUCT_GAME_DRIVERS
    n = len(players)
    weights = [factorial(k) * factorial(n - k - 1) / factorial(n) for k in range(n)]

    def value(mask: int) -> FloatArray:
        pick = {d: (fc if mask >> i & 1 else fb)[d] for i, d in enumerate(players)}
        margin = pick[Driver.PRICE] - pick[Driver.UNIT_COST] - pick[Driver.FEES]
        return pick[Driver.VOLUME] * pick[Driver.MIX] * margin

    values = [value(mask) for mask in range(1 << n)]
    out = {d: np.zeros(base.fixed.shape) for d in LEVEL1_DRIVERS}
    for i, driver in enumerate(players):
        bit = 1 << i
        total = np.zeros_like(values[0])
        for mask in range(1 << n):
            if not mask & bit:
                total += weights[mask.bit_count()] * (values[mask | bit] - values[mask])
        out[driver] = total[:, keep_p].sum(axis=1)
    out[Driver.REFUNDS] = -(cur.refunds - base.refunds)[:, keep_p].sum(axis=1)
    out[Driver.AD_SPEND] = -(cur.spend - base.spend)[:, keep_c].sum(axis=1)
    out[Driver.FIXED_COSTS] = -(cur.fixed - base.fixed)
    return out


def _block_window(
    rng: np.random.Generator, history_end: int, length: int, resamples: int
) -> NDArray[np.int64]:
    """Pseudo-windows of `length` days built from random whole 7-day blocks of the history."""
    blocks = -(-length // BLOCK_DAYS)
    starts = rng.integers(0, history_end - BLOCK_DAYS + 1, size=(resamples, blocks))
    days = starts[:, :, None] + np.arange(BLOCK_DAYS)[None, None, :]
    return days.reshape(resamples, -1)[:, :length]


def noise_band(
    figures: DailyFigures,
    *,
    length: int,
    history_end: int,
    rng: np.random.Generator,
    resamples: int = 500,
    min_pairs: int = 20,
    quantiles: tuple[float, float] = (5.0, 95.0),
) -> dict[Driver, tuple[float, float]]:
    """P5-P95 of each driver's contribution between equal-length healthy windows."""
    if history_end < BLOCK_DAYS:
        return dict.fromkeys(LEVEL1_DRIVERS, (0.0, 0.0))
    starts = list(range(history_end - 2 * length, -1, -BLOCK_DAYS))
    if len(starts) >= min_pairs:
        offsets = np.arange(length)
        base_idx = np.array([s + offsets for s in starts])
        cur_idx = base_idx + length
    else:
        base_idx = _block_window(rng, history_end, length, resamples)
        cur_idx = _block_window(rng, history_end, length, resamples)
    contributions = decompose_totals(
        figures.window_totals(base_idx), figures.window_totals(cur_idx)
    )
    low, high = quantiles
    return {
        d: (float(np.percentile(v, low)), float(np.percentile(v, high)))
        for d, v in contributions.items()
    }


def is_significant(value: float, band: tuple[float, float]) -> bool:
    low, high = band
    return value < low or value > high


def significance(
    contributions: Mapping[Driver, float], band: Mapping[Driver, tuple[float, float]]
) -> dict[Driver, bool]:
    return {d: is_significant(v, band[d]) for d, v in contributions.items()}
