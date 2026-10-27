"""Render `{{F<id>}}` references into display values. Rounding happens here and only here."""

import re
from collections.abc import Mapping
from decimal import Decimal

from app.domain.money import round_for_display
from app.facts.model import Fact, FactKind, Unit

REFERENCE = re.compile(r"\{\{F([0-9]+)\}\}")
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
UNDEFINED_TEXT = "n/a"


class UnknownFactReferenceError(KeyError):
    pass


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
