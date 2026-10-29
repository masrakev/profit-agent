"""Verdict on an owner's intent, decided by code from simulated ranges (ADR 0015).

The intent and its variants (the same kind of change at other sizes or durations) are simulated
against doing nothing. With `floor` the store's materiality over the horizon, a scenario is
*good* when its net-profit change has P10 >= -floor (the downside stays within materiality) and
P50 > 0 (it beats doing nothing at the median).

- go: the intent is good, and no good variant beats its median by more than the floor;
- adjust: a good variant exists and either the intent is not good or the variant beats it by
  more than the floor (the answer recommends that variant);
- avoid: neither the intent nor any variant is good.

A scenario the twin cannot simulate gives no verdict (the answer abstains).
"""

from dataclasses import dataclass
from enum import StrEnum

from app.twin.model import Simulation


class Verdict(StrEnum):
    GO = "go"
    ADJUST = "adjust"
    AVOID = "avoid"


@dataclass(frozen=True)
class Judged:
    verdict: Verdict | None
    reason: str
    adjusted: Simulation | None = None  # the variant an `adjust` recommends


def _good(sim: Simulation, floor: float) -> bool:
    r = sim.change.get("net_profit")
    return r is not None and r.p10 >= -floor and r.p50 > 0


def _p50(sim: Simulation) -> float:
    return sim.change["net_profit"].p50


def judge(intent: Simulation, variants: list[Simulation], floor: float) -> Judged:
    if intent.undefined_reason or "net_profit" not in intent.change:
        return Judged(None, f"the twin cannot simulate it: {intent.undefined_reason}")
    good = [v for v in variants if not v.undefined_reason and _good(v, floor)]
    best = max(good, key=_p50) if good else None
    if _good(intent, floor):
        if best is not None and _p50(best) > _p50(intent) + floor:
            return Judged(Verdict.ADJUST, "a variant gains materially more", best)
        return Judged(Verdict.GO, "the median gain is positive and the downside within the floor")
    if best is not None:
        return Judged(Verdict.ADJUST, "a variant is worth doing where the intent is not", best)
    if _p50(intent) <= 0:
        return Judged(Verdict.AVOID, "no version of the change beats doing nothing at the median")
    return Judged(Verdict.AVOID, "the downside is beyond the materiality floor in every version")
