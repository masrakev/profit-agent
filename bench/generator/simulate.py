"""Deterministic synthetic store simulation.

Floats drive the simulation (demand rates, response curves); every amount written to a record is a
`Decimal` quantized to the cent. All randomness comes from one seeded generator, consumed in a
fixed order, so `generate(config)` is a pure function of `config`.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np

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
from bench.generator.config import GeneratorConfig
from bench.generator.faults import Fault, apply_faults
from bench.generator.model import CampaignTruth, GeneratedStore, ProductTruth

CENT = Decimal("0.01")
STORE_NAMESPACE = uuid5(NAMESPACE_URL, "https://profit-agent.dev/bench/store")
ADJECTIVES = ("Classic", "Organic", "Premium", "Everyday", "Travel", "Compact", "Deluxe", "Eco")
NOUNS = (
    "Mug",
    "Tote",
    "Candle",
    "Notebook",
    "Bottle",
    "Scarf",
    "Lamp",
    "Planter",
    "Wallet",
    "Blanket",
    "Backpack",
    "Kettle",
    "Journal",
    "Pillow",
    "Apron",
)
FIXED_COSTS = (
    ("Ecommerce platform plan", "software", 79.0, 79.0),
    ("Apps and tools", "software", 40.0, 220.0),
    ("Team salaries", "payroll", 2500.0, 7000.0),
    ("Warehouse rent", "rent", 400.0, 1500.0),
)


def money(value: float | Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_EVEN)


def stable_id(store_id: UUID, *parts: object) -> UUID:
    return uuid5(store_id, ":".join(str(p) for p in parts))


@dataclass
class _ProductState:
    product: Product
    truth: ProductTruth
    cost_schedule: list[tuple[int, Decimal]]  # (first day, unit cost)
    on_hand: int
    pipeline: list[tuple[int, int]] = field(default_factory=list)  # (arrival day, units)

    def cost_on(self, day: int) -> Decimal:
        cost = self.cost_schedule[0][1]
        for first_day, value in self.cost_schedule:
            if day >= first_day:
                cost = value
        return cost


@dataclass
class _Builder:
    config: GeneratorConfig
    rng: np.random.Generator
    store_id: UUID
    orders: list[Order] = field(default_factory=list)
    lines: list[OrderLine] = field(default_factory=list)
    refunds: list[Refund] = field(default_factory=list)
    lost_sales_units: int = 0

    @property
    def horizon_end(self) -> datetime:
        return _midnight(self.config.start_date + timedelta(days=self.config.days))


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


def store_id_for(config: GeneratorConfig) -> UUID:
    return uuid5(STORE_NAMESPACE, f"{config.seed}:{config.fingerprint}")


def generate(config: GeneratorConfig, faults: Sequence[Fault] = ()) -> GeneratedStore:
    rng = np.random.default_rng(config.seed)
    store_id = store_id_for(config)
    store = Store(
        store_id=store_id,
        name=config.store_name or f"Bench store {config.seed}",
        currency=config.currency,
    )
    states = _products(config, rng, store_id)
    campaigns, promoted, campaign_truth = _campaigns(config, rng, store_id, states)
    builder = _Builder(config, rng, store_id)
    inventory: list[InventorySnapshot] = []
    metrics: list[AdMetricDaily] = []
    promoted_by_campaign: dict[UUID, list[int]] = {}
    index_of = {s.product.id: i for i, s in enumerate(states)}
    for link in promoted:
        promoted_by_campaign.setdefault(link.campaign_id, []).append(index_of[link.product_id])

    for day in range(config.days):
        today = config.start_date + timedelta(days=day)
        dow = float(config.weekly_seasonality[today.weekday()])
        for state in states:
            arrived = sum(units for arrival, units in state.pipeline if arrival == day)
            state.on_hand += arrived
            state.pipeline = [(a, u) for a, u in state.pipeline if a != day]

        # Demand events: (product index, campaign index or -1 for organic).
        events: list[tuple[int, int]] = []
        for i, state in enumerate(states):
            n = int(rng.poisson(state.truth.base_daily_demand * dow))
            events.extend((i, -1) for _ in range(n))
        spend_today: dict[int, Decimal] = {}
        for c, truth in enumerate(campaign_truth):
            if day < truth.start_day:
                continue
            spend = money(float(campaigns[c].daily_budget) * rng.uniform(0.75, 1.05))
            spend_today[c] = spend
            expected = truth.a * (1.0 - math.exp(-truth.b * float(spend)))
            purchases = max(0, round(expected + rng.normal(0.0, truth.noise_sd)))
            candidates = promoted_by_campaign[campaigns[c].id]
            events.extend((int(rng.choice(candidates)), c) for _ in range(purchases))
        order = rng.permutation(len(events))

        ad_orders = dict.fromkeys(spend_today, 0)
        ad_net = {c: Decimal(0) for c in spend_today}
        for k in order:
            product_index, campaign_index = events[int(k)]
            net = _sell(builder, states, product_index, day)
            if net is not None and campaign_index >= 0:
                ad_orders[campaign_index] += 1
                ad_net[campaign_index] += net

        for c, spend in spend_today.items():
            truth = campaign_truth[c]
            impressions = int(float(spend) * rng.uniform(30.0, 60.0))
            clicks = int(rng.binomial(impressions, rng.uniform(0.008, 0.02)))
            metrics.append(
                AdMetricDaily(
                    id=stable_id(store_id, "ad_metric", c, day),
                    store_id=store_id,
                    campaign_id=campaigns[c].id,
                    metric_date=today,
                    spend=spend,
                    currency=config.currency,
                    impressions=impressions,
                    clicks=clicks,
                    attributed_purchases=round(ad_orders[c] * truth.attribution_bias),
                    attributed_revenue=money(ad_net[c] * Decimal(str(truth.attribution_bias))),
                )
            )

        for i, state in enumerate(states):
            pipeline_units = sum(u for _, u in state.pipeline)
            if state.on_hand + pipeline_units <= state.truth.reorder_point:
                state.pipeline.append(
                    (day + state.truth.lead_time_days, state.truth.reorder_quantity)
                )
            inventory.append(
                InventorySnapshot(
                    id=stable_id(store_id, "inventory", i, day),
                    store_id=store_id,
                    product_id=state.product.id,
                    snapshot_date=today,
                    units_on_hand=state.on_hand,
                )
            )

    data = GeneratedStore(
        store=store,
        products=tuple(s.product for s in states),
        orders=tuple(builder.orders),
        lines=tuple(builder.lines),
        refunds=tuple(builder.refunds),
        inventory=tuple(inventory),
        campaigns=tuple(campaigns),
        campaign_products=tuple(promoted),
        ad_metrics=tuple(metrics),
        cost_items=tuple(_cost_items(config, rng, store_id)),
        product_truth=tuple(s.truth for s in states),
        campaign_truth=tuple(campaign_truth),
        lost_sales_units=builder.lost_sales_units,
    )
    return apply_faults(data, faults, config.seed)


def _products(
    config: GeneratorConfig, rng: np.random.Generator, store_id: UUID
) -> list[_ProductState]:
    count = int(rng.integers(config.products_min, config.products_max + 1))
    states: list[_ProductState] = []
    for i in range(count):
        price = Decimal(int(rng.integers(9, 150))) + Decimal("0.99")
        initial_cost = money(float(price) * rng.uniform(0.25, 0.6))
        schedule = [(0, initial_cost)]
        if rng.random() < 0.3:
            change_day = int(rng.integers(config.days // 4, config.days - config.days // 4))
            schedule.append((change_day, money(float(initial_cost) * rng.uniform(1.05, 1.25))))
        demand = float(rng.gamma(2.0, 1.2)) + 0.3
        lead_time = int(rng.integers(5, 31))
        product_id = stable_id(store_id, "product", i)
        name = f"{ADJECTIVES[i % len(ADJECTIVES)]} {NOUNS[(i * 7) % len(NOUNS)]} {i + 1}"
        truth = ProductTruth(
            product_id=product_id,
            base_daily_demand=demand,
            refund_rate=float(rng.uniform(0.01, 0.12)),
            lead_time_days=lead_time,
            reorder_point=math.ceil(demand * (lead_time + 7)),
            reorder_quantity=math.ceil(demand * 30),
        )
        product = Product(
            id=product_id,
            store_id=store_id,
            sku=f"SKU-{i + 1:03d}",
            name=name,
            price=price,
            unit_cost=schedule[-1][1],
            unit_fee=money(rng.uniform(0.4, 2.5)),
            currency=config.currency,
            supplier_lead_time_days=lead_time,
        )
        on_hand = math.ceil(demand * rng.uniform(20.0, 45.0))
        states.append(_ProductState(product, truth, schedule, on_hand))
    return states


def _campaigns(
    config: GeneratorConfig,
    rng: np.random.Generator,
    store_id: UUID,
    states: list[_ProductState],
) -> tuple[list[AdCampaign], list[AdCampaignProduct], list[CampaignTruth]]:
    count = int(rng.integers(config.campaigns_min, config.campaigns_max + 1))
    campaigns: list[AdCampaign] = []
    links: list[AdCampaignProduct] = []
    truths: list[CampaignTruth] = []
    for c in range(count):
        campaign_id = stable_id(store_id, "campaign", c)
        size = int(rng.integers(1, min(5, len(states)) + 1))
        chosen = sorted(int(i) for i in rng.choice(len(states), size=size, replace=False))
        a = float(rng.uniform(1.5, 12.0))
        campaigns.append(
            AdCampaign(
                id=campaign_id,
                store_id=store_id,
                external_id=f"cmp_{c + 1:02d}",
                name=f"Campaign {c + 1}",
                platform="meta",
                currency=config.currency,
                daily_budget=money(rng.uniform(20.0, 300.0)),
            )
        )
        links.extend(
            AdCampaignProduct(
                store_id=store_id, campaign_id=campaign_id, product_id=states[i].product.id
            )
            for i in chosen
        )
        truths.append(
            CampaignTruth(
                campaign_id=campaign_id,
                a=a,
                b=float(rng.uniform(0.004, 0.03)),
                noise_sd=0.1 * a,
                attribution_bias=round(float(rng.uniform(0.9, 1.35)), 4),
                start_day=int(rng.integers(0, config.days // 3)),
            )
        )
    return campaigns, links, truths


def _sell(builder: _Builder, states: list[_ProductState], first: int, day: int) -> Decimal | None:
    """Create one order (possibly with a cross-sell line). Returns its net amount, or None when
    the demanded product is out of stock (a lost sale)."""
    config, rng = builder.config, builder.rng
    wanted = [first]
    if len(states) > 1 and rng.random() < float(config.cross_sell_probability):
        other = int(rng.integers(0, len(states) - 1))
        wanted.append(other if other < first else other + 1)
    quantities: list[tuple[int, int]] = []
    for index in wanted:
        qty = 2 if rng.random() < 0.1 else 1
        qty = min(qty, states[index].on_hand)
        if qty == 0:
            builder.lost_sales_units += 1
            if index == first:
                return None
            continue
        quantities.append((index, qty))
    seq = len(builder.orders)
    order_id = stable_id(builder.store_id, "order", seq)
    ordered_at = _midnight(config.start_date + timedelta(days=day)) + timedelta(
        seconds=int(rng.integers(0, 86_400))
    )
    discounted = rng.random() < float(config.discount_probability)
    lines: list[OrderLine] = []
    for n, (index, qty) in enumerate(quantities):
        state = states[index]
        state.on_hand -= qty
        gross = state.product.price * qty
        discount = money(gross * config.discount_rate) if discounted else Decimal(0)
        net = gross - discount
        lines.append(
            OrderLine(
                id=stable_id(builder.store_id, "line", seq, n),
                store_id=builder.store_id,
                order_id=order_id,
                product_id=state.product.id,
                quantity=qty,
                unit_price=state.product.price,
                discount_amount=discount,
                tax_amount=money(net * config.tax_rate),
                unit_cost_at_sale=state.cost_on(day),
                unit_fee_at_sale=state.product.unit_fee,
                currency=config.currency,
            )
        )
    subtotal = sum((line.net_amount for line in lines), Decimal(0))
    tax = sum((line.tax_amount for line in lines), Decimal(0))
    shipping = Decimal(0) if subtotal >= config.free_shipping_threshold else config.shipping_fee
    fee = money((subtotal + tax + shipping) * config.payment_fee_rate + config.payment_fee_fixed)
    builder.orders.append(
        Order(
            id=order_id,
            store_id=builder.store_id,
            external_id=f"#{1001 + seq}",
            ordered_at=ordered_at,
            currency=config.currency,
            shipping_amount=shipping,
            payment_fee_amount=fee,
        )
    )
    builder.lines.extend(lines)
    for (index, _), line in zip(quantities, lines, strict=True):
        if rng.random() < states[index].truth.refund_rate:
            refunded_at = ordered_at + timedelta(days=int(rng.integers(2, 21)), hours=3)
            if refunded_at < builder.horizon_end:
                builder.refunds.append(
                    Refund(
                        id=stable_id(builder.store_id, "refund", line.id),
                        store_id=builder.store_id,
                        order_id=order_id,
                        order_line_id=line.id,
                        refunded_at=refunded_at,
                        amount=line.net_amount,
                        quantity=line.quantity,
                        currency=config.currency,
                        reason="customer_return",
                    )
                )
    return subtotal


def _cost_items(
    config: GeneratorConfig, rng: np.random.Generator, store_id: UUID
) -> list[CostItem]:
    end = config.start_date + timedelta(days=config.days)
    months: list[tuple[date, date]] = []
    cursor = config.start_date.replace(day=1)
    while cursor < end:
        nxt = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        months.append((cursor, nxt))
        cursor = nxt
    items: list[CostItem] = []
    for k, (name, category, low, high) in enumerate(FIXED_COSTS):
        amount = money(rng.uniform(low, high)) if high > low else money(low)
        items.extend(
            CostItem(
                id=stable_id(store_id, "cost", k, first.isoformat()),
                store_id=store_id,
                name=name,
                category=category,
                amount=amount,
                currency=config.currency,
                period_start=first,
                period_end=nxt,
            )
            for first, nxt in months
        )
    return items
