"""Detectors: statistical (robust z-score, CUSUM) and business rules over daily series.

Each detector returns `Finding`s: when a condition started and held long enough, on which entity,
and which facts (formula + scope) back it. The pipeline turns findings into `Symptom`s by
computing and persisting those facts for the finding's baseline and current windows.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID

from app.detection.config import DetectionConfig
from app.detection.models import OUT_OF_STOCK_NOTE, EntityRef, SymptomCategory
from app.detection.series import CampaignSeries, ProductSeries, StoreSeries
from app.detection.stats import (
    Episode,
    as_floats,
    benjamini_hochberg,
    cusum_path,
    cusum_start,
    episodes,
    normal_sf,
    poisson_residuals,
    rate_drop_change_point,
    rate_increase_p_value,
    ratio_series,
    robust_z,
    rolling_sum,
    standardize,
)
from app.facts.model import Scope

PROFIT = SymptomCategory.PROFITABILITY
DATA_QUALITY = SymptomCategory.DATA_QUALITY
ZERO = Decimal(0)
UP, DOWN = 1, -1

# Symptoms computed from platform-attributed numbers: explained away by an attribution collapse.
ATTRIBUTED_METRIC_DETECTORS = frozenset(
    {"campaign_cpa_z", "campaign_cpa_cusum", "campaign_profit_negative", "campaign_incrementality"}
)


@dataclass(frozen=True)
class FactRef:
    formula_id: str
    scope: Scope


@dataclass(frozen=True)
class Finding:
    detector_id: str
    entity: EntityRef
    metric: str
    category: SymptomCategory
    episode: Episode
    score: float  # peak statistic / its threshold: >= 1 when firing
    window_days: int
    baseline_days: int
    facts: tuple[FactRef, ...]
    note: str | None = None
    # Estimated day the change started; when set, the baseline facts end before it.
    change_point: int | None = None


def _scope(entity: EntityRef) -> Scope:
    return Scope(kind=entity.kind, id=entity.id)


def _refs(entity: EntityRef, *formula_ids: str) -> tuple[FactRef, ...]:
    return tuple(FactRef(f, _scope(entity)) for f in formula_ids)


def _sum(values: Sequence[Decimal], start: int, end: int) -> Decimal:
    return sum(values[max(start, 0) : end], ZERO)


# --- statistical detectors ---------------------------------------------------------------------
# Robust z-scores and CUSUMs run on *daily* values, which are (close to) independent from day to
# day, so the baseline median/MAD is well estimated and persistence over consecutive days means
# something. Ratios of daily sums cancel the weekly seasonality.


def _z_scores(
    cfg: DetectionConfig,
    series: Sequence[float | None],
    direction: int,
    *,
    rel_floor: float | None = None,
    min_level: float = 0.0,
) -> list[float | None]:
    z_cfg = cfg.robust_z
    return robust_z(
        series,
        window=1,
        baseline=z_cfg.baseline_days,
        direction=direction,
        rel_floor=rel_floor if rel_floor is not None else z_cfg.rel_floor,
        abs_floor=z_cfg.abs_floor,
        min_baseline_level=min_level,
    )


def _z_episode_findings(
    cfg: DetectionConfig,
    detector_id: str,
    entity: EntityRef,
    metric: str,
    scores: Sequence[float | None],
    facts: tuple[FactRef, ...],
    limit: float,
) -> list[Finding]:
    z_cfg = cfg.robust_z
    return [
        Finding(
            detector_id,
            entity,
            metric,
            PROFIT,
            e,
            e.peak / limit,
            z_cfg.persist_days,
            z_cfg.baseline_days,
            facts,
        )
        for e in episodes(scores, limit, z_cfg.persist_days)
    ]


def _z_findings(
    cfg: DetectionConfig,
    detector_id: str,
    entity: EntityRef,
    metric: str,
    series: Sequence[float | None],
    direction: int,
    facts: tuple[FactRef, ...],
    *,
    rel_floor: float | None = None,
    threshold: float | None = None,
    min_level: float = 0.0,
) -> list[Finding]:
    scores = _z_scores(cfg, series, direction, rel_floor=rel_floor, min_level=min_level)
    limit = threshold or cfg.robust_z.threshold
    return _z_episode_findings(cfg, detector_id, entity, metric, scores, facts, limit)


def bh_gate(
    scores: dict[UUID, list[float | None]],
    p_values: dict[UUID, list[float | None]],
    q: float,
) -> dict[UUID, list[float | None]]:
    """Benjamini-Hochberg across entities, day by day: a score survives only on days when its
    entity's test is rejected at false discovery rate `q` among that day's tests."""
    gated = {key: list(values) for key, values in scores.items()}
    days = max((len(v) for v in scores.values()), default=0)
    for t in range(days):
        tested = [(key, p[t]) for key, p in p_values.items() if p[t] is not None]
        if not tested:
            continue
        rejected = benjamini_hochberg([p for _, p in tested if p is not None], q)
        for (key, _), keep in zip(tested, rejected, strict=True):
            if not keep:
                gated[key][t] = None
    return gated


def _z_p_values(scores: Sequence[float | None]) -> list[float | None]:
    return [None if z is None else normal_sf(z) for z in scores]


def _cusum_findings(
    cfg: DetectionConfig,
    detector_id: str,
    entity: EntityRef,
    metric: str,
    standardized: Sequence[float | None],
    direction: int,
    facts: tuple[FactRef, ...],
    *,
    k: float | None = None,
    h: float | None = None,
) -> list[Finding]:
    c = cfg.cusum
    limit = c.h if h is None else h
    path = cusum_path(standardized, direction=direction, k=c.k if k is None else k)
    return [
        Finding(
            detector_id,
            entity,
            metric,
            PROFIT,
            e,
            e.peak / limit,
            c.current_days,
            c.reference_days,
            facts,
            change_point=cusum_start(path, e.start),
        )
        for e in episodes(path, limit, 1)
    ]


def _reference_start(values: Sequence[Decimal], warmup: int) -> int | None:
    first = next((i for i, v in enumerate(values) if v > 0), None)
    return None if first is None else max(first, warmup)


def campaign_cpa(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    """CPA up = fewer attributed purchases per unit of spend.

    z-score: daily purchases per spend against the trailing baseline (abrupt changes).
    CUSUM: daily Poisson residual of purchases against reference-period purchases per spend
    times today's spend (slow drifts).
    """
    c_cfg = cfg.cusum
    out: list[Finding] = []
    for c in series.campaigns.values():
        entity = EntityRef.campaign(c.campaign_id)
        facts = _refs(entity, "cpa", "ad_spend", "attributed_purchases")
        start = _reference_start(c.spend, c_cfg.reference_start_day)
        if start is None:
            continue
        stop = start + c_cfg.reference_days
        ref_purchases = sum(c.attributed_purchases[start:stop], ZERO)
        ref_spend = sum(c.spend[start:stop], ZERO)
        minimum = Decimal(str(cfg.campaign_cpa.min_reference_purchases))
        if ref_spend <= 0 or ref_purchases < minimum:
            continue
        rate = float(ref_purchases / ref_spend)
        per_spend = ratio_series(c.attributed_purchases, c.spend)
        out += _z_findings(cfg, "campaign_cpa_z", entity, "cpa", per_spend, DOWN, facts)
        expected: list[float | None] = [
            None if t < stop or s <= 0 else rate * float(s) for t, s in enumerate(c.spend)
        ]
        residuals = poisson_residuals(c.attributed_purchases, expected)
        out += _cusum_findings(
            cfg,
            "campaign_cpa_cusum",
            entity,
            "cpa",
            residuals,
            DOWN,
            facts,
            k=cfg.campaign_cpa.cusum_k,
        )
    return out


def _daily_units(p: ProductSeries) -> list[float | None]:
    return as_floats(p.units)


def _daily_unit_cost(p: ProductSeries) -> list[float | None]:
    return ratio_series(p.cogs, p.units)


def _daily_unit_fee(p: ProductSeries) -> list[float | None]:
    return ratio_series(p.unit_fees, p.units)


def product_metrics(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    """Per-product z-tests, corrected across products with Benjamini-Hochberg each day."""
    tests = (
        (
            "product_units_z",
            "units",
            _daily_units,
            DOWN,
            ("units",),
            None,
            cfg.product_units.threshold,
            cfg.product_units.min_baseline_units,
        ),
        (
            "product_unit_cost_z",
            "unit_cost",
            _daily_unit_cost,
            UP,
            ("cogs", "units"),
            cfg.product_unit_cost.rel_floor,
            cfg.robust_z.threshold,
            0.0,
        ),
        (
            "product_unit_fee_z",
            "unit_fee",
            _daily_unit_fee,
            UP,
            ("fees", "units"),
            cfg.product_unit_fee.rel_floor,
            cfg.robust_z.threshold,
            0.0,
        ),
    )
    out: list[Finding] = []
    for detector, metric, values_of, direction, formulas, rel_floor, limit, min_level in tests:
        scores = {
            p.product_id: _z_scores(
                cfg, values_of(p), direction, rel_floor=rel_floor, min_level=min_level
            )
            for p in series.products.values()
        }
        gated = bh_gate(
            scores, {k: _z_p_values(v) for k, v in scores.items()}, cfg.multiple_testing.fdr
        )
        for pid, values in gated.items():
            entity = EntityRef.product(pid)
            out += _z_episode_findings(
                cfg, detector, entity, metric, values, _refs(entity, *formulas), limit
            )
    return out


def store_metrics(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    store = EntityRef.store()
    c_cfg = cfg.cusum
    revenue = series.total("revenue")
    gross = [r - c for r, c in zip(revenue, series.total("cogs"), strict=True)]
    start = _reference_start(revenue, c_cfg.reference_start_day) or 0
    checks = (
        (
            "store_payment_fee_rate",
            "payment_fee_rate",
            ratio_series(series.total("payment_fees"), revenue),
            UP,
            _refs(store, "fees", "revenue"),
            cfg.store_payment_fee_rate,
        ),
        (
            "store_gross_margin_rate",
            "gross_margin_rate",
            ratio_series(gross, revenue),
            DOWN,
            _refs(store, "gross_margin", "revenue"),
            cfg.store_gross_margin_rate,
        ),
    )
    out: list[Finding] = []
    for detector, metric, values, direction, facts, section in checks:
        out += _z_findings(
            cfg,
            f"{detector}_z",
            store,
            metric,
            values,
            direction,
            facts,
            rel_floor=section.rel_floor,
        )
        standardized = standardize(
            values,
            reference_start=start,
            reference_days=c_cfg.reference_days,
            rel_floor=section.rel_floor,
            abs_floor=c_cfg.abs_floor,
        )
        out += _cusum_findings(
            cfg,
            f"{detector}_cusum",
            store,
            metric,
            standardized,
            direction,
            facts,
            k=section.cusum_k,
            h=section.cusum_h,
        )
    return out


# --- business rules ----------------------------------------------------------------------------


def _rule_findings(
    detector_id: str,
    entity: EntityRef,
    metric: str,
    category: SymptomCategory,
    days: int,
    score_on: Callable[[int], float | None],
    *,
    persist: int,
    window: int,
    baseline: int,
    facts: tuple[FactRef, ...],
) -> list[Finding]:
    """`score_on(t)` returns >= 1 when the rule is breached on day t."""
    scores = [score_on(t) for t in range(days)]
    return [
        Finding(detector_id, entity, metric, category, e, e.peak, window, baseline, facts)
        for e in episodes(scores, 1.0, persist)
    ]


def lagged_exposure(lines: Sequence[Decimal], lag_min: int, lag_max: int) -> list[Decimal]:
    """Average lines sold `lag_min`..`lag_max` days before each day (refund exposure)."""
    span = Decimal(lag_max - lag_min + 1)
    return [
        _sum(lines, t - lag_max, t - lag_min + 1) / span if t - lag_min >= 0 else ZERO
        for t in range(len(lines))
    ]


def _promoted(series: StoreSeries, c: CampaignSeries, metric: str) -> list[Decimal]:
    return series.total(metric, c.promoted)


def campaign_profit_negative(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    """Attributed contribution minus spend over the trailing window is negative."""
    r = cfg.campaign_profit
    w = r.window_days
    out: list[Finding] = []
    for c in series.campaigns.values():
        revenue = _promoted(series, c, "revenue")
        costs = [
            a + b + d + e
            for a, b, d, e in zip(
                _promoted(series, c, "cogs"),
                _promoted(series, c, "unit_fees"),
                _promoted(series, c, "payment_fees"),
                _promoted(series, c, "refunds"),
                strict=True,
            )
        ]

        def score(
            t: int,
            c: CampaignSeries = c,
            revenue: list[Decimal] = revenue,
            costs: list[Decimal] = costs,
        ) -> float | None:
            if t < w - 1:
                return None
            spend = _sum(c.spend, t - w + 1, t + 1)
            sales = _sum(revenue, t - w + 1, t + 1)
            attributed = _sum(c.attributed_revenue, t - w + 1, t + 1)
            if spend <= 0 or sales <= 0:
                return None
            margin = sales - _sum(costs, t - w + 1, t + 1)
            profit = attributed * margin / sales - spend
            loss_ratio = float(-profit / spend)
            return 1.0 + loss_ratio if loss_ratio > r.min_loss_ratio else None

        entity = EntityRef.campaign(c.campaign_id)
        out += _rule_findings(
            "campaign_profit_negative",
            entity,
            "campaign_profit",
            PROFIT,
            series.days,
            score,
            persist=r.persist_days,
            window=w,
            baseline=cfg.robust_z.baseline_days,
            facts=_refs(entity, "campaign_profit"),
        )
    return out


def inventory_cover_below_lead_time(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    """Days of cover below the supplier lead time on a product with active promoting spend."""
    r = cfg.inventory_cover
    out: list[Finding] = []
    for p in series.products.values():
        promoters = [series.campaigns[cid] for cid in series.campaigns_promoting(p.product_id)]
        if not promoters or not p.lead_time_days:
            continue
        lead = p.lead_time_days
        sold28 = rolling_sum(p.units, 28)

        def score(
            t: int,
            p_units: list[Decimal | None] = sold28,
            on_hand: list[int | None] = p.on_hand,
            promoters: list[CampaignSeries] = promoters,
            lead: int = lead,
        ) -> float | None:
            stock, sold = on_hand[t], p_units[t]
            if stock is None or sold is None:
                return None
            spend = sum(
                (_sum(c.spend, t - r.spend_window_days + 1, t + 1) for c in promoters), ZERO
            )
            if spend <= 0:
                return None
            cover = float(Decimal(stock) * 28 / sold) if sold > 0 else (0.0 if stock == 0 else None)
            if cover is None or cover >= lead:
                return None
            return 1.0 + (lead - cover) / lead

        entity = EntityRef.product(p.product_id)
        found = _rule_findings(
            "product_cover_below_lead_time",
            entity,
            "inventory_cover_days",
            PROFIT,
            series.days,
            score,
            persist=r.persist_days,
            window=1,
            baseline=28,
            facts=_refs(entity, "inventory_cover_days", "units_on_hand"),
        )
        # Ads still running on a product with nothing on hand: critical whatever the amount.
        out += [
            replace(f, note=OUT_OF_STOCK_NOTE) if p.on_hand[f.episode.confirmed] == 0 else f
            for f in found
        ]
    return out


def refund_rate_band(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    """Refunds per order line in the window are significantly above the product's own history.

    Events, not units, so the counting model holds when lines carry several units. Refunds
    arrive `lag_min_days`-`lag_max_days` after the sale, so the exposure of a day is the average
    number of lines sold over that lag range before it (counting both on the same day would make
    any sales dip look like a refund spike). The baseline is every day from the warm-up to the
    window start. A day counts when the rate is at least `ratio` times the baseline rate, the
    conditional binomial test gives p < `alpha`, and the test survives Benjamini-Hochberg across
    products that day.
    """
    r = cfg.refund_rate
    w = r.window_days

    def test(
        p: ProductSeries, exposure: list[Decimal], t: int
    ) -> tuple[float | None, float | None]:
        base_start, base_end = r.warmup_days, t - w + 1
        if base_end - base_start < r.baseline_days:
            return None, None
        base_sold = _sum(exposure, base_start, base_end)
        current_sold = _sum(exposure, base_end, t + 1)
        if base_sold <= 0 or current_sold <= 0:
            return None, None
        base_refunds = int(_sum(p.refund_events, base_start, base_end))
        current_refunds = int(_sum(p.refund_events, base_end, t + 1))
        p_value = rate_increase_p_value(
            current_refunds, float(current_sold), base_refunds, float(base_sold)
        )
        base_rate = max(base_refunds / float(base_sold), r.min_baseline_rate)
        if current_refunds < r.ratio * base_rate * float(current_sold) or p_value >= r.alpha:
            return None, p_value
        return math.log10(1 / max(p_value, 1e-300)) / math.log10(1 / r.alpha), p_value

    scores: dict[UUID, list[float | None]] = {}
    p_values: dict[UUID, list[float | None]] = {}
    for p in series.products.values():
        exposure = lagged_exposure(p.lines, r.lag_min_days, r.lag_max_days)
        results = [test(p, exposure, t) for t in range(series.days)]
        scores[p.product_id] = [score for score, _ in results]
        p_values[p.product_id] = [pv for _, pv in results]
    out: list[Finding] = []
    for pid, values in bh_gate(scores, p_values, cfg.multiple_testing.fdr).items():
        entity = EntityRef.product(pid)
        out += [
            Finding(
                "product_refund_rate_band",
                entity,
                "refund_rate",
                PROFIT,
                e,
                e.peak,
                w,
                r.baseline_days,
                _refs(entity, "refund_rate"),
            )
            for e in episodes(values, 1.0, r.persist_days)
        ]
    return out


def attribution_collapse(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    """Tracking break (data quality): attributed purchases per click step down toward zero.

    The shape tells it from a CPA drift. At each day, the change point of the conversion rate
    (attributed purchases per click) is estimated from data up to that day. A tracking break is
    an abrupt step: over the `abrupt_days` before the change point the rate is still at least
    `stable_before_ratio` of the baseline, and over the `abrupt_days` after it it is already
    below `max_ratio_of_baseline` of the days just before, while clicks continue and the real
    sales of the promoted products do not follow the attributed revenue down (a drop beyond
    2 sigma of promoted sales, of which real sales explain at most `max_explained_share` give
    or take `explained_noise_sigmas` sigma of their own noise).
    A CPA drift is gradual (its early rate is still close to the baseline) or real sales fall
    with it. Baselines always end before the change point.
    """
    r = cfg.attribution_collapse
    b = r.baseline_days
    out: list[Finding] = []
    for c in series.campaigns.values():
        revenue = _promoted(series, c, "revenue")
        lines = _promoted(series, c, "lines")
        active = next((i for i, s in enumerate(c.spend) if s > 0), None)
        if active is None or not c.clicks:
            continue

        def test(
            t: int,
            c: CampaignSeries = c,
            revenue: list[Decimal] = revenue,
            lines: list[Decimal] = lines,
            active: int = active,
        ) -> tuple[float, int] | None:
            lo = max(active, t - r.lookback_days + 1)
            k = rate_drop_change_point(
                c.attributed_purchases,
                c.clicks,
                lo,
                t + 1,
                min_before=r.min_before_days,
                min_after=r.abrupt_days + r.change_point_guard_days,
            )
            if k is None:
                return None
            pre, a, g = max(lo, k - b), r.abrupt_days, r.change_point_guard_days

            def rate(start: int, stop: int, c: CampaignSeries = c) -> Decimal | None:
                clicks = _sum(c.clicks, start, stop)
                return _sum(c.attributed_purchases, start, stop) / clicks if clicks > 0 else None

            pre_rate, post_rate = rate(pre, k), rate(k, t + 1)
            # The change point is located to within a day or so: the step test skips `g` days on
            # each side of it so a one-day error does not blur the before/after windows.
            late, early = rate(k - g - a, k - g), rate(k + g, k + g + a)
            if not pre_rate or not late or post_rate is None or early is None:
                return None
            if _sum(c.attributed_purchases, k - g - a, k - g) < Decimal(r.min_purchases_before):
                return None  # too few purchases to tell a step from a ramp
            relative = float(post_rate / pre_rate)
            if relative > r.max_ratio_of_baseline:
                return None  # no collapse
            # A step, not a ramp: stable right up to the change point, collapsed right after it.
            if float(late / pre_rate) < r.stable_before_ratio:
                return None
            if float(early / late) > r.max_ratio_of_baseline:
                return None
            pre_clicks, post_clicks = _sum(c.clicks, pre, k), _sum(c.clicks, k, t + 1)
            pre_days, post_days = Decimal(k - pre), Decimal(t + 1 - k)
            scale = post_days / pre_days
            if abs(float(post_clicks / (pre_clicks * scale)) - 1) > r.clicks_tolerance:
                return None  # clicks changed too: a delivery problem, not tracking
            base_sales = _sum(revenue, pre, k)
            sales = _sum(revenue, k, t + 1)
            base_lines = _sum(lines, pre, k)
            if base_sales <= 0 or base_lines <= 0:
                return None
            if abs(float(sales / (base_sales * scale)) - 1) > r.orders_stable_tolerance:
                return None
            attributed_drop = _sum(c.attributed_revenue, pre, k) * scale - _sum(
                c.attributed_revenue, k, t + 1
            )
            sales_drop = base_sales * scale - sales
            # Compound Poisson: Var(window sales) ~ expected sales x mean line value.
            sigma = math.sqrt(float(base_sales * scale) * float(base_sales / base_lines))
            if attributed_drop <= 0 or float(attributed_drop) < r.min_drop_sigmas * sigma:
                return None
            # Real sales follow the attributed drop beyond what their own noise allows.
            explained = float(attributed_drop) * r.max_explained_share
            if float(sales_drop) > explained + r.explained_noise_sigmas * sigma:
                return None
            return 2.0 - relative, k

        results = [test(t) for t in range(series.days)]
        scores = [None if x is None else x[0] for x in results]
        entity = EntityRef.campaign(c.campaign_id)
        for e in episodes(scores, 1.0, r.persist_days):
            found = results[e.confirmed]
            assert found is not None
            out.append(
                Finding(
                    "campaign_attribution_collapse",
                    entity,
                    "attribution_ratio",
                    DATA_QUALITY,
                    e,
                    e.peak,
                    r.abrupt_days,
                    b,
                    _refs(entity, "attribution_ratio", "promoted_revenue"),
                    change_point=found[1],
                )
            )
    return out


def incrementality(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    """Attributed purchases rise while the promoted products' total sales stay flat."""
    r = cfg.incrementality
    w, b = r.window_days, r.baseline_days
    out: list[Finding] = []
    for c in series.campaigns.values():
        units = _promoted(series, c, "units")

        def score(t: int, c: CampaignSeries = c, units: list[Decimal] = units) -> float | None:
            if t - w - b + 1 < 0:
                return None
            if any(s <= 0 for s in c.spend[t - w - b + 1 : t + 1]):
                return None  # the campaign was not active over the whole comparison
            scale = Decimal(w) / Decimal(b)
            base_purchases = _sum(c.attributed_purchases, t - w - b + 1, t - w + 1) * scale
            base_units = _sum(units, t - w - b + 1, t - w + 1) * scale
            if base_purchases < Decimal(str(r.min_baseline_purchases)) or base_units <= 0:
                return None
            rise = float(_sum(c.attributed_purchases, t - w + 1, t + 1) / base_purchases) - 1
            units_change = float(_sum(units, t - w + 1, t + 1) / base_units) - 1
            if rise < r.min_rise or abs(units_change) > r.sales_flat_tolerance:
                return None
            return 1.0 + rise

        entity = EntityRef.campaign(c.campaign_id)
        out += _rule_findings(
            "campaign_incrementality",
            entity,
            "attributed_purchases",
            PROFIT,
            series.days,
            score,
            persist=r.persist_days,
            window=w,
            baseline=b,
            facts=_refs(entity, "attributed_purchases", "promoted_revenue"),
        )
    return out


DETECTORS: tuple[Callable[[StoreSeries, DetectionConfig], list[Finding]], ...] = (
    campaign_cpa,
    product_metrics,
    store_metrics,
    campaign_profit_negative,
    inventory_cover_below_lead_time,
    refund_rate_band,
    attribution_collapse,
    incrementality,
)


def reclassify_data_quality(findings: list[Finding], gap_days: int) -> list[Finding]:
    """Symptoms built on attributed numbers of a campaign whose attribution collapsed are data
    quality consequences, never profitability alerts."""
    collapses: dict[UUID | None, list[Episode]] = {}
    for f in findings:
        if f.detector_id == "campaign_attribution_collapse":
            collapses.setdefault(f.entity.id, []).append(f.episode)
    out: list[Finding] = []
    for f in findings:
        related = collapses.get(f.entity.id, [])
        if f.detector_id in ATTRIBUTED_METRIC_DETECTORS and any(
            f.episode.end >= e.start - gap_days for e in related
        ):
            f = replace(f, category=DATA_QUALITY, note="explained by an attribution collapse")
        out.append(f)
    return out


def run_detectors(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    findings = [f for detector in DETECTORS for f in detector(series, cfg)]
    findings = reclassify_data_quality(findings, cfg.incidents.gap_days)
    return sorted(findings, key=lambda f: (f.episode.confirmed, f.detector_id, str(f.entity)))
