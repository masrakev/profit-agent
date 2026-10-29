from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.facts.model import Fact, FactKind, FactStatus, Period, Scope, Unit
from app.verifier import (
    UnknownFactReferenceError,
    ViolationKind,
    entity_references,
    fact_references,
    format_fact,
    render,
    verify,
)

PERIOD = Period.days(date(2026, 1, 1), date(2026, 2, 1))


def fact(
    value: str | None, unit: Unit = Unit.MONEY, currency: str | None = "USD", **kw: object
) -> Fact:
    fields: dict[str, object] = {
        "store_id": UUID(int=1),
        "formula_id": "revenue",
        "formula_version": 1,
        "kind": FactKind.EXACT,
        "scope": Scope.store(),
        "period": PERIOD,
        "status": FactStatus.DEFINED if value is not None else FactStatus.UNDEFINED,
        "value": Decimal(value) if value is not None else None,
        "undefined_reason": None if value is not None else "ad_spend is zero",
        "unit": unit,
        "currency": currency if unit is Unit.MONEY else None,
        "inputs_hash": "0" * 64,
    }
    fields.update(kw)
    return Fact.model_validate(fields)


# --- render ------------------------------------------------------------------------------------


def test_render_formats_each_unit() -> None:
    facts = {
        1: fact("1234.5650"),
        2: fact("-0.004"),
        3: fact("1200.5", currency="EUR"),
        4: fact("99", currency="CHF"),
        5: fact("1250", currency="JPY"),
        6: fact("1234", Unit.COUNT),
        7: fact("2.345", Unit.RATIO),
        8: fact("196.04", Unit.DAYS),
        9: fact(None, Unit.RATIO),
        10: fact(
            "1200",
            kind=FactKind.ESTIMATE,
            p10=Decimal("1000"),
            p50=Decimal("1200"),
            p90=Decimal("1500.5"),
            method="monte_carlo",
        ),
    }
    text = " | ".join(f"{{{{F{i}}}}}" for i in facts)
    assert render(text, facts) == (
        "$1,234.56 | $0.00 | €1,200.50 | 99.00 CHF | ¥1,250 | 1,234 | 2.34× | 196.0 days | n/a"
        " | $1,000.00–$1,500.50"
    )
    assert render("Revenue was {{F6}}.", facts) == "Revenue was 1,234."
    assert format_fact(fact("-12.5")) == "-$12.50"


def test_render_rejects_unknown_reference() -> None:
    with pytest.raises(UnknownFactReferenceError):
        render("{{F404}}", {})


# --- verify: allowed text ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Revenue was {{F12}} and margin {{F13}}.",
        "Contribution after ads fell to {{F1}} (see **{{F2}}**, `{{F3}}`).",
        "Between 2026-01-01 and 2026-01-31 the campaign spent {{F4}}.",
        "Recorded at 2026-10-27T14:05:00Z and 2026-10-27T14:05:00.123+02:00.",
        "In 2026, sales grew; since 2025 the store doubled down.",
        "Compared with Q4 2025 and between 2025 and 2026, nothing changed.",
        "No one ordered; one of the campaigns paused. Someone often bought it.",
        "The first campaign was paused, then the second.",
        "",
    ],
)
def test_clean_text_has_no_violations(text: str) -> None:
    assert verify(text, allowed=["Q4"]) == []


# --- verify: adversarial -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind", "literal"),
    [
        ("Revenue was $1,200 last month.", ViolationKind.CURRENCY, "$1,200"),
        ("Revenue was €1.200,50 last month.", ViolationKind.CURRENCY, "€1.200,50"),
        ("Revenue was USD 1200 last month.", ViolationKind.CURRENCY, "1200"),
        ("Revenue was 1200 dollars.", ViolationKind.CURRENCY, "1200 dollars"),
        ("Margin is 12 % lower.", ViolationKind.PERCENTAGE, "12 %"),
        ("Margin is 12% lower.", ViolationKind.PERCENTAGE, "12%"),
        ("Margin is 12 percent lower.", ViolationKind.PERCENTAGE, "12 percent"),
        ("ROAS hit 3.2x this week.", ViolationKind.MULTIPLIER, "3.2x"),
        ("A 3:1 return.", ViolationKind.RATIO, "3:1"),
        ("We sold 1.2k units.", ViolationKind.NUMBER, "1.2k"),
        ("We sold 1,200 units.", ViolationKind.NUMBER, "1,200"),
        (
            "Revenue was twelve hundred dollars.",
            ViolationKind.SPELLED_NUMBER,
            "twelve hundred dollars",
        ),
        ("We sold a dozen units.", ViolationKind.SPELLED_NUMBER, "a dozen"),
        ("Twenty-five orders were refunded.", ViolationKind.SPELLED_NUMBER, "Twenty-five"),
        ("One hundred and fifty orders.", ViolationKind.SPELLED_NUMBER, "One hundred and fifty"),
        ("Margin improved by one percent.", ViolationKind.SPELLED_NUMBER, "one percent"),
        ("Half of revenue came from ads.", ViolationKind.SPELLED_NUMBER, "Half"),
        ("Revenue was **$1,200** today.", ViolationKind.CURRENCY, "$1,200"),
        ("Revenue was `1200` today.", ViolationKind.NUMBER, "1200"),
        ("| Revenue | 1200 |", ViolationKind.NUMBER, "1200"),
        ("30. days of cover left.", ViolationKind.NUMBER, "30"),
        ("Revenue fell 1. Then rose.", ViolationKind.NUMBER, "1"),
        ("Revenue was ١٢٠٠ today.", ViolationKind.NUMBER, "١٢٠٠"),
        ("Revenue was １２００ today.", ViolationKind.NUMBER, "１２００"),
        ("Margin is ½ of revenue.", ViolationKind.NUMBER, "½"),
        ("Growth of x² observed.", ViolationKind.NUMBER, "x²"),
        ("Revenue was 1\u200b200 today.", ViolationKind.NUMBER, "1\u200b200"),
        ("Revenue {{F12}}0 is suspicious.", ViolationKind.NUMBER, "0"),
        ("Revenue {{F1２}} uses a fullwidth digit.", ViolationKind.NUMBER, "F1２"),
        ("Revenue {{ F12 }} is malformed.", ViolationKind.NUMBER, "F12"),
        ("We sold 2026 units.", ViolationKind.NUMBER, "2026"),
        ("Revenue reached $2026.", ViolationKind.CURRENCY, "$2026"),
        ("In 2026% growth.", ViolationKind.PERCENTAGE, "2026%"),
        ("Invalid date 2026-02-30 here.", ViolationKind.NUMBER, "2026-02-30"),
        ("Spend was -45.10 yesterday.", ViolationKind.NUMBER, "-45.10"),
    ],
)
def test_adversarial_numbers_are_caught(text: str, kind: ViolationKind, literal: str) -> None:
    violations = verify(text)
    assert [(v.kind, v.text) for v in violations][:1] == [(kind, literal)], violations
    v = violations[0]
    assert text[v.start : v.end] == v.text
    assert repr(literal) in v.message


def test_allowed_tokens_are_whole_matches() -> None:
    assert verify("Open 24/7 since 2025.", allowed=["24/7"]) == []
    assert [v.text for v in verify("Open 124/7.", allowed=["24/7"])] == ["124/7"]
    assert [v.text for v in verify("Q3 revenue")] == ["Q3"]


@pytest.mark.parametrize(
    ("text", "literal"),
    [
        ("Revenue doubled after the launch.", "doubled"),
        ("Ad spend tripled in a week.", "tripled"),
        ("Refunds were halved.", "halved"),
        ("Sales will double if we restock.", "double"),
        ("Orders quadrupled.", "quadrupled"),
        ("Revenue grew twice as fast.", "twice"),
        ("A threefold increase.", "threefold"),
        ("A ten-fold increase.", "ten-fold"),
        ("A 3-fold increase.", "3-fold"),
        ("Spend is 2x last week.", "2x"),
        ("Spend is 2× last week.", "2×"),
        ("Spend is 3 times higher.", "3 times"),
        ("Spend is three times higher.", "three times"),
        ("Spend is two-fold higher.", "two-fold"),
    ],
)
def test_multiplicative_claims_are_caught(text: str, literal: str) -> None:
    assert [(v.kind, v.text) for v in verify(text)] == [(ViolationKind.MULTIPLIER, literal)]


@pytest.mark.parametrize(
    "text",
    [
        "Please double-check the feed; we will double down on {{F3}}.",
        "Delivery times vary; at times stock runs out. The manifold is fine.",
    ],
)
def test_multiplier_lookalikes_are_not_flagged(text: str) -> None:
    assert verify(text) == []


def test_ordered_list_markers_are_allowed_when_sequential() -> None:
    text = "1. Revenue fell to {{F1}}.\n2. Spend rose.\n   3) Margin held.\n\n1. New list."
    assert verify(text) == []
    skipped = verify("1. Revenue fell.\n3. Spend rose.\n4. Margin held.")
    assert [(v.text, v.start) for v in skipped] == [("3", 17), ("4", 32)]
    assert [v.text for v in verify("1. Revenue fell by 12 %.")] == ["12 %"]
    assert [v.text for v in verify("1.5 is not a marker")] == ["1.5"]
    assert [v.text for v in verify("    1. indented code, not a list")] == ["1"]


def test_every_number_is_reported() -> None:
    text = "Spend $40 on Monday, $60 on Tuesday: ROAS 1.5x, margin 12 %, twelve orders."
    assert [v.text for v in verify(text)] == ["$40", "$60", "1.5x", "12 %", "twelve"]
    assert [v.kind for v in verify("A 3:1 return, up 2x.")] == [
        ViolationKind.RATIO,
        ViolationKind.MULTIPLIER,
    ]


# --- verify: properties ------------------------------------------------------------------------

SAFE_WORDS = [
    "revenue",
    "margin",
    "the",
    "campaign",
    "fell",
    "rose",
    "store",
    "ads",
    "spend",
    "product",
    "**bold**",
    "`code`",
    "-",
    "(note)",
    "one",
    "first",
    "no",
    "of",
]
safe_text = st.lists(
    st.one_of(
        st.sampled_from(SAFE_WORDS),
        st.integers(min_value=1, max_value=10**9).map(lambda n: f"{{{{F{n}}}}}"),
        st.dates(min_value=date(1900, 1, 1), max_value=date(2099, 12, 31)).map(date.isoformat),
    ),
    max_size=30,
).map(" ".join)


@st.composite
def number_literals(draw: st.DrawFn) -> str:
    value = draw(st.decimals(min_value=0, max_value=10**9, places=2, allow_nan=False))
    style = draw(st.sampled_from(["plain", "comma", "currency", "euro", "percent", "k", "ratio"]))
    plain = format(value, "f")
    return {
        "plain": plain,
        "comma": f"{value:,}",
        "currency": f"${value:,}",
        "euro": "€" + f"{value:,}".replace(",", "_").replace(".", ",").replace("_", "."),
        "percent": f"{plain} %",
        "k": f"{value / 1000:.1f}k",
        "ratio": f"{plain}x",
    }[style]


@given(safe_text)
def test_property_references_dates_and_words_never_violate(text: str) -> None:
    assert verify(text) == []


@given(safe_text, number_literals(), safe_text)
def test_property_any_inserted_number_is_caught(before: str, literal: str, after: str) -> None:
    text = f"{before} {literal} {after}"
    start = len(before) + 1
    assume(not (len(literal) == 4 and literal.isdigit()))  # a bare year may be allowed in context
    hits = [v for v in verify(text) if v.start < start + len(literal) and v.end > start]
    assert hits, (text, literal)


@settings(max_examples=300)
@given(st.text())
def test_property_never_crashes_and_a_trailing_digit_is_always_caught(text: str) -> None:
    verify(text)
    assert verify(text + " 7")


@given(st.decimals(min_value=-(10**12), max_value=10**12, places=4, allow_nan=False))
def test_property_rendered_values_would_be_caught_if_copied(value: Decimal) -> None:
    rendered = render("Revenue was {{F1}}.", {1: fact(str(value))})
    assert "{{" not in rendered
    assert verify(rendered)  # a model copying rendered output is still flagged


ENTITY = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"


def test_entity_references_are_allowed_and_extracted() -> None:
    text = f"{{{{E:product:{ENTITY}}}}} lost margin while {{{{E:store}}}} grew ({{{{F12}}}})."
    assert verify(text) == []
    assert entity_references(text) == {f"product:{ENTITY}", "store"}
    assert fact_references(text) == {12}


@pytest.mark.parametrize(
    "text",
    [
        f"{{{{E:product:{ENTITY.upper()}}}}}",  # canonical lower-case only
        "{{E:store:1b4e28ba-2fa1-11d2-883f-0016d3cca427}}",  # the store has no id
        f"{{{{E:order:{ENTITY}}}}}",  # unknown kind
        f"{{{{E:product:{ENTITY}}}}}7",  # a digit right after a reference is still a number
        f"product {ENTITY}",  # a bare id is a run of numbers
    ],
)
def test_malformed_entity_references_are_still_flagged(text: str) -> None:
    assert verify(text)
