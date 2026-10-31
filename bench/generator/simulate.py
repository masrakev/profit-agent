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

from app.domain.hashing import sha256_hex
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
from bench.generator.model import (
    CampaignTruth,
    GeneratedStore,
    Intervention,
    ProductTruth,
    Restock,
)

CENT = Decimal("0.01")
DYNAMICS_STREAM = int(sha256_hex("long_history")[:16], 16)  # random stream of the dynamics
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
    sold_today: int = 0
    sold_history: list[int] = field(default_factory=list)
    # Adaptive policy: base demand plus the expected ad-driven demand of promoting campaigns.
    planned_daily_demand: float = 0.0

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
    order_campaigns: list[tuple[UUID, UUID]] = field(default_factory=list)
    lost_sales_units: int = 0

    @property
    def horizon_end(self) -> datetime:
        return _midnight(self.config.start_date + timedelta(days=self.config.days))


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


def store_id_for(config: GeneratorConfig) -> UUID:
    return uuid5(STORE_NAMESPACE, f"{config.seed}:{config.fingerprint}")


def _budget_multiplier(
    interventions: Sequence[Intervention | Restock], campaign: int, day: int
) -> float:
    """The latest intervention on the campaign in force on `day` (multipliers do not compound)."""
    active = [
        i
        for i in interventions
        if isinstance(i, Intervention) and i.campaign == campaign and i.day <= day
    ]
    return max(active, key=lambda i: i.day).budget_multiplier if active else 1.0


def demand_scale(config: GeneratorConfig) -> list[float] | None:
    """The market's size each day relative to day 0, with long-history dynamics; None without.

    Log level: the growth rate (a random walk around `growth_per_year`, its sd reaching
    `growth_drift` after a year) accumulated day by day, plus regime shifts (Poisson,
    `regime_changes_per_year`); times a yearly cycle peaking on day `yearly_peak` of the year.
    """
    h = config.long_history
    if h is None:
        return None
    rng = np.random.default_rng([config.seed, DYNAMICS_STREAM])
    growth, level, out = float(h.growth_per_year), 0.0, []
    for day in range(config.days):
        if day:
            growth += float(h.growth_drift) * float(rng.normal()) / math.sqrt(365)
            level += growth / 365
            if rng.random() < float(h.regime_changes_per_year) / 365:
                level += float(rng.normal(0.0, float(h.regime_shift_sd)))
        doy = (config.start_date + timedelta(days=day)).timetuple().tm_yday
        cycle = math.cos(2 * math.pi * (doy - h.yearly_peak) / 365.25)
        out.append(math.exp(level) * (1.0 + float(h.yearly_amplitude) * cycle))
    return out


def generate(
    config: GeneratorConfig,
    faults: Sequence[Fault] = (),
    interventions: Sequence[Intervention | Restock] = (),
) -> GeneratedStore:
    rng = np.random.default_rng(config.seed)
    store_id = store_id_for(config)  # the same store, whatever the owner does
    store = Store(
        store_id=store_id,
        name=config.store_name or f"Bench store {config.seed}",
        currency=config.currency,
        synthetic=True,
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
    if config.reorder_policy == "adaptive":
        _plan_stock(states, campaigns, campaign_truth, promoted_by_campaign)

    scale = demand_scale(config)
    for day in range(config.days):
        today = config.start_date + timedelta(days=day)
        dow = float(config.weekly_seasonality[today.weekday()])
        if scale is not None:
            dow *= scale[day]  # organic demand and the ad response follow the market
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
            budget = float(campaigns[c].daily_budget) * _budget_multiplier(interventions, c, day)
            if budget <= 0:
                continue  # paused: no spend and no ad-driven demand
            spend = money(budget * rng.uniform(0.75, 1.05))
            spend_today[c] = spend
            reach = truth.a if scale is None else truth.a * scale[day]
            expected = reach * (1.0 - math.exp(-truth.b * float(spend)))
            purchases = max(0, round(expected + rng.normal(0.0, truth.noise_sd)))
            candidates = promoted_by_campaign[campaigns[c].id]
            events.extend((int(rng.choice(candidates)), c) for _ in range(purchases))
        order = rng.permutation(len(events))

        ad_orders = dict.fromkeys(spend_today, 0)
        ad_net = {c: Decimal(0) for c in spend_today}
        for k in order:
            product_index, campaign_index = events[int(k)]
            sold = _sell(builder, states, product_index, day)
            if sold is not None and campaign_index >= 0:
                order_id, net = sold
                ad_orders[campaign_index] += 1
                ad_net[campaign_index] += net
                builder.order_campaigns.append((order_id, campaigns[campaign_index].id))

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
            state.sold_history.append(state.sold_today)
            state.sold_today = 0
            pipeline_units = sum(u for _, u in state.pipeline)
            reorder_point, reorder_quantity = _reorder_levels(config, state)
            if state.on_hand + pipeline_units <= reorder_point:
                state.pipeline.append((day + state.truth.lead_time_days, reorder_quantity))
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
        config=config,
        order_campaigns=tuple(builder.order_campaigns),
        interventions=tuple(interventions),
    )
    return apply_faults(data, faults, config.seed)


def _plan_stock(
    states: list[_ProductState],
    campaigns: list[AdCampaign],
    truths: list[CampaignTruth],
    promoted_by_campaign: dict[UUID, list[int]],
) -> None:
    """Plan for ad-driven demand: scale initial stock and the reorder rate floor by it."""
    for state in states:
        state.planned_daily_demand = state.truth.base_daily_demand
    for campaign, truth in zip(campaigns, truths, strict=True):
        indexes = promoted_by_campaign[campaign.id]
        expected = truth.a * (1.0 - math.exp(-truth.b * float(campaign.daily_budget)))
        for i in indexes:
            states[i].planned_daily_demand += expected / len(indexes)
    for state in states:
        scale = state.planned_daily_demand / state.truth.base_daily_demand
        state.on_hand = math.ceil(state.on_hand * scale)


def _reorder_levels(config: GeneratorConfig, state: _ProductState) -> tuple[int, int]:
    if config.reorder_policy == "static":
        return state.truth.reorder_point, state.truth.reorder_quantity
    week, fortnight = state.sold_history[-7:], state.sold_history[-14:]
    observed = max(
        sum(week) / 7 if len(week) == 7 else 0.0,
        sum(fortnight) / 14 if len(fortnight) == 14 else 0.0,
    )
    rate = max(observed, state.planned_daily_demand)
    lead = state.truth.lead_time_days
    return (
        math.ceil(rate * (3 * lead + config.safety_stock_days)),
        max(1, math.ceil(rate * (30 + lead))),
    )


def _products(
    config: GeneratorConfig, rng: np.random.Generator, store_id: UUID
) -> list[_ProductState]:
    count = int(rng.integers(config.products_min, config.products_max + 1))
    states: list[_ProductState] = []
    for i in range(count):
        price = Decimal(int(rng.integers(9, 150))) + Decimal("0.99")
        initial_cost = money(float(price) * rng.uniform(0.25, 0.6))
        schedule = [(0, initial_cost)]
        if rng.random() < float(config.cost_change_probability):
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
            reorder_point=math.ceil(demand * (lead_time + config.safety_stock_days)),
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
        low, high = config.initial_stock_days
        on_hand = math.ceil(demand * rng.uniform(float(low), float(high)))
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
        budget = float(rng.uniform(20.0, 300.0))
        b = float(rng.uniform(0.004, 0.03))
        bias = round(float(rng.uniform(0.9, 1.35)), 4)
        start_day = int(rng.integers(0, config.days // 3))
        if config.campaign_budget_policy != "random":
            b, budget = _profitable_budget(config, rng, a, b, [states[i] for i in chosen])
        campaigns.append(
            AdCampaign(
                id=campaign_id,
                store_id=store_id,
                external_id=f"cmp_{c + 1:02d}",
                name=f"Campaign {c + 1}",
                platform="meta",
                currency=config.currency,
                daily_budget=money(budget),
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
                b=b,
                noise_sd=0.1 * a,
                attribution_bias=bias,
                start_day=start_day,
            )
        )
    return campaigns, links, truths


def _profitable_budget(
    config: GeneratorConfig,
    rng: np.random.Generator,
    a: float,
    b: float,
    promoted: list[_ProductState],
) -> tuple[float, float]:
    """Budget below the profit-maximising spend of a * (1 - exp(-b * s)) * margin - s, or past
    it with the "past_optimal" policy.

    Expected profit is concave in spend and zero at zero spend, so any budget between zero and
    the optimum s* = ln(a * b * margin) / b is profitable. `b` is raised when needed so that the
    optimum is comfortably positive (a * b * margin >= 3). Past the optimum, the next unit of
    spend brings less margin than it costs, while still bringing sales.
    """
    fee_rate = float(config.payment_fee_rate) * (1 + float(config.tax_rate))
    margins = [
        (
            float(s.product.price) * (1 - fee_rate)
            - float(s.cost_schedule[-1][1])
            - float(s.product.unit_fee)
            - float(config.payment_fee_fixed)
        )
        - float(s.product.price) * s.truth.refund_rate
        for s in promoted
    ]
    margin = max(sum(margins) / len(margins), 1.0)
    b = max(b, 3.0 / (a * margin))
    optimum = math.log(a * b * margin) / b
    low, high = (1.4, 2.0) if config.campaign_budget_policy == "past_optimal" else (0.5, 0.9)
    return b, optimum * float(rng.uniform(low, high))


def _sell(
    builder: _Builder, states: list[_ProductState], first: int, day: int
) -> tuple[UUID, Decimal] | None:
    """Create one order (possibly with a cross-sell line). Returns its id and net amount, or None
    when the demanded product is out of stock (a lost sale)."""
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
        state.sold_today += qty
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
    return order_id, subtotal


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
