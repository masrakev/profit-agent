"""Daily series for detectors, aggregated in SQL on NUMERIC columns (one query per table).

The per-day amounts use the same definitions as the fact formulas (revenue = line net amount by
order date, refunds by refund date, ...), so a window sum of a series equals the matching fact.
Detectors use these series to decide *when* something changed; whatever they report is then
backed by persisted facts.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, text

ZERO = Decimal(0)


def _days(n: int) -> list[Decimal]:
    return [ZERO] * n


@dataclass
class ProductSeries:
    product_id: UUID
    lead_time_days: int | None
    revenue: list[Decimal]
    units: list[Decimal]
    cogs: list[Decimal]
    unit_fees: list[Decimal]
    payment_fees: list[Decimal]
    refunds: list[Decimal]
    refunded_units: list[Decimal]
    lines: list[Decimal]  # order lines sold
    refund_events: list[Decimal]  # refunds issued
    on_hand: list[int | None]

    @property
    def fees(self) -> list[Decimal]:
        return [a + b for a, b in zip(self.unit_fees, self.payment_fees, strict=True)]


@dataclass
class CampaignSeries:
    campaign_id: UUID
    promoted: tuple[UUID, ...]
    spend: list[Decimal]
    attributed_purchases: list[Decimal]
    attributed_revenue: list[Decimal]


@dataclass
class StoreSeries:
    start: date
    days: int
    products: dict[UUID, ProductSeries] = field(default_factory=dict)
    campaigns: dict[UUID, CampaignSeries] = field(default_factory=dict)

    def day(self, index: int) -> date:
        return self.start + timedelta(days=index)

    def index(self, day: date) -> int:
        return (day - self.start).days

    def total(self, metric: str, product_ids: tuple[UUID, ...] | None = None) -> list[Decimal]:
        """Sum of a product metric over all products (or the given ones), per day."""
        out = _days(self.days)
        for pid, series in self.products.items():
            if product_ids is not None and pid not in product_ids:
                continue
            values: list[Decimal] = getattr(series, metric)
            out = [a + b for a, b in zip(out, values, strict=True)]
        return out

    def campaigns_promoting(self, product_id: UUID) -> list[UUID]:
        return sorted(
            (c.campaign_id for c in self.campaigns.values() if product_id in c.promoted), key=str
        )


def load_series(conn: Connection, store_id: UUID) -> StoreSeries:
    """All daily series of a store, from its first to its last day with orders or ad spend."""
    params = {"sid": store_id}
    bounds = conn.execute(
        text(
            "SELECT min(d) AS first, max(d) AS last FROM ("
            "  SELECT (ordered_at AT TIME ZONE 'UTC')::date AS d FROM orders WHERE store_id = :sid"
            "  UNION ALL SELECT metric_date FROM ad_metrics_daily WHERE store_id = :sid"
            ") x"
        ),
        params,
    ).one()
    if bounds.first is None:
        return StoreSeries(start=date.min, days=0)
    start: date = bounds.first
    n = (bounds.last - start).days + 1
    series = StoreSeries(start=start, days=n)

    for row in conn.execute(
        text("SELECT id, supplier_lead_time_days FROM products WHERE store_id = :sid ORDER BY id"),
        params,
    ):
        series.products[row.id] = ProductSeries(
            product_id=row.id,
            lead_time_days=row.supplier_lead_time_days,
            revenue=_days(n),
            units=_days(n),
            cogs=_days(n),
            unit_fees=_days(n),
            payment_fees=_days(n),
            refunds=_days(n),
            refunded_units=_days(n),
            lines=_days(n),
            refund_events=_days(n),
            on_hand=[None] * n,
        )

    lines = conn.execute(
        text(
            "SELECT (o.ordered_at AT TIME ZONE 'UTC')::date AS day, ol.product_id, "
            "sum(ol.net_amount) AS revenue, sum(ol.quantity) AS units, "
            "sum(ol.quantity * ol.unit_cost_at_sale) AS cogs, "
            "sum(ol.quantity * ol.unit_fee_at_sale) AS unit_fees, "
            "sum(ol.payment_fee_alloc) AS payment_fees, count(*) AS lines "
            "FROM order_lines ol JOIN orders o ON o.store_id = ol.store_id AND o.id = ol.order_id "
            "WHERE ol.store_id = :sid AND o.status <> 'cancelled' GROUP BY 1, 2"
        ),
        params,
    )
    for row in lines:
        p, i = series.products[row.product_id], (row.day - start).days
        p.revenue[i], p.units[i], p.cogs[i] = row.revenue, Decimal(row.units), row.cogs
        p.unit_fees[i], p.payment_fees[i] = row.unit_fees, row.payment_fees
        p.lines[i] = Decimal(row.lines)

    refunds = conn.execute(
        text(
            "SELECT (r.refunded_at AT TIME ZONE 'UTC')::date AS day, ol.product_id, "
            "sum(r.amount) AS amount, sum(r.quantity) AS units, count(*) AS events "
            "FROM refunds r "
            "JOIN order_lines ol ON ol.store_id = r.store_id AND ol.id = r.order_line_id "
            "WHERE r.store_id = :sid GROUP BY 1, 2"
        ),
        params,
    )
    for row in refunds:
        i = (row.day - start).days
        if 0 <= i < n:
            series.products[row.product_id].refunds[i] = row.amount
            series.products[row.product_id].refunded_units[i] = Decimal(row.units)
            series.products[row.product_id].refund_events[i] = Decimal(row.events)

    for row in conn.execute(
        text(
            "SELECT product_id, snapshot_date, units_on_hand FROM inventory_snapshots "
            "WHERE store_id = :sid"
        ),
        params,
    ):
        i = (row.snapshot_date - start).days
        if 0 <= i < n:
            series.products[row.product_id].on_hand[i] = int(row.units_on_hand)

    promoted: dict[UUID, list[UUID]] = defaultdict(list)
    for row in conn.execute(
        text("SELECT campaign_id, product_id FROM ad_campaign_products WHERE store_id = :sid"),
        params,
    ):
        promoted[row.campaign_id].append(row.product_id)
    for row in conn.execute(
        text("SELECT id FROM ad_campaigns WHERE store_id = :sid ORDER BY id"), params
    ):
        series.campaigns[row.id] = CampaignSeries(
            row.id, tuple(sorted(promoted[row.id], key=str)), _days(n), _days(n), _days(n)
        )
    for row in conn.execute(
        text(
            "SELECT metric_date, campaign_id, spend, attributed_purchases, attributed_revenue "
            "FROM ad_metrics_daily WHERE store_id = :sid"
        ),
        params,
    ):
        c, i = series.campaigns[row.campaign_id], (row.metric_date - start).days
        c.spend[i] = row.spend
        c.attributed_purchases[i] = Decimal(row.attributed_purchases)
        c.attributed_revenue[i] = row.attributed_revenue
    return series
