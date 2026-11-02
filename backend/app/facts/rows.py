"""The rows behind a base fact, each with its date and its amount, for the proof sheet.

A base fact sums one expression over the rows its lineage names (`app.facts.sql`); the same
expression gives each row's part, so a fact's rows add up to it (a test holds every view to
that). Rows are read under the store's row-level security, in date order, a page at a time.
Each source also says how recent its data is ("data up to").
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.facts.model import Fact, Unit

_LINES = (
    "FROM order_lines ol JOIN orders o ON o.store_id = ol.store_id AND o.id = ol.order_id "
    "WHERE ol.store_id = :s AND ol.id = ANY(:ids)"
)
_LINE_DAY = "(o.ordered_at AT TIME ZONE 'UTC')::date"
_REFUNDS = "FROM refunds r WHERE r.store_id = :s AND r.id = ANY(:ids)"
_REFUND_DAY = "(r.refunded_at AT TIME ZONE 'UTC')::date"
_METRICS = "FROM ad_metrics_daily m WHERE m.store_id = :s AND m.id = ANY(:ids)"
SHOPIFY, META = "Shopify", "Meta Ads"


@dataclass(frozen=True)
class RowView:
    table: str
    source: str  # where the rows come from, in words
    alias: str
    from_where: str  # filters by the store (:s) and the lineage's ids (:ids)
    amount: str  # each row's part of the fact (:start and :end are the fact's period)
    day: str  # each row's date
    unit: Unit


def _lines(amount: str, what: str, unit: Unit = Unit.MONEY) -> RowView:
    return RowView("order_lines", f"{SHOPIFY} · {what}", "ol", _LINES, amount, _LINE_DAY, unit)


def _metric(column: str, what: str, unit: Unit) -> RowView:
    return RowView(
        "ad_metrics_daily", f"{META} · {what}", "m", _METRICS, f"m.{column}", "m.metric_date", unit
    )


REVENUE = _lines("ol.net_amount", "Order lines, net amount")
COGS = _lines("ol.quantity * ol.unit_cost_at_sale", "Order lines, cost of goods")
FEES = _lines("ol.quantity * ol.unit_fee_at_sale + ol.payment_fee_alloc", "Order lines, fees")
REFUNDS = RowView(
    "refunds", f"{SHOPIFY} · Refunds", "r", _REFUNDS, "r.amount", _REFUND_DAY, Unit.MONEY
)

VIEWS: dict[str, RowView] = {
    "revenue": REVENUE,
    "promoted_revenue": REVENUE,
    "cogs": COGS,
    "promoted_cogs": COGS,
    "fees": FEES,
    "promoted_fees": FEES,
    "refunds": REFUNDS,
    "promoted_refunds": REFUNDS,
    "units": _lines("ol.quantity", "Order lines, units", Unit.COUNT),
    "orders": RowView(
        "orders",
        f"{SHOPIFY} · Orders",
        "o",
        "FROM orders o WHERE o.store_id = :s AND o.id = ANY(:ids)",
        "1",
        _LINE_DAY,
        Unit.COUNT,
    ),
    "ad_spend": _metric("spend", "Daily spend", Unit.MONEY),
    "attributed_revenue": _metric("attributed_revenue", "Attributed revenue", Unit.MONEY),
    "attributed_purchases": _metric("attributed_purchases", "Attributed purchases", Unit.COUNT),
    "clicks": _metric("clicks", "Daily clicks", Unit.COUNT),
    "impressions": _metric("impressions", "Daily impressions", Unit.COUNT),
    "fixed_costs": RowView(
        "cost_items",
        "Your fixed costs",
        "c",
        "FROM (SELECT id, store_id, amount, period_start, "
        "(period_start::timestamp AT TIME ZONE 'UTC') AS cs, "
        "(period_end::timestamp AT TIME ZONE 'UTC') AS ce FROM cost_items "
        "WHERE store_id = :s AND id = ANY(:ids)) c WHERE TRUE",
        "c.amount * EXTRACT(EPOCH FROM (LEAST(c.ce, :end) - GREATEST(c.cs, :start))) "
        "/ EXTRACT(EPOCH FROM (c.ce - c.cs))",
        "c.period_start",
        Unit.MONEY,
    ),
    "units_on_hand": RowView(
        "inventory_snapshots",
        f"{SHOPIFY} · Inventory, end of day",
        "s",
        "FROM inventory_snapshots s WHERE s.store_id = :s AND s.id = ANY(:ids)",
        "s.units_on_hand",
        "s.snapshot_date",
        Unit.COUNT,
    ),
    "supplier_lead_time_days": RowView(
        "products",
        f"{SHOPIFY} · Products",
        "p",
        "FROM products p WHERE p.store_id = :s AND p.id = ANY(:ids)",
        "p.supplier_lead_time_days",
        "NULL::date",
        Unit.DAYS,
    ),
}

# How recent each source's data is, for the whole store.
_LAST_ORDER = "SELECT max((ordered_at AT TIME ZONE 'UTC')::date) FROM orders WHERE store_id = :s"
FRESHNESS: dict[str, str] = {
    "order_lines": _LAST_ORDER,
    "orders": _LAST_ORDER,
    "refunds": "SELECT max((refunded_at AT TIME ZONE 'UTC')::date) FROM refunds "
    "WHERE store_id = :s",
    "ad_metrics_daily": "SELECT max(metric_date) FROM ad_metrics_daily WHERE store_id = :s",
    "inventory_snapshots": "SELECT max(snapshot_date) FROM inventory_snapshots WHERE store_id = :s",
    "cost_items": "SELECT max(period_end) FROM cost_items WHERE store_id = :s",
}


@dataclass(frozen=True)
class SourceRow:
    id: UUID
    day: date | None
    amount: Decimal
    unit: Unit


def view_for(fact: Fact, table: str) -> RowView | None:
    view = VIEWS.get(fact.formula_id)
    return view if view is not None and view.table == table else None


def source_rows(
    conn: Connection,
    fact: Fact,
    table: str,
    ids: list[UUID],
    *,
    after: tuple[date | None, UUID] | None = None,
    limit: int = 50,
) -> list[SourceRow]:
    """One page of the fact's rows in `table`, by date then id, after the cursor `after`."""
    view = view_for(fact, table)
    if view is None or not ids:
        return []
    a = view.alias
    order = f"COALESCE({view.day}, DATE '0001-01-01'), {a}.id"
    sql = (
        f"SELECT {a}.id AS id, {view.day} AS day, {view.amount} AS amount {view.from_where}"
        + (
            f" AND ({order}) > (COALESCE(CAST(:day AS date), DATE '0001-01-01'), CAST(:id AS uuid))"
            if after
            else ""
        )
        + f" ORDER BY {order} LIMIT :limit"
    )
    params: dict[str, Any] = {"s": fact.store_id, "ids": ids, "limit": limit}
    if ":start" in view.amount:
        params |= {"start": fact.period.start, "end": fact.period.end}
    if after:
        params |= {"day": after[0], "id": after[1]}
    return [
        SourceRow(id=r.id, day=r.day, amount=Decimal(r.amount), unit=view.unit)
        for r in conn.execute(text(sql), params)
    ]


def data_up_to(conn: Connection, store_id: UUID, table: str) -> date | None:
    """The last day the source has data for, in the whole store; None when unknown."""
    sql = FRESHNESS.get(table)
    if sql is None:
        return None
    value = conn.execute(text(sql), {"s": store_id}).scalar()
    return value if isinstance(value, date) else None
