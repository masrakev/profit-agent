"""Render `{{F<id>}}` references into display values. Rounding happens here and only here.

Entity references `{{E:<kind>[:<uuid>]}}` name a store, product or campaign without writing
its name or id in model text; they are rendered from the database, never from the model."""

import re
from collections.abc import Mapping
from decimal import Decimal

from app.domain.money import round_for_display
from app.facts.model import Fact, FactKind, Unit

REFERENCE = re.compile(r"\{\{F([0-9]+)\}\}")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ENTITY_REFERENCE = re.compile(r"\{\{E:(store|(?:product|campaign):" + _UUID + r")\}\}")
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
UNDEFINED_TEXT = "n/a"


class UnknownFactReferenceError(KeyError):
    pass


def fact_references(text: str) -> set[int]:
    return {int(m.group(1)) for m in REFERENCE.finditer(text)}


def entity_references(text: str) -> set[str]:
    """Referenced entities as `store`, `product:<uuid>` or `campaign:<uuid>`."""
    return {m.group(1) for m in ENTITY_REFERENCE.finditer(text)}


def format_value(value: Decimal, unit: Unit, currency: str | None) -> str:
    if unit is Unit.MONEY:
        amount = round_for_display(abs(value), 0 if currency == "JPY" else 2)
        sign = "-" if value < 0 and amount != 0 else ""
        symbol = CURRENCY_SYMBOLS.get(currency or "")
        if symbol:
            return f"{sign}{symbol}{amount:,}"
        return f"{sign}{amount:,} {currency}"
    if unit is Unit.COUNT:
        return f"{round_for_display(value, 0):,}"
    if unit is Unit.RATIO:
        return f"{round_for_display(value, 2):,}×"
    return f"{round_for_display(value, 1):,} days"


def format_fact(fact: Fact) -> str:
    if not fact.is_defined:
        return UNDEFINED_TEXT
    if fact.kind is FactKind.ESTIMATE:
        assert fact.p10 is not None
        assert fact.p90 is not None
        low = format_value(fact.p10, fact.unit, fact.currency)
        high = format_value(fact.p90, fact.unit, fact.currency)
        return f"{low}–{high}"
    assert fact.value is not None
    return format_value(fact.value, fact.unit, fact.currency)


# --- short texts for screens -------------------------------------------------------------------
# The exact text above is what answers cite and what the proof sheet shows. Screens also get a
# short one: money in whole units, a range as "low to high", and a change with its sign
# ("+$613 to +$654"). Rounding happens here too, and only here.

MINUS = "−"


def _short_magnitude(value: Decimal, unit: Unit, currency: str | None) -> tuple[Decimal, str]:
    """The rounded size of `value` and its text, without a sign."""
    size = abs(value)
    if unit is Unit.MONEY:
        amount = round_for_display(size, 0)
        if amount == 0 and currency != "JPY" and round_for_display(size, 2) != 0:
            amount = round_for_display(size, 2)  # under one unit: the cents, rather than "$0"
        symbol = CURRENCY_SYMBOLS.get(currency or "")
        return amount, f"{symbol}{amount:,}" if symbol else f"{amount:,} {currency}"
    places = {Unit.COUNT: 0, Unit.RATIO: 2, Unit.DAYS: 1}[unit]
    amount = round_for_display(size, places)
    return amount, format_value(amount, unit, currency)


def display_value(value: Decimal, unit: Unit, currency: str | None, *, signed: bool = False) -> str:
    """A value's short text: "$17,572", "−$40"; with `signed` (a change), "+$613" too."""
    amount, text = _short_magnitude(value, unit, currency)
    if amount == 0:
        return text
    if value < 0:
        return f"{MINUS}{text}"
    return f"+{text}" if signed else text


def display_quantiles(fact: Fact, *, signed: bool) -> tuple[str, str, str] | None:
    """An estimate's P10, P50 and P90 as short texts."""
    if not fact.is_defined or fact.kind is not FactKind.ESTIMATE:
        return None
    assert fact.p10 is not None
    assert fact.p50 is not None
    assert fact.p90 is not None
    return (
        display_value(fact.p10, fact.unit, fact.currency, signed=signed),
        display_value(fact.p50, fact.unit, fact.currency, signed=signed),
        display_value(fact.p90, fact.unit, fact.currency, signed=signed),
    )


def exact_quantiles(fact: Fact) -> tuple[str, str, str] | None:
    """An estimate's P10, P50 and P90 as exact texts (the proof sheet's)."""
    if not fact.is_defined or fact.kind is not FactKind.ESTIMATE:
        return None
    assert fact.p10 is not None
    assert fact.p50 is not None
    assert fact.p90 is not None
    return (
        format_value(fact.p10, fact.unit, fact.currency),
        format_value(fact.p50, fact.unit, fact.currency),
        format_value(fact.p90, fact.unit, fact.currency),
    )


def display_fact(fact: Fact, *, signed: bool = False) -> str:
    """A fact's short text: "$17,572"; an estimate as its range, "+$613 to +$654"."""
    if not fact.is_defined:
        return UNDEFINED_TEXT
    quantiles = display_quantiles(fact, signed=signed)
    if quantiles is not None:
        low, _, high = quantiles
        return low if low == high else f"{low} to {high}"
    assert fact.value is not None
    return display_value(fact.value, fact.unit, fact.currency, signed=signed)


def render(text: str, facts: Mapping[int, Fact]) -> str:
    """Replace every `{{F<id>}}` with its formatted value. Unknown ids raise; estimates render
    as their P10–P90 range, undefined facts as "n/a"."""

    def substitute(match: re.Match[str]) -> str:
        fact_id = int(match.group(1))
        fact = facts.get(fact_id)
        if fact is None:
            raise UnknownFactReferenceError(f"F{fact_id}")
        return format_fact(fact)

    return REFERENCE.sub(substitute, text)
