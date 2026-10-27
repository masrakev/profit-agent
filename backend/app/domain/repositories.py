"""Write and read paths for domain records. Used by the application and by the bench generator.

Every method expects a connection inside `tenant_transaction` for the records' store; row-level
security rejects rows of any other store.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Connection, Table, insert, select

from app.domain import schema
from app.domain.models import (
    AdCampaign,
    AdCampaignProduct,
    AdMetricDaily,
    CostItem,
    InventorySnapshot,
    Order,
    OrderLine,
    Product,
    Refund,
    Store,
)
from app.domain.money import allocate_pro_rata


def _row(model: BaseModel, **extra: Any) -> dict[str, Any]:
    data = model.model_dump()
    data.update(extra)
    return {k: (v.value if isinstance(v, Enum) else v) for k, v in data.items()}


def _insert(conn: Connection, table: Table, rows: list[dict[str, Any]]) -> int:
    if rows:
        conn.execute(insert(table), rows)
    return len(rows)


class StoreRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def create(self, store: Store) -> None:
        self.conn.execute(insert(schema.stores).values(**_row(store)))

    def get(self, store_id: UUID) -> Store | None:
        row = self.conn.execute(
            select(
                schema.stores.c.store_id,
                schema.stores.c.name,
                schema.stores.c.currency,
                schema.stores.c.timezone,
            ).where(schema.stores.c.store_id == store_id)
        ).first()
        return None if row is None else Store.model_validate(row._asdict())


class ProductRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def add_many(self, products: Iterable[Product]) -> int:
        return _insert(self.conn, schema.products, [_row(p) for p in products])

    def list_ids(self, store_id: UUID) -> list[UUID]:
        rows = self.conn.execute(
            select(schema.products.c.id)
            .where(schema.products.c.store_id == store_id)
            .order_by(schema.products.c.id)
        )
        return [r.id for r in rows]


class OrderRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def add_many(self, orders: Sequence[Order], lines: Sequence[OrderLine]) -> int:
        """Insert orders with their lines, allocating each order's payment fee to its lines.

        The allocation is pro rata to line net amounts, in 0.0001 units, and sums exactly to the
        order's payment fee, so store-level and product-level fees reconcile to the cent.
        """
        by_order: dict[UUID, list[OrderLine]] = defaultdict(list)
        for line in lines:
            by_order[line.order_id].append(line)
        order_ids = {o.id for o in orders}
        orphan = set(by_order) - order_ids
        if orphan:
            raise ValueError(f"{len(orphan)} lines reference orders outside this batch")
        line_rows: list[dict[str, Any]] = []
        for order in orders:
            order_lines = by_order.get(order.id, [])
            if not order_lines and order.payment_fee_amount != 0:
                raise ValueError(f"order {order.external_id} has a payment fee but no lines")
            for line in order_lines:
                if line.currency != order.currency or line.store_id != order.store_id:
                    raise ValueError(f"line {line.id} does not match its order's store/currency")
            allocations = allocate_pro_rata(
                order.payment_fee_amount, [line.net_amount for line in order_lines]
            )
            line_rows.extend(
                _row(line, payment_fee_alloc=alloc)
                for line, alloc in zip(order_lines, allocations, strict=True)
            )
        _insert(self.conn, schema.orders, [_row(o) for o in orders])
        _insert(self.conn, schema.order_lines, line_rows)
        return len(orders)


class RefundRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def add_many(self, refunds: Iterable[Refund]) -> int:
        return _insert(self.conn, schema.refunds, [_row(r) for r in refunds])


class InventoryRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def add_many(self, snapshots: Iterable[InventorySnapshot]) -> int:
        return _insert(self.conn, schema.inventory_snapshots, [_row(s) for s in snapshots])


class CampaignRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def add_many(
        self, campaigns: Iterable[AdCampaign], promoted: Iterable[AdCampaignProduct]
    ) -> int:
        count = _insert(self.conn, schema.ad_campaigns, [_row(c) for c in campaigns])
        _insert(self.conn, schema.ad_campaign_products, [_row(p) for p in promoted])
        return count

    def list_ids(self, store_id: UUID) -> list[UUID]:
        rows = self.conn.execute(
            select(schema.ad_campaigns.c.id)
            .where(schema.ad_campaigns.c.store_id == store_id)
            .order_by(schema.ad_campaigns.c.id)
        )
        return [r.id for r in rows]


class AdMetricsRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def add_many(self, metrics: Iterable[AdMetricDaily]) -> int:
        return _insert(self.conn, schema.ad_metrics_daily, [_row(m) for m in metrics])


class CostItemRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def add_many(self, items: Iterable[CostItem]) -> int:
        return _insert(self.conn, schema.cost_items, [_row(i) for i in items])
