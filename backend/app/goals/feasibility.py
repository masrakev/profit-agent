"""Whether a goal is reachable: probability, verdict and gap, computed by code (Task 6 A3,
SPEC 17.2, ADR 0023).

- Probability: the share of the calibrated cumulative paths that reach the target at the
  deadline (2,000 seeded draws); its interval is a bootstrap over the draws.
- Verdict from the probability: `likely` (70% or more), `possible` (40% to 70%), `stretch`
  (15% to 40%), `unlikely` (under 15%).
- Gap: the target minus the baseline's cumulative P50 at the deadline (with the P10-P90 the
  forecast gives it).
- `low_evidence`, with its reasons, when the horizon is longer than the store's history or the
  backtest found the forecast poorly calibrated at that horizon.
- Beyond 90 days (SPEC 17.2, rule 6) there is no point probability: the probability is an
  interval 15 points either side (the backtests found 180-day probabilities 13 to 15 points
  off on average), shown with the verdict band its two ends give, and the goal is split into
  quarterly checkpoints (every 90 days to the deadline).

Everything is stored as `estimate` facts: the cumulative forecast for every day to the deadline
(`goal.forecast.<metric>`), the probability (`goal.probability.<metric>`) and the gap
(`goal.gap.<metric>`), with the exact facts of the fit window as parents.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import numpy as np
import numpy.typing as npt
from sqlalchemy import Connection

from app.detection.series import load_series
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.engine import FactEngine
from app.facts.model import Fact, Period, Scope, Unit
from app.goals import facts as gf
from app.goals.forecast import BUCKETS, FIT_DAYS, METHOD, Forecast, daily_values, forecast, frozen

VERDICTS = ((0.70, "likely"), (0.40, "possible"), (0.15, "stretch"), (0.0, "unlikely"))
RESAMPLES = 1000  # bootstrap of the probability over the draws
POINT_HORIZON = 90  # beyond it, a probability is shown as an interval only
LONG_HORIZON_MARGIN = 0.15  # half-width of that interval
CHECKPOINT_DAYS = 90


def verdict(probability: float) -> str:
    return next(name for floor, name in VERDICTS if probability >= floor)


def bucket(horizon: int) -> int:
    """The calibration bucket a horizon falls in: the first one at least as long."""
    return next((b for b in BUCKETS if horizon <= b), BUCKETS[-1])


def checkpoints(horizon: int) -> tuple[int, ...]:
    """Days of the quarterly checkpoints of a goal beyond 90 days, the deadline last."""
    if horizon <= POINT_HORIZON:
        return ()
    return (*range(CHECKPOINT_DAYS, horizon, CHECKPOINT_DAYS), horizon)


@dataclass(frozen=True)
class Feasibility:
    metric: str
    target: float
    deadline: date
    horizon: int
    probability: float  # the share of paths: shown up to 90 days only
    probability_range: tuple[float, float, float]  # low, point, high
    verdict: str  # of the point probability
    verdict_band: tuple[str, str]  # the verdicts of the range's two ends
    gap: tuple[float, float, float]  # target minus the forecast's P90, P50, P10
    forecast_range: tuple[float, float, float]  # cumulative P10, P50, P90 at the deadline
    low_evidence: tuple[str, ...]
    checkpoints: tuple[int, ...] = ()  # days ahead, beyond 90 days

    @property
    def shows_point(self) -> bool:
        return self.horizon <= POINT_HORIZON

    @property
    def shown_probability(self) -> float | None:
        return self.probability if self.shows_point else None


def low_evidence(f: Forecast) -> tuple[str, ...]:
    """Why the evidence is weak, in words without numbers (they reach the owner's text)."""
    reasons = []
    if f.horizon > POINT_HORIZON:
        reasons.append(
            "past a quarter, probabilities were overconfident in the backtest: the probability "
            "is a range, and the goal is checked every quarter"
        )
    if f.horizon > f.history_days:
        reasons.append("the goal's horizon is longer than the store's history")
    poor = frozen().get("poor", {}).get(f.metric, [])
    if bucket(f.horizon) in poor:
        reasons.append(
            f"forecasts of {f.metric.replace('_', ' ')} this far ahead were poorly calibrated "
            "in the backtest"
        )
    return tuple(reasons)


def probability_range(
    values: npt.NDArray[np.float64], target: float, horizon: int, seed: int
) -> tuple[float, float, float]:
    """The share of `values` reaching `target`, with its interval: a bootstrap over the draws
    up to 90 days, 15 points either side beyond (SPEC 17.2, rule 6)."""
    reached = (values >= target).astype(np.float64)
    p = float(reached.mean())
    if horizon > POINT_HORIZON:
        lo, hi = max(0.0, p - LONG_HORIZON_MARGIN), min(1.0, p + LONG_HORIZON_MARGIN)
    else:
        rng = np.random.default_rng(seed)
        draws = rng.integers(0, len(reached), size=(RESAMPLES, len(reached)))
        lo, hi = (float(x) for x in np.percentile(reached[draws].mean(axis=1), [10, 90]))
    return (min(lo, p), p, max(hi, p))


def assess(f: Forecast, target: float, seed: int) -> Feasibility:
    lo, probability, hi = probability_range(f.paths[:, -1], target, f.horizon, seed)
    low, mid, high = f.quantiles(f.horizon)
    return Feasibility(
        metric=f.metric,
        target=target,
        deadline=f.as_of + timedelta(days=f.horizon),
        horizon=f.horizon,
        probability=probability,
        probability_range=(lo, probability, hi),
        verdict=verdict(probability),
        verdict_band=(verdict(lo), verdict(hi)),
        gap=(target - high, target - mid, target - low),
        forecast_range=(low, mid, high),
        low_evidence=low_evidence(f),
        checkpoints=checkpoints(f.horizon),
    )


def seed_of(*parts: object) -> int:
    """A reproducible seed: the same goal on the same data draws the same forecast."""
    return int(sha256_hex(canonical_json([str(p) for p in parts]))[:16], 16)


@dataclass(frozen=True)
class Assessment:
    feasibility: Feasibility
    forecast: dict[int, Fact]  # day -> the cumulative forecast fact to that day
    probability: Fact
    gap: Fact
    history: Fact  # the fit window's exact fact, the forecast's parent


def assess_store(
    conn: Connection,
    store_id: UUID,
    metric: str,
    target: Decimal,
    deadline: date,
    *,
    currency: str,
    as_of: date | None = None,
) -> Assessment:
    """The goal's feasibility from the store's data before `as_of` (default: all of it),
    with its facts."""
    series = load_series(conn, store_id)
    every = daily_values(series, metric)
    end = series.days if as_of is None else series.index(as_of)
    values = np.array([float(v) for v in every[:end]], dtype=np.float64)
    as_of = series.start + timedelta(days=end)
    horizon = (deadline - as_of).days
    seed = seed_of(store_id, metric, as_of, horizon)
    f = forecast(values, series.start, metric, horizon, seed)
    feas = assess(f, float(target), seed_of(store_id, metric, as_of, horizon, target))
    engine = FactEngine(conn, store_id)
    window = Period.days(as_of - timedelta(days=min(FIT_DAYS, end)), as_of)
    history = engine.persist(engine.adopt(engine.fact(metric, Scope.store(), window)))
    method = f"{METHOD};calibration {f.calibration}"
    parents = (("history", history),)

    def estimate(
        formula: str, day: int, unit: Unit, qs: tuple[float, float, float], key: object
    ) -> Fact:
        return gf.estimate(
            engine,
            store_id,
            formula=formula,
            period=(as_of, as_of + timedelta(days=day)),
            unit=unit,
            quantiles=qs,
            method=method,
            key=(seed, key),
            parents=parents,
            currency=currency,
        )

    daily = {
        day: estimate(f"goal.forecast.{metric}", day, Unit.MONEY, f.quantiles(day), day)
        for day in range(1, f.horizon + 1)
    }
    # Beyond 90 days the probability fact carries the range only, so a citation renders it so.
    probability = estimate(
        f"goal.probability.{metric}", horizon, Unit.RATIO, feas.probability_range, target
    )
    gap = estimate(f"goal.gap.{metric}", horizon, Unit.MONEY, feas.gap, target)
    return Assessment(feas, daily, probability, gap, history)
