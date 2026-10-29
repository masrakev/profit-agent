"""The read-only tools the agent may call (ADR 0010). None writes business data."""

from datetime import date, timedelta
from typing import Any, Literal
from uuid import UUID

import numpy as np
from pydantic import Field
from sqlalchemy import text

from app.agent.tools.base import (
    EntityInput,
    EntityView,
    FactView,
    PeriodInput,
    Tool,
    ToolContext,
    ToolError,
    ToolInput,
    ToolResult,
    scope_label,
)
from app.agent.tools.derived import ComputeError, change_point, compute, difference, mean, slope
from app.causes.noise import noise_band
from app.causes.profit import AttributionUnavailableError, attribute_profit_change
from app.detection.config import default_config
from app.detection.models import EntityRef, SymptomCategory
from app.detection.pipeline import daily_figures
from app.detection.repository import load_incident, load_incidents
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.formulas import REGISTRY
from app.facts.model import Fact, Period, Scope, ScopeKind, Unit
from app.facts.registry import UnknownFormulaError, UnsupportedScopeError
from app.facts.repository import get_facts

MAX_SERIES_DAYS = 120
MAX_COMPARED = 20
LEVEL2_SHOWN = 5
STALE_AFTER_DAYS = 1


def _fact(ctx: ToolContext, metric: str, scope: Scope, period: Period) -> Fact:
    try:
        return ctx.facts.fact(metric, scope, period)
    except UnknownFormulaError:
        raise ToolError(
            "unknown_metric",
            f"unknown metric {metric[:64]!r}; known: {', '.join(f.formula_id for f in REGISTRY)}",
        ) from None
    except UnsupportedScopeError as exc:
        raise ToolError("unsupported_scope", str(exc)) from None
    except LookupError as exc:
        raise ToolError("not_found", str(exc)) from None


def _facts_by_id(ctx: ToolContext, ids: tuple[int, ...] | list[int]) -> list[FactView]:
    found = get_facts(ctx.conn, ctx.store_id, ids)
    return [ctx.view(found[i]) for i in ids if i in found]


# --- get_incident --------------------------------------------------------------------------


class IncidentQuery(ToolInput):
    incident_id: str = Field(pattern=r"^inc-[0-9a-f]{12}$")


class SymptomView(ToolResult):
    detector: str
    entity: str
    metric: str
    category: str
    first_seen: date
    last_seen: date
    note: str | None
    baseline_facts: list[FactView]
    current_facts: list[FactView]


class CandidateView(ToolResult):
    family: str
    entity: str
    evidence: list[str]


class IncidentView(ToolResult):
    incident_id: str
    category: str
    alert: str
    material: bool
    first_seen: date
    last_seen: date
    entities: list[EntityView]
    symptoms: list[SymptomView]
    candidates: list[CandidateView] = Field(description="deterministic ranking, best first")
    expected_monthly_impact: FactView | None
    attribution: list[FactView]


def _scope(entity: EntityRef) -> Scope:
    return Scope(kind=entity.kind, id=entity.id)


def get_incident(ctx: ToolContext, q: IncidentQuery) -> IncidentView:
    stored = load_incident(ctx.conn, ctx.store_id, q.incident_id)
    if stored is None:
        raise ToolError("not_found", f"no incident {q.incident_id}")
    i = stored.incident
    impact = _facts_by_id(ctx, [i.monthly_impact_fact_id]) if i.monthly_impact_fact_id else []
    return IncidentView(
        incident_id=i.incident_id,
        category=i.category.value,
        alert=i.alert.value,
        material=i.material,
        first_seen=i.first_seen,
        last_seen=i.last_seen,
        entities=[ctx.entity(_scope(e)) for e in i.entities],
        symptoms=[
            SymptomView(
                detector=s.detector_id,
                entity=str(s.entity),
                metric=s.metric,
                category=s.category.value,
                first_seen=s.first_seen,
                last_seen=s.last_seen,
                note=s.note,
                baseline_facts=_facts_by_id(ctx, s.baseline_fact_ids),
                current_facts=_facts_by_id(ctx, s.current_fact_ids),
            )
            for s in i.symptoms
        ],
        candidates=[
            CandidateView(family=c.family.value, entity=str(c.entity), evidence=list(c.evidence))
            for c in i.candidates
        ],
        expected_monthly_impact=impact[0] if impact else None,
        attribution=_facts_by_id(ctx, i.attribution_fact_ids),
    )


# --- get_profit_bridge ---------------------------------------------------------------------


class BridgeQuery(ToolInput):
    scope: EntityInput
    baseline: PeriodInput
    current: PeriodInput


class DriverView(ToolResult):
    driver: str
    contribution: FactView
    significant: bool | None = Field(description="outside the store's own noise band")


class Level2View(ToolResult):
    driver: str
    contributions: list[FactView]


class BridgeView(ToolResult):
    net_profit_change: FactView
    drivers: list[DriverView]
    entity_contributions: list[Level2View]


def get_profit_bridge(ctx: ToolContext, q: BridgeQuery) -> BridgeView:
    baseline, current = q.baseline.period(), q.current.period()
    if baseline.end > current.start:
        raise ToolError("invalid_periods", "the baseline must end before the current period")
    series = ctx.series()
    band = None
    try:
        start = series.index(q.baseline.start)
        cfg = default_config().noise_band
        band = noise_band(
            daily_figures(series),
            length=(q.current.end - q.current.start).days,
            history_end=start,
            rng=np.random.default_rng(
                int(
                    sha256_hex(
                        canonical_json(
                            [
                                str(ctx.store_id),
                                *(
                                    str(d)
                                    for d in (
                                        q.baseline.start,
                                        q.baseline.end,
                                        q.current.start,
                                        q.current.end,
                                    )
                                ),
                            ]
                        )
                    )[:15],
                    16,
                )
            ),
            resamples=cfg.resamples,
            min_pairs=cfg.min_pairs,
            quantiles=(cfg.low_percentile, cfg.high_percentile),
        )
    except (ValueError, IndexError):
        band = None  # too little history before the baseline: significance not assessed
    try:
        attribution = attribute_profit_change(ctx.facts, baseline, current, band)
    except AttributionUnavailableError as exc:
        raise ToolError("unavailable", str(exc)) from None
    wanted = q.scope.scope()
    level2 = []
    for driver, contributions in attribution.level2.items():
        chosen = [c for c in contributions if wanted.kind is ScopeKind.STORE or c.scope == wanted][
            :LEVEL2_SHOWN
        ]
        if chosen:
            level2.append(
                Level2View(
                    driver=driver.value,
                    contributions=_facts_by_id(ctx, [c.fact_id for c in chosen]),
                )
            )
    drivers = [
        DriverView(
            driver=d.value,
            contribution=_facts_by_id(ctx, [c.fact_id])[0],
            significant=c.significant,
        )
        for d, c in attribution.level1.items()
    ]
    return BridgeView(
        net_profit_change=_facts_by_id(ctx, [attribution.delta_fact_id])[0],
        drivers=drivers,
        entity_contributions=level2,
    )


# --- get_facts, compare_entities -----------------------------------------------------------


class FactQuery(ToolInput):
    metric: str = Field(max_length=64)
    scope: EntityInput
    period: PeriodInput


class FactsView(ToolResult):
    fact: FactView


def get_facts_tool(ctx: ToolContext, q: FactQuery) -> FactsView:
    return FactsView(fact=ctx.view(_fact(ctx, q.metric, q.scope.scope(), q.period.period())))


class CompareQuery(ToolInput):
    metric: str = Field(max_length=64)
    entities: list[EntityInput] = Field(min_length=1, max_length=MAX_COMPARED)
    period: PeriodInput


class ComparedView(ToolResult):
    entity: EntityView
    fact: FactView


class CompareView(ToolResult):
    items: list[ComparedView] = Field(description="highest value first; undefined last")


def compare_entities(ctx: ToolContext, q: CompareQuery) -> CompareView:
    period = q.period.period()
    pairs = [(e.scope(), _fact(ctx, q.metric, e.scope(), period)) for e in q.entities]
    pairs.sort(key=lambda p: (p[1].value is None, -(p[1].value or 0), scope_label(p[0])))
    return CompareView(
        items=[ComparedView(entity=ctx.entity(s), fact=ctx.view(f)) for s, f in pairs]
    )


# --- get_series_summary --------------------------------------------------------------------


class SeriesQuery(ToolInput):
    metric: str = Field(max_length=64)
    entity: EntityInput
    window: PeriodInput


class SeriesView(ToolResult):
    first_day: FactView
    last_day: FactView
    change: FactView
    slope_per_day: FactView
    change_point: date | None = Field(description="first day after the largest mean shift")
    mean_before: FactView | None
    mean_after: FactView | None


def series_summary(ctx: ToolContext, metric: str, scope: Scope, window: PeriodInput) -> SeriesView:
    days = (window.end - window.start).days
    if days > MAX_SERIES_DAYS or days < 3:
        raise ToolError("invalid_window", f"windows of 3 to {MAX_SERIES_DAYS} days")
    formula = REGISTRY.get(metric) if metric in {f.formula_id for f in REGISTRY} else None
    if formula is None or formula.unit not in (Unit.MONEY, Unit.COUNT, Unit.RATIO):
        raise ToolError(
            "unknown_metric", f"{metric[:64]!r} is not a daily money, count or ratio metric"
        )
    daily = [
        _fact(ctx, metric, scope, Period.days(d, d + timedelta(days=1)))
        for d in (window.start + timedelta(days=i) for i in range(days))
    ]
    for d in daily:
        ctx.facts.persist(d)
    period = window.period()
    k = change_point(daily)
    before = after = None
    if k is not None:
        split = window.start + timedelta(days=k)
        before = ctx.view(mean(daily[:k], Period.days(window.start, split), daily[0]))
        after = ctx.view(mean(daily[k:], Period.days(split, window.end), daily[0]))
    return SeriesView(
        first_day=ctx.view(daily[0]),
        last_day=ctx.view(daily[-1]),
        change=ctx.view(difference(daily[0], daily[-1], period)),
        slope_per_day=ctx.view(slope(daily, period, daily[0])),
        change_point=window.start + timedelta(days=k) if k is not None else None,
        mean_before=before,
        mean_after=after,
    )


def get_series_summary(ctx: ToolContext, q: SeriesQuery) -> SeriesView:
    return series_summary(ctx, q.metric, q.entity.scope(), q.window)


# --- get_campaign_context ------------------------------------------------------------------


class CampaignQuery(ToolInput):
    campaign_id: UUID


CAMPAIGN_METRICS = (
    "ad_spend",
    "attributed_revenue",
    "attributed_purchases",
    "attribution_ratio",
    "clicks",
    "impressions",
    "cpa",
    "roas",
    "promoted_revenue",
)


class CampaignView(ToolResult):
    campaign: EntityView
    platform: str
    status: str
    promoted_products: list[EntityView]
    recent: list[FactView] = Field(description="last 28 days of data")
    previous: list[FactView] = Field(description="the 28 days before")
    clicks_trend: SeriesView


def get_campaign_context(ctx: ToolContext, q: CampaignQuery) -> CampaignView:
    row = ctx.conn.execute(
        text("SELECT platform, status FROM ad_campaigns WHERE store_id = :s AND id = :c"),
        {"s": ctx.store_id, "c": q.campaign_id},
    ).first()
    if row is None:
        raise ToolError("not_found", f"no campaign {q.campaign_id}")
    scope = Scope.campaign(q.campaign_id)
    products = ctx.conn.execute(
        text(
            "SELECT product_id FROM ad_campaign_products WHERE store_id = :s AND campaign_id = :c"
            " ORDER BY product_id"
        ),
        {"s": ctx.store_id, "c": q.campaign_id},
    ).scalars()
    recent, previous = ctx.recent(28), ctx.recent(28, offset=28)
    window = PeriodInput(start=ctx.data_end - timedelta(days=56), end=ctx.data_end)
    return CampaignView(
        campaign=ctx.entity(scope),
        platform=str(row.platform),
        status=str(row.status),
        promoted_products=[ctx.entity(Scope.product(p)) for p in products],
        recent=[ctx.view(_fact(ctx, m, scope, recent)) for m in CAMPAIGN_METRICS],
        previous=[ctx.view(_fact(ctx, m, scope, previous)) for m in CAMPAIGN_METRICS],
        clicks_trend=series_summary(ctx, "clicks", scope, window),
    )


# --- get_inventory_context -----------------------------------------------------------------


class InventoryQuery(ToolInput):
    product_id: UUID


class InventoryView(ToolResult):
    product: EntityView
    latest_snapshot: date | None
    units_on_hand: FactView
    inventory_cover_days: FactView
    supplier_lead_time_days: FactView
    units_sold_last_28_days: FactView
    promoted_by: list[EntityView]


def get_inventory_context(ctx: ToolContext, q: InventoryQuery) -> InventoryView:
    scope = Scope.product(q.product_id)
    if ctx.entity(scope).name is None:
        raise ToolError("not_found", f"no product {q.product_id}")
    recent = ctx.recent(28)
    snapshot = ctx.conn.execute(
        text(
            "SELECT max(snapshot_date) FROM inventory_snapshots WHERE store_id = :s "
            "AND product_id = :p"
        ),
        {"s": ctx.store_id, "p": q.product_id},
    ).scalar()
    campaigns = ctx.conn.execute(
        text(
            "SELECT campaign_id FROM ad_campaign_products WHERE store_id = :s "
            "AND product_id = :p ORDER BY campaign_id"
        ),
        {"s": ctx.store_id, "p": q.product_id},
    ).scalars()
    return InventoryView(
        product=ctx.entity(scope),
        latest_snapshot=snapshot,
        units_on_hand=ctx.view(_fact(ctx, "units_on_hand", scope, recent)),
        inventory_cover_days=ctx.view(_fact(ctx, "inventory_cover_days", scope, recent)),
        supplier_lead_time_days=ctx.view(_fact(ctx, "supplier_lead_time_days", scope, recent)),
        units_sold_last_28_days=ctx.view(_fact(ctx, "units", scope, recent)),
        promoted_by=[ctx.entity(Scope.campaign(c)) for c in campaigns],
    )


# --- get_data_quality ----------------------------------------------------------------------


class DataQualityQuery(ToolInput):
    """No arguments: the store is the one under investigation."""


class SourceView(ToolResult):
    source: Literal["orders", "ad_metrics", "inventory"]
    latest_day: date | None
    status: Literal["fresh", "stale", "missing"]


class ReconciliationView(ToolResult):
    campaign: EntityView
    attribution_ratio_recent: FactView = Field(description="last 14 days")
    attribution_ratio_baseline: FactView = Field(description="the 28 days before")


class DataQualityView(ToolResult):
    analysis_day: date
    sources: list[SourceView]
    reconciliation: list[ReconciliationView]
    open_data_quality_incidents: list[str]


SOURCES: dict[str, str] = {
    "orders": "SELECT max((ordered_at AT TIME ZONE 'UTC')::date) FROM orders WHERE store_id = :s",
    "ad_metrics": "SELECT max(metric_date) FROM ad_metrics_daily WHERE store_id = :s",
    "inventory": "SELECT max(snapshot_date) FROM inventory_snapshots WHERE store_id = :s",
}


def get_data_quality(ctx: ToolContext, q: DataQualityQuery) -> DataQualityView:
    analysis_day = ctx.data_end - timedelta(days=1)
    sources = []
    for name, sql in SOURCES.items():
        latest = ctx.conn.execute(text(sql), {"s": ctx.store_id}).scalar()
        status: Literal["fresh", "stale", "missing"] = (
            "missing"
            if latest is None
            else "stale"
            if (analysis_day - latest).days > STALE_AFTER_DAYS
            else "fresh"
        )
        sources.append(SourceView(source=name, latest_day=latest, status=status))
    recent, baseline = ctx.recent(14), ctx.recent(28, offset=14)
    campaigns = ctx.conn.execute(
        text("SELECT id FROM ad_campaigns WHERE store_id = :s ORDER BY id"), {"s": ctx.store_id}
    ).scalars()
    reconciliation = [
        ReconciliationView(
            campaign=ctx.entity(Scope.campaign(c)),
            attribution_ratio_recent=ctx.view(
                _fact(ctx, "attribution_ratio", Scope.campaign(c), recent)
            ),
            attribution_ratio_baseline=ctx.view(
                _fact(ctx, "attribution_ratio", Scope.campaign(c), baseline)
            ),
        )
        for c in campaigns
    ]
    open_dq = [
        s.incident.incident_id
        for s in load_incidents(ctx.conn, ctx.store_id)
        if s.incident.category is SymptomCategory.DATA_QUALITY
    ]
    return DataQualityView(
        analysis_day=analysis_day,
        sources=sources,
        reconciliation=reconciliation,
        open_data_quality_incidents=open_dq,
    )


# --- compute -------------------------------------------------------------------------------


class ComputeQuery(ToolInput):
    expression: str = Field(max_length=300, description="fact references and + - * / only")
    fact_ids: list[int] = Field(min_length=1, max_length=12)


class ComputeView(ToolResult):
    fact: FactView


def compute_tool(ctx: ToolContext, q: ComputeQuery) -> ComputeView:
    unseen = sorted(set(q.fact_ids) - ctx.seen_fact_ids)
    if unseen:
        raise ToolError("unknown_fact", f"facts {unseen} were not returned by a tool in this run")
    operands = get_facts(ctx.conn, ctx.store_id, q.fact_ids, with_lineage=True)
    for fact in operands.values():
        ctx.facts.adopt(fact)
    try:
        derived = compute(q.expression, operands)
    except ComputeError as exc:
        raise ToolError("invalid_expression", str(exc)) from None
    return ComputeView(fact=ctx.view(derived))


TOOLS: list[Tool[Any, Any]] = [
    Tool(
        "get_incident",
        "An incident: symptoms with their facts, the deterministic ranking of "
        "candidate causes, the expected monthly impact and the profit attribution.",
        IncidentQuery,
        IncidentView,
        get_incident,
    ),
    Tool(
        "get_profit_bridge",
        "Exact Shapley decomposition of the net profit change between two "
        "periods: level-1 drivers with a significance flag, and per-entity contributions.",
        BridgeQuery,
        BridgeView,
        get_profit_bridge,
    ),
    Tool(
        "get_facts",
        "One metric for one entity over one period, as a fact.",
        FactQuery,
        FactsView,
        get_facts_tool,
    ),
    Tool(
        "get_series_summary",
        "Daily series of a metric over a window: first and last day, "
        "change, slope per day and the largest mean shift, as facts.",
        SeriesQuery,
        SeriesView,
        get_series_summary,
    ),
    Tool(
        "compare_entities",
        "One metric for several entities over the same period, highest first.",
        CompareQuery,
        CompareView,
        compare_entities,
    ),
    Tool(
        "get_campaign_context",
        "A campaign: promoted products, spend, attribution and delivery "
        "facts for the last 28 days and the 28 before, and the clicks trend.",
        CampaignQuery,
        CampaignView,
        get_campaign_context,
    ),
    Tool(
        "get_inventory_context",
        "A product's stock: units on hand, cover, supplier lead time, "
        "recent sales and the campaigns promoting it.",
        InventoryQuery,
        InventoryView,
        get_inventory_context,
    ),
    Tool(
        "get_data_quality",
        "Freshness of each data source and the attribution ratio of each "
        "campaign (recent vs baseline), with open data-quality incidents.",
        DataQualityQuery,
        DataQualityView,
        get_data_quality,
    ),
    Tool(
        "compute",
        "Arithmetic over facts already returned in this run (F<id> references, "
        "+ - * / and parentheses; no literal numbers). Returns a new derived fact.",
        ComputeQuery,
        ComputeView,
        compute_tool,
    ),
]
