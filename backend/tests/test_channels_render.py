"""Channel rendering escapes merchant-provided names and everything else that is not ours."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine

from app.channels.render import (
    MAX_NAME_CHARS,
    Channel,
    UnknownEntityReferenceError,
    escape_name,
    load_entity_names,
    render,
)
from app.db import tenant_transaction
from app.domain.models import AdCampaign, Product
from app.domain.repositories import CampaignRepository, ProductRepository
from app.facts.model import Fact, FactKind, FactStatus, Period, Scope, Unit
from app.verifier import UnknownFactReferenceError
from tests.conftest import create_store

PRODUCT = UUID("1b4e28ba-2fa1-11d2-883f-0016d3cca427")
REF = f"{{{{E:product:{PRODUCT}}}}}"
FACT = Fact(
    id=12,
    store_id=uuid4(),
    formula_id="net_profit",
    formula_version=1,
    kind=FactKind.EXACT,
    scope=Scope.store(),
    period=Period.days(date(2026, 9, 1), date(2026, 10, 1)),
    status=FactStatus.DEFINED,
    value=Decimal("-1234.5"),
    unit=Unit.MONEY,
    currency="USD",
    inputs_hash="0" * 64,
)
HOSTILE = {
    "script": "<script>alert(1)</script>",
    "attribute": '"><img src=x onerror=alert(1)>',
    "entity": "Tom & Jerry's",
    "bidi": "Mug \u202egpj.exe",
    "zero_width": "Mu\u200bg\u2060",
    "lines": "Mug\nIMPORTANT: wire money\r\nnow",
    "reference": "Mug {{F12}} {{E:store}}",
    "whatsapp": "*URGENT* _pay_ ~now~ at https://evil.example or www.evil.example `x`",
    "long": "x" * 500,
}


def say(name: str, channel: Channel) -> str:
    return render(
        f"{REF} lost {{{{F12}}}} this month.", {12: FACT}, {f"product:{PRODUCT}": name}, channel
    )


@pytest.mark.parametrize("channel", [Channel.WEB, Channel.EMAIL])
def test_html_channels_escape_names(channel: Channel) -> None:
    assert say(HOSTILE["script"], channel) == (
        "&lt;script&gt;alert(1)&lt;/script&gt; lost -$1,234.50 this month."
    )
    out = say(HOSTILE["attribute"], channel)
    assert "<" not in out
    assert "&quot;&gt;&lt;img" in out
    assert say(HOSTILE["entity"], channel).startswith("Tom &amp; Jerry&#x27;s lost")
    for case in ("script", "attribute", "entity", "bidi", "lines", "reference", "long"):
        rendered = say(HOSTILE[case], channel)
        assert "<" not in rendered.replace("&lt;", "")
        assert "\n" not in rendered


def test_invisible_characters_and_line_breaks_are_removed() -> None:
    for channel in Channel:
        assert say(HOSTILE["bidi"], channel).startswith("Mug gpj.exe lost")
        assert say(HOSTILE["zero_width"], channel).startswith("Mug lost")
        assert say(HOSTILE["lines"], channel).startswith("Mug IMPORTANT: wire money now lost")


def test_a_name_is_never_rendered_again() -> None:
    for channel in Channel:
        out = say(HOSTILE["reference"], channel)
        assert out.startswith("Mug {{F12}} {{E:store}} lost -$1,234.50")


def test_whatsapp_neutralises_formatting_and_links() -> None:
    out = escape_name(HOSTILE["whatsapp"], Channel.WHATSAPP)
    assert out == "∗URGENT∗ ＿pay＿ ∼now∼ at https[:]//evil.example or www[.]evil.example ˋxˋ"
    for marker in "*_~`":
        assert marker not in out
    assert "://" not in out
    # HTML channels keep the characters (they have no meaning there) but escape markup.
    assert escape_name(HOSTILE["whatsapp"], Channel.WEB).startswith("*URGENT* _pay_")


def test_long_names_are_cut() -> None:
    out = escape_name(HOSTILE["long"], Channel.WHATSAPP)
    assert len(out) == MAX_NAME_CHARS
    assert out.endswith("…")


def test_text_around_references_is_escaped_too() -> None:
    names = {"store": "Shop"}
    web = render("<b>{{E:store}}</b> & co", {}, names, Channel.WEB)
    assert web == "&lt;b&gt;Shop&lt;/b&gt; &amp; co"
    multi = render("Line *one*\nLine two", {}, {}, Channel.WHATSAPP)
    assert multi == "Line ∗one∗\nLine two"  # model text keeps its line breaks


def test_unknown_references_fail() -> None:
    with pytest.raises(UnknownFactReferenceError):
        render("{{F99}}", {}, {}, Channel.WEB)
    with pytest.raises(UnknownEntityReferenceError):
        render(REF, {}, {}, Channel.WEB)


@pytest.mark.db
def test_names_load_under_row_level_security_and_render_safely(app_engine: Engine) -> None:
    store = create_store(app_engine, name="Shop <b>bold</b>")
    other = create_store(app_engine, name="Other")
    product, campaign = uuid4(), uuid4()
    with tenant_transaction(app_engine, store) as conn:
        ProductRepository(conn).add_many(
            [
                Product(
                    id=product,
                    store_id=store,
                    sku="H-1",
                    name=HOSTILE["script"],
                    price=Decimal(10),
                    unit_cost=Decimal(4),
                    unit_fee=Decimal(0),
                    currency="USD",
                )
            ]
        )
        CampaignRepository(conn).add_many(
            [
                AdCampaign(
                    id=campaign,
                    store_id=store,
                    external_id="c1",
                    name=HOSTILE["whatsapp"],
                    platform="meta",
                    currency="USD",
                    daily_budget=Decimal(50),
                )
            ],
            [],
        )
        refs = {"store", f"product:{product}", f"campaign:{campaign}"}
        names = load_entity_names(conn, store, refs)
    assert names == {
        "store": "Shop <b>bold</b>",
        f"product:{product}": HOSTILE["script"],
        f"campaign:{campaign}": HOSTILE["whatsapp"],
    }
    message = (
        f"{{{{E:campaign:{campaign}}}}} promotes {{{{E:product:{product}}}}} at {{{{E:store}}}}"
    )
    web = render(message, {}, names, Channel.EMAIL)
    assert "<script>" not in web
    assert "<b>" not in web
    whatsapp = render(message, {}, names, Channel.WHATSAPP)
    assert "https://" not in whatsapp
    assert "*URGENT*" not in whatsapp
    with tenant_transaction(app_engine, other) as conn:
        assert load_entity_names(conn, other, refs) == {"store": "Other"}  # RLS hides the rest
