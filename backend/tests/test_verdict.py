"""Did the prediction hold: the measured effect's P50 against the predicted P10 to P90."""

from app.causal.verdict import Consistency, consistency, verdict_text

PREDICTED = {"p10": "100.00", "p50": "150.00", "p90": "200.00"}


def outcome(p50: str) -> dict[str, object]:
    return {"predicted": PREDICTED, "effect": {"p10": "0", "p50": p50, "p90": "400"}}


def test_inside_above_or_below_the_predicted_range() -> None:
    assert consistency(outcome("150.00")) is Consistency.INSIDE
    assert consistency(outcome("100.00")) is Consistency.INSIDE  # the bounds are inside
    assert consistency(outcome("200.00")) is Consistency.INSIDE
    assert consistency(outcome("200.01")) is Consistency.ABOVE
    assert consistency(outcome("-35.50")) is Consistency.BELOW


def test_no_verdict_without_a_prediction_or_a_measure() -> None:
    assert consistency({"effect": {"p10": "1", "p50": "2", "p90": "3"}}) is None
    assert consistency({"predicted": PREDICTED}) is None
    assert consistency({"predicted": None, "effect": None}) is None


def test_the_verdict_in_words() -> None:
    assert verdict_text(Consistency.INSIDE) == (
        "As predicted: the measured effect is within the predicted range."
    )
    assert str(verdict_text(Consistency.ABOVE)).startswith("Better than predicted")
    assert str(verdict_text(Consistency.BELOW)).startswith("Worse than predicted")
    assert verdict_text(None) is None
