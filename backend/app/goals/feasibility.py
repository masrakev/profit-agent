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
FORMULA_VERSION = 1
CENT = Decimal("0.01")
BASIS_POINT = Decimal("0.0001")


def verdict(probability: float) -> str:
    return next(name for floor, name in VERDICTS if probability >= floor)


def bucket(horizon: int) -> int:
    """The calibration bucket a horizon falls in: the first one at least as long."""
    return next((b for b in BUCKETS if horizon <= b), BUCKETS[-1])


@dataclass(frozen=True)
class Feasibility:
    metric: str
    target: float
    deadline: date
    probability: float
    probability_range: tuple[float, float, float]  # P10, P50, P90 of the bootstrap
    verdict: str
    gap: tuple[float, float, float]  # target minus the forecast's P90, P50, P10
    forecast_range: tuple[float, float, float]  # cumulative P10, P50, P90 at the deadline
    low_evidence: tuple[str, ...]


def low_evidence(f: Forecast) -> tuple[str, ...]:
    reasons = []
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
    rng = np.random.default_rng(seed)
    shares = reached[rng.integers(0, len(reached), size=(RESAMPLES, len(reached)))].mean(axis=1)
    p10, p50, p90 = (float(x) for x in np.percentile(shares, [10, 50, 90]))
    probability = float(reached.mean())
    low, mid, high = f.quantiles(f.horizon)
    return Feasibility(
        metric=f.metric,
        target=target,
        deadline=f.as_of + timedelta(days=f.horizon),
        probability=probability,
        probability_range=(p10, p50, p90),
        verdict=verdict(probability),
        gap=(target - high, target - mid, target - low),
        forecast_range=(low, mid, high),
        low_evidence=low_evidence(f),
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
    p10, _, p90 = feas.probability_range
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
