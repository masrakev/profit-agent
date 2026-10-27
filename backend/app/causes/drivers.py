"""Profit drivers and the exact two-level Shapley decomposition of a net profit change.

Net profit over a period, written with driver factors:

    NP = sum_p Q * s_p * (P_p - C_p - F_p) - sum_p R_p - sum_c A_c - K

    Q    volume: total units sold                      s_p  mix: product share of units
    P_p  price: net revenue per unit                   C_p  unit cost: COGS per unit
    F_p  fees: (per-unit + payment) fees per unit      R_p  refunds of the product
    A_c  ad spend of the campaign                      K    fixed costs

The first term is a sum of per-product games, each depending on five drivers; the other terms
are additive. Shapley values are linear in the game, so the level-1 value of a driver is the sum
of its per-product (or per-campaign) values: level 2 is exact and sums to level 1, and level 1
sums to the total change (efficiency). A driver whose factors did not change is a null player
and gets exactly zero.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from uuid import UUID

from app.causes.shapley import shapley


class Driver(StrEnum):
    VOLUME = "volume"
    MIX = "mix"
    PRICE = "price"
    UNIT_COST = "unit_cost"
    FEES = "fees"
    REFUNDS = "refunds"
    AD_SPEND = "ad_spend"
    FIXED_COSTS = "fixed_costs"


PRODUCT_GAME_DRIVERS = (Driver.VOLUME, Driver.MIX, Driver.PRICE, Driver.UNIT_COST, Driver.FEES)
LEVEL1_DRIVERS = (*PRODUCT_GAME_DRIVERS, Driver.REFUNDS, Driver.AD_SPEND, Driver.FIXED_COSTS)


@dataclass(frozen=True)
class ProductFigures:
    revenue: Decimal = Decimal(0)
    units: Decimal = Decimal(0)
    cogs: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    refunds: Decimal = Decimal(0)


@dataclass(frozen=True)
class PeriodFigures:
    products: Mapping[UUID, ProductFigures] = field(default_factory=dict)
    ad_spend: Mapping[UUID, Decimal] = field(default_factory=dict)
    fixed_costs: Decimal = Decimal(0)

    @property
    def total_units(self) -> Fraction:
        return sum((Fraction(p.units) for p in self.products.values()), Fraction(0))

    def net_profit(self) -> Fraction:
        products = sum(
            (Fraction(p.revenue - p.cogs - p.fees - p.refunds) for p in self.products.values()),
            Fraction(0),
        )
        ads = sum((Fraction(a) for a in self.ad_spend.values()), Fraction(0))
        return products - ads - Fraction(self.fixed_costs)


@dataclass(frozen=True)
class Decomposition:
    delta: Fraction
    level1: dict[Driver, Fraction]
    # Driver -> (entity kind, id) -> contribution. Products for product drivers and refunds,
    # campaigns for ad spend; fixed costs have no level 2.
    level2: dict[Driver, dict[tuple[str, UUID], Fraction]]


def _per_unit(amount: Decimal, units: Decimal) -> Fraction | None:
    return Fraction(amount) / Fraction(units) if units else None


@dataclass(frozen=True)
class _Factors:
    q: Fraction
    s: Fraction
    price: Fraction
    cost: Fraction
    fee: Fraction


def _factors(
    mine: ProductFigures, other: ProductFigures, q: Fraction, other_q: Fraction
) -> _Factors:
    """Driver factors of one product in one period. A per-unit value that is undefined because
    nothing sold takes the other period's value (it multiplies zero units, so the period's
    profit is unchanged, and the driver gets no spurious contribution)."""

    def pick(attr: str) -> Fraction:
        value = _per_unit(getattr(mine, attr), mine.units)
        if value is None:
            value = _per_unit(getattr(other, attr), other.units)
        return value or Fraction(0)

    if q:
        share = Fraction(mine.units) / q
    elif other_q:
        share = Fraction(other.units) / other_q
    else:
        share = Fraction(0)
    return _Factors(q, share, pick("revenue"), pick("cogs"), pick("fees"))


def decompose(baseline: PeriodFigures, current: PeriodFigures) -> Decomposition:
    q_b, q_c = baseline.total_units, current.total_units
    level1 = dict.fromkeys(LEVEL1_DRIVERS, Fraction(0))
    level2: dict[Driver, dict[tuple[str, UUID], Fraction]] = {d: {} for d in LEVEL1_DRIVERS}
    empty = ProductFigures()
    for pid in sorted(set(baseline.products) | set(current.products), key=str):
        b = baseline.products.get(pid, empty)
        c = current.products.get(pid, empty)
        fb, fc = _factors(b, c, q_b, q_c), _factors(c, b, q_c, q_b)

        def margin(players: frozenset[Driver], fb: _Factors = fb, fc: _Factors = fc) -> Fraction:
            def x(d: Driver, attr: str) -> Fraction:
                factor: Fraction = getattr(fc if d in players else fb, attr)
                return factor

            return (
                x(Driver.VOLUME, "q")
                * x(Driver.MIX, "s")
                * (x(Driver.PRICE, "price") - x(Driver.UNIT_COST, "cost") - x(Driver.FEES, "fee"))
            )

        start = margin(frozenset())

        def gain(players: frozenset[Driver], start: Fraction = start) -> Fraction:
            return margin(players) - start

        values = shapley(PRODUCT_GAME_DRIVERS, gain)
        for driver, value in values.items():
            level2[driver][("product", pid)] = value
            level1[driver] += value
        refund = -(Fraction(c.refunds) - Fraction(b.refunds))
        level2[Driver.REFUNDS][("product", pid)] = refund
        level1[Driver.REFUNDS] += refund
    for cid in sorted(set(baseline.ad_spend) | set(current.ad_spend), key=str):
        change = -(
            Fraction(current.ad_spend.get(cid, Decimal(0)))
            - Fraction(baseline.ad_spend.get(cid, Decimal(0)))
        )
        level2[Driver.AD_SPEND][("campaign", cid)] = change
        level1[Driver.AD_SPEND] += change
    level1[Driver.FIXED_COSTS] = -(Fraction(current.fixed_costs) - Fraction(baseline.fixed_costs))
    delta = current.net_profit() - baseline.net_profit()
    if sum(level1.values(), Fraction(0)) != delta:  # pragma: no cover - guarded by property tests
        raise ArithmeticError("Shapley efficiency violated")
    return Decomposition(delta, level1, level2)
