"""Detectors on hand-built daily series: each fires on its pattern and stays quiet on noise."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import numpy as np
import pytest

from app.detection import detectors as d
from app.detection.config import default_config, load_config
from app.detection.models import SymptomCategory
from app.detection.series import CampaignSeries, ProductSeries, StoreSeries
from app.detection.stats import (
    as_floats,
    binomial_sf,
    cusum_path,
    episodes,
    poisson_residuals,
    rate_increase_p_value,
    ratio_series,
    robust_scale,
    robust_z,
    rolling_sum,
    standardize,
)

DAYS = 120
CFG = default_config()
P, Q = UUID(int=1), UUID(int=2)
C = UUID(int=10)
D = Decimal


def flat(value: float, days: int = DAYS) -> list[Decimal]:
    return [D(str(value))] * days


def noisy(mean: float, seed: int, days: int = DAYS) -> list[Decimal]:
    rng = np.random.default_rng(seed)
    return [D(int(x)) for x in rng.poisson(mean, days)]


def product(
    pid: UUID = P,
    *,
    units: list[Decimal] | None = None,
    price: float = 10.0,
    cost: float = 4.0,
    fee: float = 1.0,
    lead: int | None = 10,
) -> ProductSeries:
    u = units if units is not None else noisy(20, int(pid))
    return ProductSeries(
        product_id=pid,
        lead_time_days=lead,
        revenue=[x * D(str(price)) for x in u],
        units=list(u),
        cogs=[x * D(str(cost)) for x in u],
        unit_fees=[x * D(str(fee)) for x in u],
        payment_fees=[x * D(str(price * 0.03)) for x in u],
        refunds=flat(0),
        refunded_units=flat(0),
        lines=list(u),
        refund_events=flat(0),
        on_hand=[500] * DAYS,
    )


def campaign(
    *,
    spend: list[Decimal] | None = None,
    purchases: list[Decimal] | None = None,
    revenue: list[Decimal] | None = None,
) -> CampaignSeries:
    p = purchases if purchases is not None else noisy(10, 99)
    return CampaignSeries(
        campaign_id=C,
        promoted=(P,),
        spend=spend if spend is not None else flat(50),
        attributed_purchases=p,
        attributed_revenue=revenue if revenue is not None else [x * 10 for x in p],
    )


def store(*products: ProductSeries, campaigns: tuple[CampaignSeries, ...] = ()) -> StoreSeries:
    s = StoreSeries(start=date(2026, 6, 1), days=DAYS)
    s.products = {p.product_id: p for p in products}
    s.campaigns = {c.campaign_id: c for c in campaigns}
    return s


def fired(findings: list[d.Finding], detector: str) -> list[d.Finding]:
    return [f for f in findings if f.detector_id == detector]


# --- stats -------------------------------------------------------------------------------------


def test_stats_primitives() -> None:
    assert rolling_sum([D(1)] * 4, 2) == [None, D(2), D(2), D(2)]
    assert ratio_series([D(1), D(2), None], [D(2), D(0), D(1)]) == [0.5, None, None]
    assert as_floats([D(1), None]) == [1.0, None]
    assert robust_scale([1.0, 2.0, 3.0], 0.0, 0.0) == (2.0, pytest.approx(1.4826))
    assert robust_scale([5.0, 5.0], 0.1, 0.0) == (5.0, 0.5)  # MAD 0: relative floor applies
    z = robust_z(
        [1.0] * 10 + [5.0], window=1, baseline=5, direction=1, rel_floor=0.1, abs_floor=1e-9
    )
    assert z[-1] == pytest.approx(40.0)
    assert z[0] is None
    assert (
        robust_z(
            [1.0] * 10,
            window=1,
            baseline=5,
            direction=1,
            rel_floor=0.1,
            abs_floor=1e-9,
            min_baseline_level=2.0,
        )[-1]
        is None
    )
    assert episodes([0, 2, 2, 2, 0, 2, None], 1.0, 2) == [d.Episode(1, 2, 3, 2)]
    assert cusum_path([1.0, None, 1.0, -5.0], direction=1, k=0.5) == [0.5, None, 1.0, 0.0]
    assert standardize(
        [1.0, 1.0, 3.0], reference_start=0, reference_days=2, rel_floor=0.5, abs_floor=0.0
    ) == [None, None, 4.0]
    assert standardize(
        [None, None, 1.0], reference_start=0, reference_days=2, rel_floor=0.1, abs_floor=0.0
    ) == [None, None, None]
    assert poisson_residuals([D(9), D(1)], [4.0, None]) == [2.5, None]
    assert binomial_sf(0, 3, 0.5) == 1.0
    assert binomial_sf(4, 3, 0.5) == 0.0
    assert binomial_sf(3, 3, 0.5) == pytest.approx(0.125)
    assert rate_increase_p_value(5, 10.0, 5, 10.0) > 0.5
    assert rate_increase_p_value(10, 10.0, 1, 10.0) < 0.01


# --- statistical detectors ---------------------------------------------------------------------


def test_unit_cost_step_fires_after_persistence() -> None:
    p = product()
    p.cogs = [u * (D(4) if t < 80 else D("4.40")) for t, u in enumerate(p.units)]
    found = fired(d.product_metrics(store(p), CFG), "product_unit_cost_z")
    assert [f.episode.confirmed for f in found] == [80 + CFG.robust_z.persist_days - 1]
    assert found[0].facts[0].formula_id == "cogs"
    assert not fired(d.product_metrics(store(product()), CFG), "product_unit_cost_z")


def test_unit_fee_step_and_units_drop() -> None:
    p = product(units=[D(30)] * 80 + [D(2)] * 40)
    p.unit_fees = [u * (D(1) if t < 90 else D(2)) for t, u in enumerate(p.units)]
    found = d.product_metrics(store(p), CFG)
    assert fired(found, "product_units_z")[0].episode.start == 80
    assert fired(found, "product_unit_fee_z")[0].episode.start == 90


def test_store_rates_step_and_drift() -> None:
    p, q = product(P), product(Q)
    p.payment_fees = [x * (D("0.3") if t < 70 else D("0.45")) for t, x in enumerate(p.units)]
    q.cogs = [x * (D(4) + D("0.02") * max(0, t - 60)) for t, x in enumerate(q.units)]
    found = d.store_metrics(store(p, q), CFG)
    assert fired(found, "store_payment_fee_rate_z") or fired(found, "store_payment_fee_rate_cusum")
    drift = fired(found, "store_gross_margin_rate_cusum")
    assert drift
    assert drift[0].episode.confirmed > 60
    quiet = d.store_metrics(store(product(P), product(Q)), CFG)
    assert not quiet


def test_campaign_cpa_drift_and_quiet_baseline() -> None:
    healthy = campaign()
    assert not d.campaign_cpa(store(product(), campaigns=(healthy,)), CFG)
    drop = [x if t < 70 else D(int(x) // 2) for t, x in enumerate(noisy(10, 99))]
    found = d.campaign_cpa(store(product(), campaigns=(campaign(purchases=drop),)), CFG)
    cusum = fired(found, "campaign_cpa_cusum")
    assert cusum
    assert 70 <= cusum[0].episode.confirmed < 85
    never_spent = campaign(spend=flat(0))
    assert not d.campaign_cpa(store(product(), campaigns=(never_spent,)), CFG)
    too_few = campaign(purchases=flat(0.5))
    assert not d.campaign_cpa(store(product(), campaigns=(too_few,)), CFG)


# --- business rules ----------------------------------------------------------------------------


def test_campaign_profit_negative() -> None:
    # Promoted products earn 47% contribution (10 - 4 - 1 - 0.30 per $10). Attributed revenue
    # 200/day -> attributed contribution 94/day vs spend 50: profitable; spend triples on day 80.
    c = campaign(spend=[D(50) if t < 80 else D(150) for t in range(DAYS)], revenue=flat(200))
    found = d.campaign_profit_negative(store(product(), campaigns=(c,)), CFG)
    assert found
    assert found[0].episode.start >= 80
    assert found[0].facts[0].formula_id == "campaign_profit"
    assert not d.campaign_profit_negative(
        store(product(), campaigns=(campaign(revenue=flat(200)),)), CFG
    )


def test_inventory_cover_below_lead_time_needs_promoting_spend() -> None:
    p = product(units=flat(10))
    p.on_hand = [500] * 70 + [0] * 50
    found = d.inventory_cover_below_lead_time(store(p, campaigns=(campaign(),)), CFG)
    assert found
    assert found[0].episode.start == 70
    assert not d.inventory_cover_below_lead_time(store(p), CFG)  # nothing promotes it
    p.on_hand = [None] * DAYS
    assert not d.inventory_cover_below_lead_time(store(p, campaigns=(campaign(),)), CFG)


def test_refund_rate_band() -> None:
    p = product(units=flat(10))
    rng = np.random.default_rng(3)
    rates = [0.05 if t < 75 else 0.3 for t in range(DAYS)]
    p.refund_events = [D(int(rng.binomial(10, r))) for r in rates]
    found = d.refund_rate_band(store(p), CFG)
    assert found
    assert found[0].episode.start >= 75
    p.refund_events = [D(int(rng.binomial(10, 0.05))) for _ in range(DAYS)]
    assert not d.refund_rate_band(store(p), CFG)


def test_attribution_collapse_only_when_sales_hold() -> None:
    p = product(units=flat(20))
    revenue = [D(150) if t < 70 else D(10) for t in range(DAYS)]
    collapsed = d.attribution_collapse(store(p, campaigns=(campaign(revenue=revenue),)), CFG)
    assert collapsed
    assert collapsed[0].category is SymptomCategory.DATA_QUALITY
    # Attributed revenue 150 -> 60/day while real sales fall 30/day (within the stability band):
    # the sales drop explains more than 30% of the attributed drop, so purchases were really lost.
    lost = product(units=[D(20) if t < 70 else D(17) for t in range(DAYS)])
    partial = [D(150) if t < 70 else D(60) for t in range(DAYS)]
    assert not d.attribution_collapse(store(lost, campaigns=(campaign(revenue=partial),)), CFG)


def test_incrementality() -> None:
    purchases = [D(10) if t < 70 else D(16) for t in range(DAYS)]
    c = campaign(purchases=purchases, spend=flat(50))
    found = d.incrementality(store(product(units=flat(20)), campaigns=(c,)), CFG)
    assert found
    assert found[0].episode.start >= 70
    rising = product(units=[D(20) if t < 70 else D(26) for t in range(DAYS)])
    assert not d.incrementality(store(rising, campaigns=(c,)), CFG)


def test_attributed_symptoms_are_reclassified_by_a_collapse() -> None:
    p = product(units=flat(20))
    revenue = [D(150) if t < 70 else D(10) for t in range(DAYS)]
    purchases = [D(15) if t < 70 else D(1) for t in range(DAYS)]
    c = campaign(revenue=revenue, purchases=purchases)
    findings = d.run_detectors(store(p, campaigns=(c,)), CFG)
    attributed = [f for f in findings if f.detector_id in d.ATTRIBUTED_METRIC_DETECTORS]
    assert attributed
    assert all(f.category is SymptomCategory.DATA_QUALITY for f in attributed)
    assert all(f.note == "explained by an attribution collapse" for f in attributed)


def test_thresholds_file_is_versioned(tmp_path: object) -> None:
    assert CFG.version == 1
    assert load_config().robust_z == CFG.robust_z
