"""Golden tests: hand-computed scenarios the fact engine must match exactly (or to the cent where
the formula involves a division). Expected values are derived in the comments."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine

from app.db import tenant_transaction
from app.domain.models import OrderStatus
from app.domain.money import round_for_display
from app.facts.engine import FactEngine
from app.facts.model import Fact, FactStatus, Period, Scope
from tests.builders import Scenario
from tests.conftest import create_store

pytestmark = pytest.mark.db

D = Decimal
JAN = Period.days(date(2026, 1, 1), date(2026, 2, 1))
FEB = Period.days(date(2026, 2, 1), date(2026, 3, 1))


def facts_for(
    engine: Engine, store_id: UUID, period: Period, scope: Scope, *ids: str
) -> dict[str, Fact]:
    with tenant_transaction(engine, store_id) as conn:
        fe = FactEngine(conn, store_id)
        return {fid: fe.fact(fid, scope, period) for fid in ids}


def values(facts: dict[str, Fact]) -> dict[str, Decimal | None]:
    return {k: f.value for k, f in facts.items()}


def cents(value: Decimal | None) -> Decimal:
    assert value is not None
    return round_for_display(value, 2)


def test_golden_1_single_order_margins(app_engine: Engine) -> None:
    # 3 × $20.00 with a $6.00 discount, $4.32 tax, $5.99 shipping, $2.00 payment fee.
    # revenue = 60.00 − 6.00 = 54.00 (tax and shipping excluded)
    # cogs = 3 × 8.00 = 24.00; fees = 3 × 1.50 + 2.00 = 6.50
    # gross_margin = 54.00 − 24.00 = 30.00; contribution_margin = 54.00 − 24.00 − 6.50 − 0 = 23.50
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        a = s.product("20.00", "8.00", "1.50")
        s.order(
            "2026-01-10T10:00:00",
            [(a, 3, "20.00", "8.00", "1.50")],
            payment_fee="2.00",
            shipping="5.99",
            discounts=["6.00"],
            taxes=["4.32"],
        )
    ids = ("revenue", "units", "cogs", "fees", "refunds", "gross_margin", "contribution_margin")
    for scope in (Scope.store(), Scope.product(a)):
        assert values(facts_for(app_engine, store, JAN, scope, *ids)) == {
            "revenue": D("54.00"),
            "units": D(3),
            "cogs": D("24.00"),
            "fees": D("6.50"),
            "refunds": D(0),
            "gross_margin": D("30.00"),
            "contribution_margin": D("23.50"),
        }


def test_golden_2_period_boundaries_refund_dates_and_cancellations(app_engine: Engine) -> None:
    # Jan: one paid order 2 × $15.00 at 23:59:59 on Jan 31 → revenue 30.00.
    #      a cancelled order (5 × $15.00) is excluded.
    #      an order at exactly Feb 1 00:00:00 belongs to Feb (half-open periods): 1 × $15.00.
    # Feb: refund of $15.00 on Feb 2 for the January line → refunds counted by refund date.
    # Jan CM = 30.00 − 2 × 6.00 = 18.00
    # Feb CM = 15.00 − 6.00 − 15.00 = −6.00
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        p = s.product("15.00", "6.00", "0")
        (jan_line,) = s.order("2026-01-31T23:59:59", [(p, 2, "15.00", "6.00", "0")])
        s.order("2026-01-15T12:00:00", [(p, 5, "15.00", "6.00", "0")], status=OrderStatus.CANCELLED)
        s.order("2026-02-01T00:00:00", [(p, 1, "15.00", "6.00", "0")])
        s.refund(jan_line, "2026-02-02T09:00:00", "15.00")
    ids = ("revenue", "units", "refunds", "contribution_margin")
    assert values(facts_for(app_engine, store, JAN, Scope.store(), *ids)) == {
        "revenue": D("30.00"),
        "units": D(2),
        "refunds": D(0),
        "contribution_margin": D("18.00"),
    }
    assert values(facts_for(app_engine, store, FEB, Scope.store(), *ids)) == {
        "revenue": D("15.00"),
        "units": D(1),
        "refunds": D("15.00"),
        "contribution_margin": D("-6.00"),
    }


def test_golden_3_payment_fee_allocation_reconciles(app_engine: Engine) -> None:
    # One order: A 1 × $30.00 (unit fee 1.00) and B 2 × $5.00 (unit fee 0.50); payment fee 1.01.
    # Allocation pro rata to net 30 : 10 → A 0.7575, B 0.2525 (sums to 1.01 exactly).
    # fees A = 1.00 + 0.7575 = 1.7575; fees B = 2 × 0.50 + 0.2525 = 1.2525; store = 3.01.
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        a = s.product("30.00", "10.00", "1.00")
        b = s.product("5.00", "2.00", "0.50")
        s.order(
            "2026-01-05T08:00:00",
            [(a, 1, "30.00", "10.00", "1.00"), (b, 2, "5.00", "2.00", "0.50")],
            payment_fee="1.01",
        )
    fees = {
        "a": facts_for(app_engine, store, JAN, Scope.product(a), "fees")["fees"].value,
        "b": facts_for(app_engine, store, JAN, Scope.product(b), "fees")["fees"].value,
        "store": facts_for(app_engine, store, JAN, Scope.store(), "fees")["fees"].value,
    }
    assert fees == {"a": D("1.7575"), "b": D("1.2525"), "store": D("3.01")}
    assert cents(fees["a"]) == D("1.76")
    assert cents(fees["b"]) == D("1.25")


def _ads_store(app_engine: Engine) -> tuple[UUID, UUID, UUID]:
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        a = s.product("50.00", "20.00", "2.00")
        b = s.product("30.00", "10.00", "1.00")
        a_lines = [
            s.order(
                f"2026-01-{day:02d}T12:00:00",
                [(a, 1, "50.00", "20.00", "2.00")],
                payment_fee="1.75",
            )[0]
            for day in (3, 4, 10, 11)
        ]
        for day in (5, 6):
            s.order(
                f"2026-01-{day:02d}T12:00:00",
                [(b, 1, "30.00", "10.00", "1.00")],
                payment_fee="1.00",
            )
        s.refund(a_lines[0], "2026-01-20T10:00:00", "50.00")
        campaign = s.campaign([a])
        s.ad_day(campaign, "2026-01-05", "40.00", 2, "100.00")
        s.ad_day(campaign, "2026-01-06", "60.00", 1, "50.00")
        s.ad_day(campaign, "2026-02-01", "999.00", 9, "999.00")  # outside January
        s.fixed_cost("310.00", "2026-01-01", "2026-02-01")
    return store, campaign, a


def test_golden_4_ads_and_profit(app_engine: Engine) -> None:
    # Store, January:
    #   revenue = 4 × 50 + 2 × 30 = 260.00; cogs = 4 × 20 + 2 × 10 = 100.00
    #   fees = 4 × (2.00 + 1.75) + 2 × (1.00 + 1.00) = 19.00; refunds = 50.00
    #   contribution_margin = 260 − 100 − 19 − 50 = 91.00
    #   ad_spend = 40 + 60 = 100.00 (Feb 1 excluded); attributed_revenue = 150.00; purchases = 3
    #   contribution_after_ads = 91 − 100 = −9.00; fixed_costs = 310.00; net_profit = −319.00
    # Campaign (promotes A):
    #   promoted revenue 200.00, cogs 80.00, fees 15.00, refunds 50.00 → promoted CM 55.00
    #   attributed_contribution = 150 × 55 / 200 = 41.25
    #   roas = 150 / 100 = 1.5; poas = 41.25 / 100 = 0.4125; cpa = 100 / 3 = 33.33…
    store, campaign, _ = _ads_store(app_engine)
    s = facts_for(
        app_engine,
        store,
        JAN,
        Scope.store(),
        "revenue",
        "cogs",
        "fees",
        "refunds",
        "contribution_margin",
        "ad_spend",
        "attributed_revenue",
        "attributed_purchases",
        "attributed_contribution",
        "contribution_after_ads",
        "fixed_costs",
        "net_profit",
        "roas",
        "poas",
        "cpa",
    )
    assert values(s) | {"cpa": cents(s["cpa"].value)} == {
        "revenue": D("260.00"),
        "cogs": D("100.00"),
        "fees": D("19.00"),
        "refunds": D("50.00"),
        "contribution_margin": D("91.00"),
        "ad_spend": D("100.00"),
        "attributed_revenue": D("150.00"),
        "attributed_purchases": D(3),
        "attributed_contribution": D("41.25"),
        "contribution_after_ads": D("-9.00"),
        "fixed_costs": D("310.00"),
        "net_profit": D("-319.00"),
        "roas": D("1.5"),
        "poas": D("0.4125"),
        "cpa": D("33.33"),
    }
    c = facts_for(
        app_engine,
        store,
        JAN,
        Scope.campaign(campaign),
        "promoted_revenue",
        "promoted_contribution_margin",
        "attributed_contribution",
        "roas",
        "poas",
        "ad_spend",
    )
    assert values(c) == {
        "promoted_revenue": D("200.00"),
        "promoted_contribution_margin": D("55.00"),
        "attributed_contribution": D("41.25"),
        "roas": D("1.5"),
        "poas": D("0.4125"),
        "ad_spend": D("100.00"),
    }


def test_golden_7_campaign_profit_mer_attribution_and_refund_rates(app_engine: Engine) -> None:
    # Same store as golden 4 (January):
    #   campaign_profit = attributed_contribution − ad_spend = 41.25 − 100.00 = −58.75
    #   mer = revenue ÷ ad_spend = 260 / 100 = 2.6
    #   attribution_ratio (campaign) = 150 / promoted revenue 200 = 0.75
    #   attribution_ratio (store) = 150 / 260 = 0.576923… → 0.5769 to 4 places
    #   refund_rate (store) = 50 / 260 = 0.192307… → 0.1923
    #   refund_rate (A) = 50 / 200 = 0.25; refund_rate (B) = 0 / 60 = 0
    store, campaign, a = _ads_store(app_engine)
    c = facts_for(
        app_engine, store, JAN, Scope.campaign(campaign), "campaign_profit", "attribution_ratio"
    )
    assert values(c) == {"campaign_profit": D("-58.75"), "attribution_ratio": D("0.75")}
    s = facts_for(app_engine, store, JAN, Scope.store(), "mer", "attribution_ratio", "refund_rate")
    assert s["mer"].value == D("2.6")
    assert round_for_display(s["attribution_ratio"].value or D(0), 4) == D("0.5769")
    assert round_for_display(s["refund_rate"].value or D(0), 4) == D("0.1923")
    assert facts_for(app_engine, store, JAN, Scope.product(a), "refund_rate")[
        "refund_rate"
    ].value == D("0.25")
    with tenant_transaction(app_engine, store) as conn:
        b = conn.exec_driver_sql(
            "SELECT id FROM products WHERE price = 30 AND store_id = %(s)s", {"s": store}
        ).scalar_one()
    assert facts_for(app_engine, store, JAN, Scope.product(b), "refund_rate")[
        "refund_rate"
    ].value == D(0)

    # Zero denominators: no sales, no ad spend, no promoted sales in March.
    march = Period.days(date(2026, 3, 1), date(2026, 4, 1))
    empty = facts_for(app_engine, store, march, Scope.store(), "mer", "refund_rate")
    assert empty["mer"].undefined_reason == "ad_spend is zero"
    assert empty["refund_rate"].undefined_reason == "revenue is zero"
    feb = Period.days(date(2026, 2, 1), date(2026, 3, 1))
    ratio = facts_for(app_engine, store, feb, Scope.campaign(campaign), "attribution_ratio")
    assert ratio["attribution_ratio"].undefined_reason == "promoted_revenue is zero"


def test_golden_5_fixed_cost_proration(app_engine: Engine) -> None:
    # Period Jan 22 – Feb 8 (17 days: 10 in January, 7 in February).
    #   item 1: 310.00 over January (31 days, 10.00/day) → 10 × 10 = 100.00
    #   item 2: 280.00 over February (28 days, 10.00/day) → 7 × 10 = 70.00
    #   item 3: 900.00 over Jan–Mar (90 days, 10.00/day) → 17 × 10 = 170.00
    #   total = 340.00
    # Period Jan 1 – Jan 11 for a 100.00 January item alone: 100 × 10 / 31 = 32.2580… → $32.26
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        s.fixed_cost("310.00", "2026-01-01", "2026-02-01")
        s.fixed_cost("280.00", "2026-02-01", "2026-03-01")
        s.fixed_cost("900.00", "2026-01-01", "2026-04-01")
        s.fixed_cost("10.00", "2025-12-01", "2026-01-01")  # before the period: excluded
    period = Period.days(date(2026, 1, 22), date(2026, 2, 8))
    assert facts_for(app_engine, store, period, Scope.store(), "fixed_costs")[
        "fixed_costs"
    ].value == D("340")

    other = create_store(app_engine)
    with tenant_transaction(app_engine, other) as conn:
        Scenario(conn, other).fixed_cost("100.00", "2026-01-01", "2026-02-01")
    value = facts_for(
        app_engine,
        other,
        Period.days(date(2026, 1, 1), date(2026, 1, 11)),
        Scope.store(),
        "fixed_costs",
    )["fixed_costs"].value
    assert cents(value) == D("32.26")


def test_golden_6_inventory_cover_days(app_engine: Engine) -> None:
    # Snapshots: Jan 30 → 50 units, Jan 31 → 42 units, Feb 1 → 0 (after the period end).
    # Units sold in [Jan 4, Feb 1): 3 orders × 2 = 6 (the Jan 3 order is outside the window).
    # cover = 42 ÷ (6 / 28) = 196 days.
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        p = s.product("10.00", "4.00", "0")
        s.stock(p, "2026-01-30", 50)
        s.stock(p, "2026-01-31", 42)
        s.stock(p, "2026-02-01", 0)
        for day in ("2026-01-03", "2026-01-04", "2026-01-15", "2026-01-31"):
            s.order(f"{day}T23:00:00", [(p, 2, "10.00", "4.00", "0")])
    f = facts_for(app_engine, store, JAN, Scope.product(p), "units_on_hand", "inventory_cover_days")
    assert f["units_on_hand"].value == D(42)
    assert f["inventory_cover_days"].value == D(196)


def test_undefined_facts_carry_reasons(app_engine: Engine) -> None:
    # No ads and no sales: ratios divide by zero → undefined with a reason, never an exception.
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        p = s.product("10.00", "4.00", "0")
        s.stock(p, "2026-01-10", 5)
        idle = s.product("10.00", "4.00", "0")
        c = s.campaign([p])
        s.ad_day(c, "2026-01-10", "25.00", 0, "40.00")  # attributed revenue but no promoted sales
        quiet = s.campaign([idle])  # no metrics in January: nothing attributed
    f = facts_for(app_engine, store, JAN, Scope.store(), "roas", "cpa", "attributed_contribution")
    assert f["roas"].status is FactStatus.DEFINED
    assert f["roas"].value == D("1.6")
    assert f["cpa"].status is FactStatus.UNDEFINED
    assert f["cpa"].undefined_reason == "attributed_purchases is zero"
    assert f["attributed_contribution"].status is FactStatus.UNDEFINED
    assert "promoted_revenue is zero" in (f["attributed_contribution"].undefined_reason or "")

    cover = facts_for(app_engine, store, JAN, Scope.product(p), "inventory_cover_days")
    assert cover["inventory_cover_days"].undefined_reason == (
        "units sold in the trailing 28 days is zero"
    )
    no_stock = facts_for(app_engine, store, JAN, Scope.product(idle), "inventory_cover_days")
    assert "no inventory snapshot" in (no_stock["inventory_cover_days"].undefined_reason or "")
    # Zero attributed revenue attributes zero contribution, even with no promoted sales.
    q = facts_for(app_engine, store, JAN, Scope.campaign(quiet), "attributed_contribution", "poas")
    assert q["attributed_contribution"].value == D(0)
    assert q["poas"].undefined_reason == "ad_spend is zero"

    empty = create_store(app_engine)
    e = facts_for(app_engine, empty, JAN, Scope.store(), "roas", "poas", "attributed_contribution")
    assert e["roas"].undefined_reason == "ad_spend is zero"
    assert e["poas"].undefined_reason == "ad_spend is zero"
    assert e["attributed_contribution"].value == D(0)


def test_foreign_currency_rows_make_money_facts_undefined(app_engine: Engine) -> None:
    store = create_store(app_engine, currency="EUR")
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store, currency="EUR")
        p = s.product("10.00", "4.00", "0")
        s.order("2026-01-05T10:00:00", [(p, 1, "10.00", "4.00", "0")])
        s.order("2026-01-06T10:00:00", [(p, 1, "10.00", "4.00", "0")], currency="USD")
    f = facts_for(app_engine, store, JAN, Scope.store(), "revenue", "units", "gross_margin")
    assert f["revenue"].status is FactStatus.UNDEFINED
    assert "USD differ from store currency EUR" in (f["revenue"].undefined_reason or "")
    assert f["units"].value == D(2)
    assert f["gross_margin"].undefined_reason is not None
    assert f["gross_margin"].undefined_reason.startswith("revenue is undefined")
