"""Calibrated outcome intervals: a split-conformal widening per action kind (ADR 0018, Task 5).

Against the truth (the same store without the action), the synthetic-control interval of
`control.py`, built from pre-period residuals only, is too narrow: its P10-P90 held the true
effect 69% of the time on dev scenarios, pauses 44% (bench/reports/outcome-validation.md). Each
action kind's interval is widened in proportion to its own width, the median unchanged:

    [P10 - q * w, P90 + q * w],   w = P90 - P10

`q` is the split-conformal quantile of the score max(P10 - truth, truth - P90) / w over the
calibration set's reported estimates, at rank ceil((n + 1) * 0.8): under exchangeability, a new
interval then holds the truth at least 80% of the time. It is never negative (a kind already
covered is not narrowed). The widenings are fitted once by `bench.outcome_calibration` on dev
decision scenarios and frozen in `outcome_calibration.json`; a kind with no fit (a resume, say)
gets the widest one.
"""

import json
import math
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

FROZEN = Path(__file__).with_name("outcome_calibration.json")
TARGET = 0.8
Interval = tuple[float, float, float]


@cache
def frozen() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FROZEN.read_text(encoding="utf-8"))
    return data


def action_key(kind: str, before: dict[str, Any] | None, after: dict[str, Any] | None) -> str:
    """The calibration key of an executed action: a budget change is a cut or a raise."""
    if kind != "change_budget":
        return kind
    old = (before or {}).get("daily_budget_minor")
    new = (after or {}).get("daily_budget_minor")
    raised = old is not None and new is not None and new > old
    return "increase_budget" if raised else "reduce_budget"


def widening(key: str) -> float:
    fitted: dict[str, float] = frozen()["widening"]
    return float(fitted.get(key, max(fitted.values(), default=0.0)))


def expand(effect: Interval, q: float) -> Interval:
    p10, p50, p90 = effect
    gap = q * (p90 - p10)
    return (p10 - gap, p50, p90 + gap)


def widen(effect: Interval, key: str) -> Interval:
    return expand(effect, widening(key))


def score(effect: Interval, truth: float) -> float:
    """How far outside its interval the truth fell, in interval widths (negative: inside)."""
    p10, _, p90 = effect
    width = p90 - p10
    gap = max(p10 - truth, truth - p90)
    if width > 0:
        return gap / width
    return 0.0 if gap <= 0 else math.inf


def conformal_quantile(scores: Sequence[float], target: float = TARGET) -> float:
    """The split-conformal widening for `scores`: rank ceil((n + 1) * target), at least 0."""
    n = len(scores)
    rank = math.ceil((n + 1) * target)
    if n == 0 or rank > n:
        return math.inf
    return max(0.0, sorted(scores)[rank - 1])
