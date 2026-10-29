"""Terse builders for hand-written scenarios. All writes go through the app repositories."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Connection

from app.domain.models import (
    AdCampaign,
    AdCampaignProduct,
    AdMetricDaily,
    CostItem,
    InventorySnapshot,
    Order,
    OrderLine,
    OrderStatus,
    Product,
    Refund,
)
from app.domain.repositories import (
    AdMetricsRepository,
    CampaignRepository,
    CostItemRepository,
    InventoryRepository,
    OrderRepository,
    ProductRepository,
    RefundRepository,
)

D = Decimal


def ts(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


class Scenario:
    def __init__(self, conn: Connection, store_id: UUID, currency: str = "USD") -> None:
        self.conn = conn
        self.store_id = store_id
        self.currency = currency
        self._orders = 0

    def product(
        self, price: str, cost: str, fee: str, sku: str | None = None, lead_time: int | None = None
    ) -> UUID:
        pid = uuid4()
        ProductRepository(self.conn).add_many(
            [
                Product(
                    id=pid,
                    store_id=self.store_id,
                    sku=sku or f"SKU-{pid.hex[:8]}",
                    name="Product",
                    price=D(price),
                    unit_cost=D(cost),
                    unit_fee=D(fee),
                    currency=self.currency,
                    supplier_lead_time_days=lead_time,
                )
            ]
        )
        return pid

    def order(
        self,
        at: str,
        lines: list[tuple[UUID, int, str, str, str]],
        *,
        payment_fee: str = "0",
        shipping: str = "0",
        discounts: list[str] | None = None,
        taxes: list[str] | None = None,
        status: OrderStatus = OrderStatus.PAID,
        currency: str | None = None,
    ) -> list[UUID]:
        """`lines`: (product, quantity, unit price, unit cost at sale, unit fee at sale)."""
        self._orders += 1
        currency = currency or self.currency
        order = Order(
            id=uuid4(),
            store_id=self.store_id,
            external_id=f"#{self._orders}-{uuid4().hex[:8]}",
            ordered_at=ts(at),
            status=status,
            currency=currency,
            shipping_amount=D(shipping),
            payment_fee_amount=D(payment_fee),
        )
        built = [
            OrderLine(
                id=uuid4(),
                store_id=self.store_id,
                order_id=order.id,
                product_id=product,
                quantity=qty,
                unit_price=D(price),
                discount_amount=D((discounts or [])[i] if discounts else "0"),
                tax_amount=D((taxes or [])[i] if taxes else "0"),
                unit_cost_at_sale=D(cost),
                unit_fee_at_sale=D(fee),
                currency=currency,
            )
            for i, (product, qty, price, cost, fee) in enumerate(lines)
        ]
        OrderRepository(self.conn).add_many([order], built)
        return [line.id for line in built]

    def refund(self, order_line: UUID, at: str, amount: str, quantity: int = 1) -> UUID:
        order_id = self.conn.exec_driver_sql(
            "SELECT order_id FROM order_lines WHERE id = %(id)s", {"id": order_line}
        ).scalar_one()
        rid = uuid4()
        RefundRepository(self.conn).add_many(
            [
                Refund(
                    id=rid,
                    store_id=self.store_id,
                    order_id=order_id,
                    order_line_id=order_line,
                    refunded_at=ts(at),
                    amount=D(amount),
                    quantity=quantity,
                    currency=self.currency,
                )
            ]
        )
        return rid

    def campaign(self, promoted: list[UUID], budget: str = "100") -> UUID:
        cid = uuid4()
        CampaignRepository(self.conn).add_many(
            [
                AdCampaign(
                    id=cid,
                    store_id=self.store_id,
                    external_id=f"cmp-{cid.hex[:8]}",
                    name="Campaign",
                    platform="meta",
                    currency=self.currency,
                    daily_budget=D(budget),
                )
            ],
            [
                AdCampaignProduct(store_id=self.store_id, campaign_id=cid, product_id=p)
                for p in promoted
            ],
        )
        return cid

    def ad_day(self, campaign: UUID, day: str, spend: str, purchases: int, revenue: str) -> UUID:
        mid = uuid4()
        AdMetricsRepository(self.conn).add_many(
            [
                AdMetricDaily(
                    id=mid,
                    store_id=self.store_id,
                    campaign_id=campaign,
                    metric_date=date.fromisoformat(day),
                    spend=D(spend),
                    currency=self.currency,
                    impressions=1000,
                    clicks=10,
                    attributed_purchases=purchases,
                    attributed_revenue=D(revenue),
                )
            ]
        )
        return mid

    def fixed_cost(self, amount: str, start: str, end: str) -> UUID:
        cid = uuid4()
        CostItemRepository(self.conn).add_many(
            [
                CostItem(
                    id=cid,
                    store_id=self.store_id,
                    name="Fixed",
                    category="overhead",
                    amount=D(amount),
                    currency=self.currency,
                    period_start=date.fromisoformat(start),
                    period_end=date.fromisoformat(end),
                )
            ]
        )
        return cid

    def stock(self, product: UUID, day: str, units: int) -> UUID:
        sid = uuid4()
        InventoryRepository(self.conn).add_many(
            [
                InventorySnapshot(
                    id=sid,
                    store_id=self.store_id,
                    product_id=product,
                    snapshot_date=date.fromisoformat(day),
                    units_on_hand=units,
                )
            ]
        )
        return sid
