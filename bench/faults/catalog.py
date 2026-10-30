"""The fault catalogue. Each fault is a pure, seeded transformation of generated data with a
ground-truth label. Faults are Pydantic models so scenario manifests can store them as JSON."""

import dataclasses
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.detection.models import EntityRef, FaultFamily, SymptomCategory
from app.domain.models import OrderLine, Refund
from bench.faults.base import (
    Driver,
    FaultLabel,
    adjust_inventory,
    day_of,
    horizon_end,
    lines_by_order,
    order_net,
    payment_fee,
    promoted_products,
    recompute_attribution,
    remove_orders,
)
from bench.generator.model import GeneratedStore, Restock
from bench.generator.simulate import money, stable_id

PROFIT = SymptomCategory.PROFITABILITY


class _FaultBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start_day: int = Field(ge=1)
    magnitude: Decimal = Field(ge=0)

    @property
    def name(self) -> str:
        return str(getattr(self, "type"))  # noqa: B009 - every subclass defines `type`


class CpaDrift(_FaultBase):
    """The campaign's response degrades: a growing share of its ad-driven purchases disappears
    (ramping to `magnitude` over `ramp_days`) while spend is unchanged, so CPA rises."""

    type: Literal["cpa_drift"] = "cpa_drift"
    campaign_id: UUID
    ramp_days: int = Field(default=7, ge=1)

    def label(self) -> FaultLabel:
        return FaultLabel(
            fault_type=FaultFamily.CPA_DRIFT,
            entities=(EntityRef.campaign(self.campaign_id),),
            start_day=self.start_day,
            magnitude=self.magnitude,
            category=PROFIT,
            expected_driver=Driver.VOLUME,
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        orders = {o.id: o for o in data.orders}
        dropped: set[UUID] = set()
        for order_id, campaign_id in data.order_campaigns:
            if campaign_id != self.campaign_id:
                continue
            day = day_of(data, orders[order_id].ordered_at)
            if day < self.start_day:
                continue
            ramp = min(1.0, (day - self.start_day + 1) / self.ramp_days)
            if rng.random() < float(self.magnitude) * ramp:
                dropped.add(order_id)
        data = remove_orders(data, dropped)
        return recompute_attribution(data, {self.campaign_id}, self.start_day)


class Cannibalization(_FaultBase):
    """Spend scales up by `magnitude` but buys no incremental sales: the platform claims organic
    orders of the promoted products instead, so attributed purchases rise and real sales stay
    flat."""

    type: Literal["cannibalization"] = "cannibalization"
    campaign_id: UUID

    def label(self) -> FaultLabel:
        return FaultLabel(
            fault_type=FaultFamily.CANNIBALIZATION,
            entities=(EntityRef.campaign(self.campaign_id),),
            start_day=self.start_day,
            magnitude=self.magnitude,
            category=PROFIT,
            expected_driver=Driver.AD_SPEND,
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        promoted = promoted_products(data, self.campaign_id)
        bias = next(
            t.attribution_bias for t in data.campaign_truth if t.campaign_id == self.campaign_id
        )
        by_order = lines_by_order(data)
        ad_orders = {oid for oid, _ in data.order_campaigns}
        organic: dict[int, list[UUID]] = defaultdict(list)
        own_ad: dict[int, int] = defaultdict(int)
        for order in data.orders:
            day = day_of(data, order.ordered_at)
            if order.id in ad_orders:
                continue
            if any(line.product_id in promoted for line in by_order[order.id]):
                organic[day].append(order.id)
        ordered_at = {o.id: o.ordered_at for o in data.orders}
        for oid, cid in data.order_campaigns:
            if cid == self.campaign_id:
                own_ad[day_of(data, ordered_at[oid])] += 1
        scale = 1 + self.magnitude
        metrics = []
        for m in data.ad_metrics:
            day = (m.metric_date - data.config.start_date).days
            if m.campaign_id == self.campaign_id and day >= self.start_day:
                pool = organic[day]
                k = min(len(pool), round(own_ad[day] * float(self.magnitude)))
                picked = [
                    pool[int(i)] for i in sorted(rng.choice(len(pool), size=k, replace=False))
                ]
                claimed = sum((order_net(by_order[oid]) for oid in picked), Decimal(0))
                m = m.model_copy(
                    update={
                        "spend": money(m.spend * scale),
                        "impressions": int(m.impressions * float(scale)),
                        "clicks": int(m.clicks * float(scale)),
                        "attributed_purchases": m.attributed_purchases + round(k * bias),
                        "attributed_revenue": m.attributed_revenue
                        + money(claimed * Decimal(str(bias))),
                    }
                )
            metrics.append(m)
        return dataclasses.replace(data, ad_metrics=tuple(metrics))


class StockoutOnPromoted(_FaultBase):
    """A promoted product's supplier fails: from `start_day` it is out of stock, its orders are
    lost, and its campaign keeps spending."""

    type: Literal["stockout_on_promoted"] = "stockout_on_promoted"
    campaign_id: UUID
    product_id: UUID
    magnitude: Decimal = Decimal(1)

    def label(self) -> FaultLabel:
        return FaultLabel(
            fault_type=FaultFamily.STOCKOUT_ON_PROMOTED,
            entities=(EntityRef.product(self.product_id), EntityRef.campaign(self.campaign_id)),
            start_day=self.start_day,
            magnitude=self.magnitude,
            category=PROFIT,
            expected_driver=Driver.VOLUME,
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        orders = {o.id: o for o in data.orders}
        # A restock (the simulator's) ends the stockout; without one it lasts to the end.
        end = min(
            (
                r.day
                for r in data.interventions
                if isinstance(r, Restock)
                and r.product == self.product_id
                and r.day > self.start_day
            ),
            default=None,
        )
        lost = {
            line.order_id
            for line in data.lines
            if line.product_id == self.product_id
            and self.start_day
            <= day_of(data, orders[line.order_id].ordered_at)
            < (end if end is not None else data.config.days)
        }
        data = remove_orders(data, lost)
        data = adjust_inventory(
            data,
            {},
            zero_from={self.product_id: self.start_day},
            zero_until={self.product_id: end} if end is not None else None,
        )
        return recompute_attribution(data, {c.id for c in data.campaigns}, self.start_day)


class SupplierCostIncrease(_FaultBase):
    """The product's unit cost rises by `magnitude` from `start_day`."""

    type: Literal["supplier_cost_increase"] = "supplier_cost_increase"
    product_id: UUID

    def label(self) -> FaultLabel:
        return FaultLabel(
            fault_type=FaultFamily.SUPPLIER_COST_INCREASE,
            entities=(EntityRef.product(self.product_id),),
            start_day=self.start_day,
            magnitude=self.magnitude,
            category=PROFIT,
            expected_driver=Driver.UNIT_COST,
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        orders = {o.id: o for o in data.orders}
        scale = 1 + self.magnitude
        lines = tuple(
            line.model_copy(update={"unit_cost_at_sale": money(line.unit_cost_at_sale * scale)})
            if line.product_id == self.product_id
            and day_of(data, orders[line.order_id].ordered_at) >= self.start_day
            else line
            for line in data.lines
        )
        products = tuple(
            p.model_copy(update={"unit_cost": money(p.unit_cost * scale)})
            if p.id == self.product_id
            else p
            for p in data.products
        )
        return dataclasses.replace(data, lines=lines, products=products)


class RefundSpike(_FaultBase):
    """From `start_day`, each sold line of the product is additionally refunded with probability
    `magnitude` (2-20 days later, when that falls inside the horizon)."""

    type: Literal["refund_spike"] = "refund_spike"
    product_id: UUID

    def label(self) -> FaultLabel:
        return FaultLabel(
            fault_type=FaultFamily.REFUND_SPIKE,
            entities=(EntityRef.product(self.product_id),),
            start_day=self.start_day,
            magnitude=self.magnitude,
            category=PROFIT,
            expected_driver=Driver.REFUNDS,
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        orders = {o.id: o for o in data.orders}
        refunded = {r.order_line_id for r in data.refunds}
        end = horizon_end(data)
        extra: list[Refund] = []
        for line in data.lines:
            ordered_at = orders[line.order_id].ordered_at
            if line.product_id != self.product_id or line.id in refunded:
                continue
            if day_of(data, ordered_at) < self.start_day:
                continue
            if rng.random() >= float(self.magnitude):
                continue
            when = ordered_at + timedelta(days=int(rng.integers(2, 21)), hours=3)
            if when < end:
                extra.append(
                    Refund(
                        id=stable_id(data.store.store_id, "fault_refund", line.id),
                        store_id=line.store_id,
                        order_id=line.order_id,
                        order_line_id=line.id,
                        refunded_at=when,
                        amount=line.net_amount,
                        quantity=line.quantity,
                        currency=line.currency,
                        reason="quality_issue",
                    )
                )
        return dataclasses.replace(data, refunds=data.refunds + tuple(extra))


class MixShift(_FaultBase):
    """From `start_day`, organic purchases of high-margin products switch, with probability
    `magnitude`, to a low-margin product at about the same line value: revenue stays roughly
    stable while margin falls."""

    type: Literal["mix_shift"] = "mix_shift"

    def label(self) -> FaultLabel:
        return FaultLabel(
            fault_type=FaultFamily.MIX_SHIFT,
            entities=(EntityRef.store(),),
            start_day=self.start_day,
            magnitude=self.magnitude,
            category=PROFIT,
            expected_driver=Driver.MIX,
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        def margin_rate(p_id: UUID) -> Decimal:
            p = products[p_id]
            return (p.price - p.unit_cost - p.unit_fee) / p.price

        products = {p.id: p for p in data.products}
        ranked = sorted(products, key=lambda pid: (margin_rate(pid), str(pid)))
        third = max(1, len(ranked) // 3)
        low, high = ranked[:third], set(ranked[-third:])
        orders = {o.id: o for o in data.orders}
        ad_orders = {oid for oid, _ in data.order_campaigns}
        deltas: dict[UUID, list[tuple[int, int]]] = defaultdict(list)
        changed: dict[UUID, OrderLine] = {}
        for line in data.lines:
            order = orders[line.order_id]
            day = day_of(data, order.ordered_at)
            if day < self.start_day or line.order_id in ad_orders or line.product_id not in high:
                continue
            if rng.random() >= float(self.magnitude):
                continue
            target = products[low[int(rng.integers(0, len(low)))]]
            quantity = max(1, int((line.net_amount / target.price).to_integral_value()))
            net = target.price * quantity
            changed[line.id] = line.model_copy(
                update={
                    "product_id": target.id,
                    "quantity": quantity,
                    "unit_price": target.price,
                    "discount_amount": Decimal(0),
                    "tax_amount": money(net * data.config.tax_rate),
                    "unit_cost_at_sale": target.unit_cost,
                    "unit_fee_at_sale": target.unit_fee,
                }
            )
            # Units the original product did not sell go back to its stock. The products demand
            # moves to are assumed replenished by the store (the adaptive reorder policy would
            # follow their sales), so their stock is left alone: no impossible stockouts.
            deltas[line.product_id].append((day, line.quantity))
        lines = tuple(changed.get(line.id, line) for line in data.lines)
        data = dataclasses.replace(data, lines=lines)
        by_order = lines_by_order(data)
        touched = {line.order_id for line in changed.values()}
        new_orders = tuple(
            o.model_copy(update={"payment_fee_amount": payment_fee(data, o, by_order[o.id])})
            if o.id in touched
            else o
            for o in data.orders
        )
        refunds = tuple(
            r.model_copy(
                update={
                    "amount": changed[r.order_line_id].net_amount,
                    "quantity": changed[r.order_line_id].quantity,
                }
            )
            if r.order_line_id in changed
            else r
            for r in data.refunds
        )
        data = dataclasses.replace(data, orders=new_orders, refunds=refunds)
        return adjust_inventory(data, deltas)


class FeeIncrease(_FaultBase):
    """Payment fees (store) or one product's per-unit fee rise by `magnitude` from `start_day`."""

    type: Literal["fee_increase"] = "fee_increase"
    product_id: UUID | None = None

    def label(self) -> FaultLabel:
        entity = (
            EntityRef.store() if self.product_id is None else EntityRef.product(self.product_id)
        )
        return FaultLabel(
            fault_type=FaultFamily.FEE_INCREASE,
            entities=(entity,),
            start_day=self.start_day,
            magnitude=self.magnitude,
            category=PROFIT,
            expected_driver=Driver.FEES,
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        scale = 1 + self.magnitude
        if self.product_id is None:
            orders = tuple(
                o.model_copy(update={"payment_fee_amount": money(o.payment_fee_amount * scale)})
                if day_of(data, o.ordered_at) >= self.start_day
                else o
                for o in data.orders
            )
            return dataclasses.replace(data, orders=orders)
        by_id = {o.id: o for o in data.orders}
        lines = tuple(
            line.model_copy(update={"unit_fee_at_sale": money(line.unit_fee_at_sale * scale)})
            if line.product_id == self.product_id
            and day_of(data, by_id[line.order_id].ordered_at) >= self.start_day
            else line
            for line in data.lines
        )
        products = tuple(
            p.model_copy(update={"unit_fee": money(p.unit_fee * scale)})
            if p.id == self.product_id
            else p
            for p in data.products
        )
        return dataclasses.replace(data, lines=lines, products=products)


class TrackingBreak(_FaultBase):
    """The platform stops reporting conversions: attributed purchases and revenue fall by
    `magnitude` from `start_day`. Real orders are unchanged."""

    type: Literal["tracking_break"] = "tracking_break"
    campaign_id: UUID

    def label(self) -> FaultLabel:
        return FaultLabel(
            fault_type=FaultFamily.TRACKING_BREAK,
            entities=(EntityRef.campaign(self.campaign_id),),
            start_day=self.start_day,
            magnitude=self.magnitude,
            category=SymptomCategory.DATA_QUALITY,
            expected_driver=None,
        )

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        keep = 1 - self.magnitude
        metrics = tuple(
            m.model_copy(
                update={
                    "attributed_purchases": round(m.attributed_purchases * float(keep)),
                    "attributed_revenue": money(m.attributed_revenue * keep),
                }
            )
            if m.campaign_id == self.campaign_id
            and (m.metric_date - data.config.start_date).days >= self.start_day
            else m
            for m in data.ad_metrics
        )
        return dataclasses.replace(data, ad_metrics=metrics)


AnyFault = Annotated[
    CpaDrift
    | Cannibalization
    | StockoutOnPromoted
    | SupplierCostIncrease
    | RefundSpike
    | MixShift
    | FeeIncrease
    | TrackingBreak,
    Field(discriminator="type"),
]
