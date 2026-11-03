"""Did the prediction hold? A measured effect against the range predicted for it.

The measured effect's most likely value (P50) is compared with the predicted P10 to P90: inside,
the prediction held; above or below, it missed in that direction. The effect is on net profit, so
above is better than predicted. One definition, used by the trust ledger to count the predictions
that held and shown with every measured outcome.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Any


class Consistency(StrEnum):
    INSIDE = "inside"
    ABOVE = "above"
    BELOW = "below"


WORDS = {
    Consistency.INSIDE: "As predicted: the measured effect is within the predicted range.",
    Consistency.ABOVE: "Better than predicted: the measured effect is above the predicted range.",
    Consistency.BELOW: "Worse than predicted: the measured effect is below the predicted range.",
}


def consistency(payload: dict[str, Any]) -> Consistency | None:
    """The verdict of an outcome's payload (its `predicted` and measured `effect` quantiles), or
    None when it has no prediction or was not measured."""
    predicted, effect = payload.get("predicted"), payload.get("effect")
    if not predicted or not effect:
        return None
    measured = Decimal(str(effect["p50"]))
    low, high = Decimal(str(predicted["p10"])), Decimal(str(predicted["p90"]))
    if measured > high:
        return Consistency.ABOVE
    if measured < low:
        return Consistency.BELOW
    return Consistency.INSIDE


def verdict_text(found: Consistency | None) -> str | None:
    return None if found is None else WORDS[found]
