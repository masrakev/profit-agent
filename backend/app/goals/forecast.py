"""Baseline forecast of a store metric to a goal's deadline (Task 6 A2, ADR 0023).

The metric's daily values (net profit, contribution margin or revenue, by the fact formulas'
definitions: `daily_values`) over the fit window (the last 8 weeks) are modelled as a level, a
linear trend and day-of-week effects, by least squares; what the model leaves is the residual.
Ahead, the trend is damped: its daily growth halves every 60 days. The simulation is a seeded
block bootstrap: each draw refits the model on the fitted values plus residuals resampled in
weekly blocks (moving blocks, so a week's autocorrelation is kept), which carries the trend's
uncertainty forward, then adds future residuals in blocks; the draw's daily values are summed
into a cumulative path. Uncertainty grows with the horizon twice over: residuals add up, and
the bootstrapped trend fans out.

The paths are then calibrated: each day's deviations from the median path are scaled by the
frozen conformal factor of its horizon (`calibration.json`, fitted on `goals_dev` by
`bench.goals_backtest`), interpolated between the horizon buckets.
"""

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from app.detection.series import StoreSeries

FloatArray = npt.NDArray[np.float64]

METRICS = ("net_profit", "contribution_margin", "revenue")
METHOD = "goal_trend_block_bootstrap_v1"
DRAWS = 2000
BLOCK = 7  # residuals are resampled a week at a time
# Chosen on goals_dev by cross-validation (bench/reports/goals-backtest-dev.md): the last 8
# weeks, the trend's daily growth halving every 60 days ahead.
FIT_DAYS = 56
TREND_HALF_LIFE: float | None = 60.0  # days for the trend to halve ahead; None: kept linear
MIN_HISTORY = 28  # days of data needed to forecast at all
MAX_HORIZON = 186  # six months
BUCKETS = (30, 60, 90, 180)  # horizons the calibration is fitted at (days)
FROZEN = Path(__file__).with_name("calibration.json")


def daily_values(series: StoreSeries, metric: str) -> list[Decimal]:
    """The metric per day, by the fact formulas' definitions (a window sum equals the fact):
    revenue; contribution margin = revenue - COGS - fees - refunds; net profit = contribution
    margin - ad spend - fixed costs (prorated per day)."""
    if metric not in METRICS:
        raise ValueError(f"no forecast for {metric}")
    revenue = series.total("revenue")
    if metric == "revenue":
        return revenue
    costs = [series.total(m) for m in ("cogs", "unit_fees", "payment_fees", "refunds")]
    margin = [r - sum(c[i] for c in costs) for i, r in enumerate(revenue)]
    if metric == "contribution_margin":
        return margin
    spend = [sum(c.spend[i] for c in series.campaigns.values()) for i in range(series.days)]
    fixed = series.fixed_costs or [Decimal(0)] * series.days
    return [m - s - f for m, s, f in zip(margin, spend, fixed, strict=True)]


@cache
def frozen() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FROZEN.read_text(encoding="utf-8"))
    return data


def scale(metric: str, day: int) -> float:
    """The calibration factor for the cumulative value `day` days ahead: the frozen factors of
    the horizon buckets, linear between them, constant outside."""
    fitted: dict[str, float] = frozen()["scales"].get(metric, {})
    if not fitted:
        return 1.0
    points = sorted((int(h), float(s)) for h, s in fitted.items())
    if day <= points[0][0]:
        return points[0][1]
    for (h0, s0), (h1, s1) in pairwise(points):
        if day <= h1:
            return s0 + (s1 - s0) * (day - h0) / (h1 - h0)
    return points[-1][1]


@dataclass(frozen=True)
class Fit:
    history_days: int  # days of data before the forecast starts
    window: int  # the last `window` of them are fitted
    first_dow: int  # weekday of the first fitted day (Monday = 0)
    beta: FloatArray
    fitted: FloatArray
    residuals: FloatArray
    pinv: FloatArray  # least-squares solver of the design
    half_life: float | None = TREND_HALF_LIFE

    @property
    def level(self) -> float:
        """The typical daily magnitude of the metric over the window (for scale)."""
        return float(np.abs(self.fitted + self.residuals).mean())


def _design(
    start: int, length: int, window: int, first_dow: int, half_life: float | None = None
) -> FloatArray:
    """Rows of the design for days `start` to `start + length - 1` (day 0: the first fitted
    day): level, trend, and Tuesday to Sunday. Beyond the fitted window a damped trend grows
    less each day (its increments halve every `half_life` days; 0 stops it)."""
    t = np.arange(start, start + length, dtype=np.float64)
    center, last = (window - 1) / 2, window - 1
    trend = t - center
    if half_life is not None:
        ahead = np.maximum(t - last, 0.0)
        phi = 0.0 if half_life == 0 else 0.5 ** (1.0 / half_life)
        grown = ahead if phi == 1.0 else phi * (1.0 - phi**ahead) / (1.0 - phi)
        trend = np.where(t > last, last - center + grown, trend)
    dow = (first_dow + t) % 7
    columns = [np.ones(length), trend / 365.0]
    columns += [(dow == d).astype(np.float64) for d in range(1, 7)]
    return np.column_stack(columns)


def fit(
    values: FloatArray,
    first_day: date,
    window: int = FIT_DAYS,
    half_life: float | None = TREND_HALF_LIFE,
) -> Fit:
    """Least squares on the last `window` days of `values` (day 0 is `first_day`)."""
    n = len(values)
    if n < MIN_HISTORY:
        raise ValueError(f"{n} days of data: at least {MIN_HISTORY} are needed to forecast")
    w = min(n, window)
    first_dow = (first_day + timedelta(days=n - w)).weekday()
    x = _design(0, w, w, first_dow)
    y = values[n - w :]
    pinv = np.linalg.pinv(x)
    beta = pinv @ y
    fitted = x @ beta
    return Fit(n, w, first_dow, beta, fitted, y - fitted, pinv, half_life)


def _blocks(rng: np.random.Generator, residuals: FloatArray, draws: int, length: int) -> FloatArray:
    """`draws` series of `length` residuals, resampled in circular blocks of `BLOCK` days."""
    n = len(residuals)
    k = math.ceil(length / BLOCK)
    starts = rng.integers(0, n, size=(draws, k))
    idx = (starts[:, :, None] + np.arange(BLOCK)[None, None, :]) % n
    out: FloatArray = residuals[idx.reshape(draws, k * BLOCK)[:, :length]]
    return out


def simulate(f: Fit, horizon: int, rng: np.random.Generator, draws: int = DRAWS) -> FloatArray:
    """Raw cumulative paths, `draws` x `horizon`: day k is the sum of the first k + 1 days."""
    refit = (f.fitted[None, :] + _blocks(rng, f.residuals, draws, f.window)) @ f.pinv.T
    future = _design(f.window, horizon, f.window, f.first_dow, f.half_life)
    daily = refit @ future.T + _blocks(rng, f.residuals, draws, horizon)
    paths: FloatArray = np.cumsum(daily, axis=1)
    return paths


def calibrate(paths: FloatArray, metric: str) -> FloatArray:
    """Scale each day's deviations from the median path by that horizon's frozen factor."""
    median = np.median(paths, axis=0)
    factors = np.array([scale(metric, k + 1) for k in range(paths.shape[1])])
    out: FloatArray = median + (paths - median) * factors
    return out


@dataclass(frozen=True)
class Forecast:
    metric: str
    as_of: date  # the first forecast day (the day after the last day of data)
    history_days: int
    level: float
    paths: FloatArray  # calibrated cumulative paths, draws x horizon
    calibration: str

    @property
    def horizon(self) -> int:
        return int(self.paths.shape[1])

    def quantiles(self, day: int) -> tuple[float, float, float]:
        """P10, P50, P90 of the cumulative value over the first `day` days."""
        q10, q50, q90 = np.percentile(self.paths[:, day - 1], [10, 50, 90])
        return float(q10), float(q50), float(q90)


def forecast(
    values: FloatArray,
    first_day: date,
    metric: str,
    horizon: int,
    seed: int,
    *,
    window: int = FIT_DAYS,
    half_life: float | None = TREND_HALF_LIFE,
    calibrated: bool = True,
) -> Forecast:
    """The metric's cumulative forecast over the `horizon` days after `values` end."""
    if not 1 <= horizon <= MAX_HORIZON:
        raise ValueError(f"a horizon of {horizon} days: between 1 and {MAX_HORIZON}")
    f = fit(values, first_day, window, half_life)
    paths = simulate(f, horizon, np.random.default_rng(seed))
    return Forecast(
        metric=metric,
        as_of=first_day + timedelta(days=len(values)),
        history_days=len(values),
        level=f.level,
        paths=calibrate(paths, metric) if calibrated else paths,
        calibration=frozen()["version"] if calibrated else "uncalibrated",
    )
