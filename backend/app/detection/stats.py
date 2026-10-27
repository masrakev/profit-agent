"""Pure detection statistics on daily series. No I/O, no randomness.

Detector statistics are decisions about *when* something changed, not facts: they run in floats.
Everything a symptom reports is backed by exact facts computed separately.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class Episode:
    """A run of flagged days: `confirmed` is the first day the persistence requirement holds."""

    start: int
    confirmed: int
    end: int  # last flagged day of the run, inclusive
    peak: float


def rolling_sum(values: Sequence[Decimal], window: int) -> list[Decimal | None]:
    """Sum over the `window` days ending at each day (None until a full window exists)."""
    out: list[Decimal | None] = [None] * len(values)
    total = Decimal(0)
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        if i >= window - 1:
            out[i] = total
    return out


def ratio_series(
    numerator: Sequence[Decimal | None],
    denominator: Sequence[Decimal | None],
    min_denominator: Decimal = Decimal(0),
) -> list[float | None]:
    """Numerator / denominator per day; None where the denominator is missing or too small."""
    out: list[float | None] = []
    for n, d in zip(numerator, denominator, strict=True):
        if n is None or d is None or d <= min_denominator or d == 0:
            out.append(None)
        else:
            out.append(float(n / d))
    return out


def as_floats(values: Sequence[Decimal | None]) -> list[float | None]:
    return [None if v is None else float(v) for v in values]


def robust_scale(
    values: Sequence[float], rel_floor: float, abs_floor: float
) -> tuple[float, float]:
    """Median and a robust scale: 1.4826 * MAD, floored relative to the median and absolutely."""
    center = median(values)
    mad = median(abs(v - center) for v in values)
    return center, max(MAD_TO_SIGMA * mad, rel_floor * abs(center), abs_floor)


def robust_z(
    series: Sequence[float | None],
    *,
    window: int,
    baseline: int,
    direction: int,
    rel_floor: float,
    abs_floor: float,
    min_baseline_level: float = 0.0,
) -> list[float | None]:
    """Signed z-score of each day's value against the trailing baseline of non-overlapping windows.

    The baseline for day t is the values of days [t - window - baseline + 1, t - window], so it
    never overlaps the current window. `direction` is +1 when increases are bad, -1 for decreases.
    """
    out: list[float | None] = [None] * len(series)
    for t in range(len(series)):
        lo = t - window - baseline + 1
        current = series[t]
        if lo < 0 or current is None:
            continue
        reference = [v for v in series[lo : t - window + 1] if v is not None]
        if len(reference) < baseline // 2:
            continue
        center, scale = robust_scale(reference, rel_floor, abs_floor)
        if abs(center) < min_baseline_level:
            continue
        out[t] = direction * (current - center) / scale
    return out


def standardize(
    series: Sequence[float | None],
    *,
    reference_start: int,
    reference_days: int,
    rel_floor: float,
    abs_floor: float,
) -> list[float | None]:
    """(x_t - mu) / sigma after a fixed reference period, with robust mu and sigma from it."""
    reference = [
        v for v in series[reference_start : reference_start + reference_days] if v is not None
    ]
    out: list[float | None] = [None] * len(series)
    if len(reference) < reference_days // 2:
        return out
    center, scale = robust_scale(reference, rel_floor, abs_floor)
    for t in range(reference_start + reference_days, len(series)):
        value = series[t]
        if value is not None:
            out[t] = (value - center) / scale
    return out


def cusum_path(z: Sequence[float | None], *, direction: int, k: float) -> list[float | None]:
    """One-sided CUSUM: S_t = max(0, S_{t-1} + direction * z_t - k); None where z_t is None."""
    out: list[float | None] = [None] * len(z)
    s = 0.0
    for t, value in enumerate(z):
        if value is None:
            continue
        s = max(0.0, s + direction * value - k)
        out[t] = s
    return out


def poisson_residuals(
    observed: Sequence[Decimal], expected: Sequence[float | None]
) -> list[float | None]:
    """(observed - expected) / sqrt(expected), the standardized Poisson residual per day."""
    return [
        None if e is None or e <= 0 else (float(o) - e) / math.sqrt(e)
        for o, e in zip(observed, expected, strict=True)
    ]


def binomial_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return min(1.0, sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def rate_increase_p_value(
    current_events: int, current_exposure: float, base_events: int, base_exposure: float
) -> float:
    """Conditional test that the current event rate exceeds the baseline rate.

    Under equal rates, given K = current + base events, the current count is
    Binomial(K, current_exposure / (current_exposure + base_exposure)). Unlike plugging in the
    baseline rate, this accounts for the baseline's own sampling noise.
    """
    total = current_events + base_events
    share = current_exposure / (current_exposure + base_exposure)
    return binomial_sf(current_events, total, share)


def rate_drop_change_point(
    events: Sequence[Decimal],
    exposure: Sequence[Decimal],
    lo: int,
    hi: int,
    *,
    min_before: int,
    min_after: int,
) -> int | None:
    """Most likely day where the rate events / exposure dropped, within [lo, hi).

    For each split k, a two-sample test of the rates before ([lo, k)) and after ([k, hi)):
    z = (r1 - r2) / sqrt(pooled * (1 / x1 + 1 / x2)). Returns the k with the largest positive z
    (None when no split has a drop). Uses only data before `hi`, so it never looks ahead.
    """
    ev = [0.0]
    ex = [0.0]
    for t in range(lo, hi):
        ev.append(ev[-1] + float(events[t]))
        ex.append(ex[-1] + float(exposure[t]))
    best, best_z = None, 0.0
    for k in range(lo + min_before, hi - min_after + 1):
        e1, x1 = ev[k - lo], ex[k - lo]
        e2, x2 = ev[-1] - e1, ex[-1] - x1
        if x1 <= 0 or x2 <= 0:
            continue
        pooled = (e1 + e2) / (x1 + x2)
        if pooled <= 0:
            continue
        z = (e1 / x1 - e2 / x2) / math.sqrt(pooled * (1 / x1 + 1 / x2))
        if z > best_z:
            best, best_z = k, z
    return best


def cusum_start(path: Sequence[float | None], episode_start: int) -> int:
    """Change-point estimate of a CUSUM alarm: the day after the statistic was last zero."""
    t = episode_start
    while t > 0 and (path[t - 1] or 0.0) > 0.0:
        t -= 1
    return t


def normal_sf(z: float) -> float:
    """P(Z >= z) for a standard normal Z."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def benjamini_hochberg(p_values: Sequence[float], q: float) -> list[bool]:
    """Which hypotheses are rejected at false discovery rate `q` (Benjamini-Hochberg step-up)."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    cutoff = -1
    for rank, i in enumerate(order, start=1):
        if p_values[i] <= q * rank / m:
            cutoff = rank
    rejected = [False] * m
    for rank, i in enumerate(order, start=1):
        if rank <= cutoff:
            rejected[i] = True
    return rejected


def episodes(scores: Sequence[float | None], threshold: float, persist: int) -> list[Episode]:
    """Runs of consecutive days with score >= threshold lasting at least `persist` days."""
    found: list[Episode] = []
    run_start: int | None = None
    peak = -math.inf
    for t, score in enumerate([*scores, None]):
        flagged = score is not None and score >= threshold
        if flagged:
            assert score is not None
            if run_start is None:
                run_start, peak = t, score
            peak = max(peak, score)
            continue
        if run_start is not None and t - run_start >= persist:
            found.append(Episode(run_start, run_start + persist - 1, t - 1, peak))
        run_start, peak = None, -math.inf
    return found
