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
from app.detection.models import EntityRef, SymptomCategory
from app.detection.series import CampaignSeries, StoreSeries
from app.detection.stats import (
    Episode,
    as_floats,
    cusum_path,
    episodes,
    poisson_residuals,
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
    z_cfg = cfg.robust_z
    limit = threshold or z_cfg.threshold
    scores = robust_z(
        series,
        window=1,
        baseline=z_cfg.baseline_days,
        direction=direction,
        rel_floor=rel_floor if rel_floor is not None else z_cfg.rel_floor,
        abs_floor=z_cfg.abs_floor,
        min_baseline_level=min_level,
    )
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
        out += _cusum_findings(cfg, "campaign_cpa_cusum", entity, "cpa", residuals, DOWN, facts)
    return out


def product_metrics(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    out: list[Finding] = []
    for p in series.products.values():
        entity = EntityRef.product(p.product_id)
        out += _z_findings(
            cfg,
            "product_units_z",
            entity,
            "units",
            as_floats(p.units),
            DOWN,
            _refs(entity, "units"),
            threshold=cfg.product_units.threshold,
            min_level=cfg.product_units.min_baseline_units,
        )
        out += _z_findings(
            cfg,
            "product_unit_cost_z",
            entity,
            "unit_cost",
            ratio_series(p.cogs, p.units),
            UP,
            _refs(entity, "cogs", "units"),
            rel_floor=cfg.product_unit_cost.rel_floor,
        )
        out += _z_findings(
            cfg,
            "product_unit_fee_z",
            entity,
            "unit_fee",
            ratio_series(p.unit_fees, p.units),
            UP,
            _refs(entity, "fees", "units"),
            rel_floor=cfg.product_unit_fee.rel_floor,
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
        out += _rule_findings(
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
    return out


def refund_rate_band(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    """Refunds per order line in the window are significantly above the product's own history.

    Events, not units, so the counting model holds when lines carry several units. The baseline
    is every day from the warm-up to the window start (refunds lag sales by up to 20 days, hence
    the warm-up). Fires when the rate is at least `ratio` times the baseline rate and the
    conditional binomial test gives p < `alpha`.
    """
    r = cfg.refund_rate
    w = r.window_days
    out: list[Finding] = []
    for p in series.products.values():

        def score(
            t: int, refunded: list[Decimal] = p.refund_events, sold: list[Decimal] = p.lines
        ) -> float | None:
            base_start, base_end = r.warmup_days, t - w + 1
            if base_end - base_start < r.baseline_days:
                return None
            base_sold = _sum(sold, base_start, base_end)
            current_sold = _sum(sold, base_end, t + 1)
            if base_sold <= 0 or current_sold <= 0:
                return None
            base_refunds = int(_sum(refunded, base_start, base_end))
            current_refunds = int(_sum(refunded, base_end, t + 1))
            base_rate = max(base_refunds / float(base_sold), r.min_baseline_rate)
            if current_refunds < r.ratio * base_rate * float(current_sold):
                return None
            p_value = rate_increase_p_value(
                current_refunds, float(current_sold), base_refunds, float(base_sold)
            )
            if p_value >= r.alpha:
                return None
            return math.log10(1 / max(p_value, 1e-300)) / math.log10(1 / r.alpha)

        entity = EntityRef.product(p.product_id)
        out += _rule_findings(
            "product_refund_rate_band",
            entity,
            "refund_rate",
            PROFIT,
            series.days,
            score,
            persist=r.persist_days,
            window=w,
            baseline=r.baseline_days,
            facts=_refs(entity, "refund_rate"),
        )
    return out


def attribution_collapse(series: StoreSeries, cfg: DetectionConfig) -> list[Finding]:
    """Attributed revenue collapses while real sales of the promoted products do not follow:
    a data-quality problem. If real sales fell by a comparable amount, the purchases were really
    lost (a profitability problem such as CPA drift), and this rule stays silent. It also stays
    silent when the attributed drop is within the noise of the promoted products' sales
    (compound-Poisson sigma), since then real sales could not show whether purchases were lost."""
    r = cfg.attribution_collapse
    w, b = r.window_days, r.baseline_days
    out: list[Finding] = []
    for c in series.campaigns.values():
        revenue = _promoted(series, c, "revenue")
        lines = _promoted(series, c, "lines")

        def score(
            t: int,
            c: CampaignSeries = c,
            revenue: list[Decimal] = revenue,
            lines: list[Decimal] = lines,
        ) -> float | None:
            if t - w - b + 1 < 0:
                return None
            sales = _sum(revenue, t - w + 1, t + 1)
            base_sales = _sum(revenue, t - w - b + 1, t - w + 1)
            base_attr = _sum(c.attributed_revenue, t - w - b + 1, t - w + 1)
            if sales <= 0 or base_sales <= 0 or base_attr <= 0:
                return None
            scale = Decimal(w) / Decimal(b)
            sales_change = float(sales / (base_sales * scale)) - 1
            if abs(sales_change) > r.orders_stable_tolerance:
                return None
            attributed = _sum(c.attributed_revenue, t - w + 1, t + 1)
            attributed_drop = base_attr * scale - attributed
            sales_drop = base_sales * scale - sales
            if attributed_drop <= 0 or sales_drop > attributed_drop * Decimal(
                str(r.max_explained_share)
            ):
                return None
            base_lines = _sum(lines, t - w - b + 1, t - w + 1)
            if base_lines <= 0:
                return None
            # Compound Poisson: Var(window sales) ~ expected sales x mean line value.
            sigma = math.sqrt(float(base_sales * scale) * float(base_sales / base_lines))
            if float(attributed_drop) < r.min_drop_sigmas * sigma:
                return None
            ratio_now = attributed / sales
            ratio_before = base_attr / base_sales
            relative = float(ratio_now / ratio_before)
            return 2.0 - relative if relative <= r.max_ratio_of_baseline else None

        entity = EntityRef.campaign(c.campaign_id)
        out += _rule_findings(
            "campaign_attribution_collapse",
            entity,
            "attribution_ratio",
            DATA_QUALITY,
            series.days,
            score,
            persist=r.persist_days,
            window=w,
            baseline=b,
            facts=_refs(entity, "attribution_ratio", "promoted_revenue"),
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
