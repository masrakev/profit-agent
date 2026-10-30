"""Ground-truth labels and helpers that keep generated data consistent when a fault rewrites it.

Every helper is pure: it takes a `GeneratedStore` and returns a new one.
"""

import dataclasses
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.causes.drivers import Driver as Driver  # re-exported for fault definitions
from app.detection.models import EntityRef, FaultFamily, SymptomCategory
from app.domain.models import AdMetricDaily, Order, OrderLine
from bench.generator.model import GeneratedStore
from bench.generator.simulate import money


class FaultLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fault_type: FaultFamily
    entities: tuple[EntityRef, ...]  # any of them is an acceptable root-cause entity
    start_day: int
    magnitude: Decimal
    category: SymptomCategory
    expected_driver: Driver | None  # largest negative level-1 driver; None if profit is unchanged


def day_of(data: GeneratedStore, when: datetime) -> int:
    return (when.date() - data.config.start_date).days


def horizon_end(data: GeneratedStore) -> datetime:
    end = data.config.start_date + timedelta(days=data.config.days)
    return datetime.combine(end, time(), tzinfo=UTC)


def lines_by_order(data: GeneratedStore) -> dict[UUID, list[OrderLine]]:
    out: dict[UUID, list[OrderLine]] = defaultdict(list)
    for line in data.lines:
        out[line.order_id].append(line)
    return out


def order_net(lines: Iterable[OrderLine]) -> Decimal:
    return sum((line.net_amount for line in lines), Decimal(0))


def payment_fee(data: GeneratedStore, order: Order, lines: Iterable[OrderLine]) -> Decimal:
    """Payment fee of an order, with the generator's formula."""
    lines = list(lines)
    subtotal = order_net(lines)
    tax = sum((line.tax_amount for line in lines), Decimal(0))
    cfg = data.config
    return money(
        (subtotal + tax + order.shipping_amount) * cfg.payment_fee_rate + cfg.payment_fee_fixed
    )


def adjust_inventory(
    data: GeneratedStore,
    deltas: Mapping[UUID, Iterable[tuple[int, int]]],
    zero_from: Mapping[UUID, int] | None = None,
    zero_until: Mapping[UUID, int] | None = None,
) -> GeneratedStore:
    """Add `delta` units to a product's snapshots from `day` on; force zero from `zero_from`
    (until `zero_until`, exclusive, when given)."""
    per_product = {pid: sorted(items) for pid, items in deltas.items()}
    zero_from = zero_from or {}
    zero_until = zero_until or {}
    snapshots = []
    for snap in data.inventory:
        pid = snap.product_id
        day = (snap.snapshot_date - data.config.start_date).days
        if pid in zero_from and zero_from[pid] <= day < zero_until.get(pid, day + 1):
            units = 0
        elif pid in per_product:
            units = snap.units_on_hand + sum(d for first, d in per_product[pid] if first <= day)
        else:
            snapshots.append(snap)
            continue
        snapshots.append(snap.model_copy(update={"units_on_hand": max(0, units)}))
    return dataclasses.replace(data, inventory=tuple(snapshots))


def remove_orders(data: GeneratedStore, order_ids: set[UUID]) -> GeneratedStore:
    """Drop orders with their lines and refunds; removed units go back into stock."""
    if not order_ids:
        return data
    orders = {o.id: o for o in data.orders}
    deltas: dict[UUID, list[tuple[int, int]]] = defaultdict(list)
    for line in data.lines:
        if line.order_id in order_ids:
            deltas[line.product_id].append(
                (day_of(data, orders[line.order_id].ordered_at), line.quantity)
            )
    data = dataclasses.replace(
        data,
        orders=tuple(o for o in data.orders if o.id not in order_ids),
        lines=tuple(line for line in data.lines if line.order_id not in order_ids),
        refunds=tuple(r for r in data.refunds if r.order_id not in order_ids),
        order_campaigns=tuple(oc for oc in data.order_campaigns if oc[0] not in order_ids),
    )
    return adjust_inventory(data, deltas)


def recompute_attribution(
    data: GeneratedStore, campaign_ids: set[UUID], from_day: int
) -> GeneratedStore:
    """Platform attribution from the remaining ad-driven orders, as the generator computes it."""
    bias = {t.campaign_id: t.attribution_bias for t in data.campaign_truth}
    orders = {o.id: o for o in data.orders}
    by_order = lines_by_order(data)
    counts: dict[tuple[UUID, int], int] = defaultdict(int)
    nets: dict[tuple[UUID, int], Decimal] = defaultdict(Decimal)
    for order_id, campaign_id in data.order_campaigns:
        key = (campaign_id, day_of(data, orders[order_id].ordered_at))
        counts[key] += 1
        nets[key] += order_net(by_order[order_id])
    metrics: list[AdMetricDaily] = []
    for m in data.ad_metrics:
        day = (m.metric_date - data.config.start_date).days
        if m.campaign_id in campaign_ids and day >= from_day:
            key = (m.campaign_id, day)
            m = m.model_copy(
                update={
                    "attributed_purchases": round(counts[key] * bias[m.campaign_id]),
                    "attributed_revenue": money(nets[key] * Decimal(str(bias[m.campaign_id]))),
                }
            )
        metrics.append(m)
    return dataclasses.replace(data, ad_metrics=tuple(metrics))


def promoted_products(data: GeneratedStore, campaign_id: UUID) -> set[UUID]:
    return {link.product_id for link in data.campaign_products if link.campaign_id == campaign_id}
