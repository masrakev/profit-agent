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
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

import numpy as np
from sqlalchemy import Connection

from app.detection.series import load_series
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.engine import FactEngine
from app.facts.model import Fact, FactKind, FactStatus, Lineage, ParentRef, Period, Scope, Unit
from app.goals.forecast import BUCKETS, FIT_DAYS, METHOD, Forecast, daily_values, forecast, frozen

VERDICTS = ((0.70, "likely"), (0.40, "possible"), (0.15, "stretch"), (0.0, "unlikely"))
RESAMPLES = 1000  # bootstrap of the probability over the draws
POINT_HORIZON = 90  # beyond it, a probability is shown as an interval only
LONG_HORIZON_MARGIN = 0.15  # half-width of that interval
CHECKPOINT_DAYS = 90
FORMULA_VERSION = 1
CENT = Decimal("0.01")
BASIS_POINT = Decimal("0.0001")


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
    reasons = []
    if f.horizon > POINT_HORIZON:
        reasons.append(
            f"beyond {POINT_HORIZON} days probabilities were overconfident in the backtest: the "
            "probability is a range, and the goal is checked every quarter"
        )
    if f.horizon > f.history_days:
        reasons.append(
            f"the horizon ({f.horizon} days) is longer than the store's history "
            f"({f.history_days} days)"
        )
    poor = frozen().get("poor", {}).get(f.metric, [])
    if bucket(f.horizon) in poor:
        reasons.append(
            f"forecasts of {f.metric.replace('_', ' ')} over {bucket(f.horizon)} days were "
            "poorly calibrated in the backtest"
        )
    return tuple(reasons)


def assess(f: Forecast, target: float, seed: int) -> Feasibility:
    final = f.paths[:, -1]
    reached = (final >= target).astype(np.float64)
    probability = float(reached.mean())
    if f.horizon > POINT_HORIZON:
        lo = max(0.0, probability - LONG_HORIZON_MARGIN)
        hi = min(1.0, probability + LONG_HORIZON_MARGIN)
    else:
        rng = np.random.default_rng(seed)
        draws = rng.integers(0, len(reached), size=(RESAMPLES, len(reached)))
        lo, hi = (float(x) for x in np.percentile(reached[draws].mean(axis=1), [10, 90]))
    low, mid, high = f.quantiles(f.horizon)
    return Feasibility(
        metric=f.metric,
        target=target,
        deadline=f.as_of + timedelta(days=f.horizon),
        horizon=f.horizon,
        probability=probability,
        probability_range=(min(lo, probability), probability, max(hi, probability)),
        verdict=verdict(probability),
        verdict_band=(verdict(lo), verdict(hi)),
        gap=(target - high, target - mid, target - low),
        forecast_range=(low, mid, high),
        low_evidence=low_evidence(f),
        checkpoints=checkpoints(f.horizon),
    )


def _seed(*parts: object) -> int:
    return int(sha256_hex(canonical_json([str(p) for p in parts]))[:16], 16)


def _money(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(CENT, rounding=ROUND_HALF_EVEN)


def _ratio(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(BASIS_POINT, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class Assessment:
    feasibility: Feasibility
    forecast: dict[int, Fact]  # day -> the cumulative forecast fact to that day
    probability: Fact
    gap: Fact


def assess_store(
    conn: Connection,
    store_id: UUID,
    metric: str,
    target: Decimal,
    deadline: date,
    *,
    currency: str,
) -> Assessment:
    """The goal's feasibility from the store's data (to its last day), with its facts."""
    series = load_series(conn, store_id)
    values = np.array([float(v) for v in daily_values(series, metric)], dtype=np.float64)
    as_of = series.start + timedelta(days=series.days)
    horizon = (deadline - as_of).days
    seed = _seed(store_id, metric, as_of, horizon)
    f = forecast(values, series.start, metric, horizon, seed)
    feas = assess(f, float(target), _seed(store_id, metric, as_of, horizon, target))
    engine = FactEngine(conn, store_id)
    window = Period.days(as_of - timedelta(days=min(FIT_DAYS, series.days)), as_of)
    parent = engine.adopt(engine.fact(metric, Scope.store(), window))
    lineage = Lineage(parents=(ParentRef(role="history", fact_hash=parent.fact_hash),))
    method = f"{METHOD};calibration {f.calibration}"

    def estimate(formula: str, end: date, unit: Unit, qs: tuple[Decimal, ...], key: object) -> Fact:
        fact = Fact(
            store_id=store_id,
            formula_id=formula,
            formula_version=FORMULA_VERSION,
            kind=FactKind.ESTIMATE,
            scope=Scope.store(),
            period=Period.days(as_of, end),
            status=FactStatus.DEFINED,
            value=qs[1],
            p10=qs[0],
            p50=qs[1],
            p90=qs[2],
            method=method,
            unit=unit,
            currency=currency if unit is Unit.MONEY else None,
            inputs_hash=sha256_hex(
                canonical_json(
                    {"formula": formula, "method": method, "seed": seed, "key": str(key)}
                )
            ),
            lineage=lineage,
        )
        return engine.persist(engine.adopt(fact))

    daily = {
        day: estimate(
            f"goal.forecast.{metric}",
            as_of + timedelta(days=day),
            Unit.MONEY,
            tuple(_money(q) for q in f.quantiles(day)),
            day,
        )
        for day in range(1, f.horizon + 1)
    }
    p10, _, p90 = feas.probability_range  # beyond 90 days the fact renders as this range
    probability = estimate(
        f"goal.probability.{metric}",
        deadline,
        Unit.RATIO,
        (_ratio(p10), _ratio(feas.probability), _ratio(p90)),
        target,
    )
    gap = estimate(
        f"goal.gap.{metric}", deadline, Unit.MONEY, tuple(_money(g) for g in feas.gap), target
    )
    return Assessment(feas, daily, probability, gap)
