"""Economic materiality: expected monthly profit impact of an incident, and alert severity.

Impact = the incident's Shapley contributions over the current window, scaled to 30 days:
- entities: the incident's products, the products its campaigns promote, and its campaigns
  (all their level-2 contributions: volume, mix, price, unit cost, fees, refunds, ad spend);
- store-level symptoms add the drivers they implicate, over every product (payment fee rate:
  fees; gross margin rate: mix, price, unit cost).

Uncertainty: a seeded block bootstrap (7-day blocks, resampled within each window) of the daily
figures, repeating the decomposition per resample. P10/P50/P90 of the 30-day scaled impact.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from app.causes.drivers import LEVEL1_DRIVERS, Driver
from app.causes.noise import BLOCK_DAYS, DailyFigures, decompose_totals
from app.detection.incidents import EntityGraph
from app.detection.models import OUT_OF_STOCK_NOTE, AlertLevel, Symptom
from app.facts.model import ScopeKind
from app.settings.models import Materiality

METHOD = "block_bootstrap_shapley_v1"
MONTH_DAYS = 30
CENT = Decimal("0.01")

# Store-level symptoms -> the profit drivers they implicate.
STORE_DRIVERS: dict[str, frozenset[Driver]] = {
    "store_payment_fee_rate_z": frozenset({Driver.FEES}),
    "store_payment_fee_rate_cusum": frozenset({Driver.FEES}),
    "store_gross_margin_rate_z": frozenset({Driver.MIX, Driver.PRICE, Driver.UNIT_COST}),
    "store_gross_margin_rate_cusum": frozenset({Driver.MIX, Driver.PRICE, Driver.UNIT_COST}),
}


@dataclass(frozen=True)
class ImpactScope:
    products: frozenset[UUID]
    campaigns: frozenset[UUID]
    store_drivers: frozenset[Driver]


@dataclass(frozen=True)
class MonthlyImpact:
    """Monthly profit change (negative = loss), as P10/P50/P90."""

    p10: Decimal
    p50: Decimal
    p90: Decimal

    @property
    def loss(self) -> Decimal:
        return max(-self.p50, Decimal(0))


def impact_scope(symptoms: Iterable[Symptom], graph: EntityGraph) -> ImpactScope:
    products: set[UUID] = set()
    campaigns: set[UUID] = set()
    drivers: set[Driver] = set()
    for s in symptoms:
        entity = s.entity
        if entity.kind is ScopeKind.PRODUCT and entity.id is not None:
            products.add(entity.id)
        elif entity.kind is ScopeKind.CAMPAIGN and entity.id is not None:
            campaigns.add(entity.id)
            products |= graph.promoted.get(entity.id, frozenset())
        else:
            drivers |= STORE_DRIVERS.get(s.detector_id, frozenset())
    return ImpactScope(frozenset(products), frozenset(campaigns), frozenset(drivers))


def _block_resample(
    rng: np.random.Generator, start: int, length: int, resamples: int
) -> NDArray[np.int64]:
    """Day indexes of `resamples` circular block-bootstrap copies of [start, start + length)."""
    blocks = -(-length // BLOCK_DAYS)
    offsets = rng.integers(0, length, size=(resamples, blocks))
    days = (offsets[:, :, None] + np.arange(BLOCK_DAYS)[None, None, :]) % length
    return start + days.reshape(resamples, -1)[:, :length]


def estimate_monthly_impact(
    figures: DailyFigures,
    product_ids: list[UUID],
    campaign_ids: list[UUID],
    scope: ImpactScope,
    *,
    baseline: tuple[int, int],
    current: tuple[int, int],
    rng: np.random.Generator,
    resamples: int,
) -> MonthlyImpact:
    """Bootstrap distribution of the scope's contribution change, scaled to 30 days."""
    length = current[1] - current[0]
    base_idx = _block_resample(rng, baseline[0], baseline[1] - baseline[0], resamples)
    cur_idx = _block_resample(rng, current[0], length, resamples)
    # The first "resample" is the observed windows themselves.
    base_idx[0] = np.arange(baseline[0], baseline[1])
    cur_idx[0] = np.arange(current[0], current[1])
    base, cur = figures.window_totals(base_idx), figures.window_totals(cur_idx)
    in_products = np.array([p in scope.products for p in product_ids], dtype=bool)
    in_campaigns = np.array([c in scope.campaigns for c in campaign_ids], dtype=bool)
    entity_part = decompose_totals(base, cur, in_products, in_campaigns)
    total = sum(
        (entity_part[d] for d in LEVEL1_DRIVERS if d is not Driver.FIXED_COSTS),
        np.zeros(resamples),
    )
    if scope.store_drivers:
        store_part = decompose_totals(base, cur, None, np.zeros_like(in_campaigns))
        # Drivers already counted for the incident's own products are not counted twice.
        for driver in scope.store_drivers:
            total = total + store_part[driver] - entity_part[driver]
    monthly = total * MONTH_DAYS / length
    p10, p50, p90 = (Decimal(repr(float(np.percentile(monthly, q)))) for q in (10, 50, 90))
    return MonthlyImpact(p10.quantize(CENT), p50.quantize(CENT), p90.quantize(CENT))


def alert_level(
    impact: MonthlyImpact,
    materiality: Materiality,
    trailing_contribution: Decimal,
    *,
    ads_on_out_of_stock: bool,
) -> tuple[AlertLevel, bool]:
    """(level, material). Material: the P50 loss meets both thresholds (SPEC section 6)."""
    relative = materiality.relative * max(trailing_contribution, Decimal(0))
    material = impact.loss >= materiality.absolute and impact.loss >= relative and impact.loss > 0
    if ads_on_out_of_stock or (material and impact.loss >= 10 * materiality.absolute):
        return AlertLevel.CRITICAL, material
    if material and impact.loss >= 3 * materiality.absolute:
        return AlertLevel.HIGH, material
    if material:
        return AlertLevel.NORMAL, material
    return AlertLevel.WATCHLIST, material


def ads_on_out_of_stock(symptoms: Iterable[Symptom]) -> bool:
    return any(
        s.detector_id == "product_cover_below_lead_time" and s.note == OUT_OF_STOCK_NOTE
        for s in symptoms
    )
