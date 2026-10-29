"""Audit tools: the agent cross-examines the deterministic pipeline (SPEC section 15, ADR 0012).

- `run_sensitivity`: recompute the attribution, the expected impact and the candidate ranking of
  an incident under a fixed, versioned set of window variants; `stable` is decided by code.
- `check_reconciliation`: product sums against store totals, and platform-attributed purchases
  against real orders of the promoted products, as gap facts.
- `get_method`: how a fact or an incident was computed (formula, windows, thresholds, versions).

All read-only: they persist derived facts, never change a formula, a threshold or a setting.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from app.agent.tools.base import (
    EntityInput,
    EntityView,
    FactView,
    PeriodInput,
    PeriodView,
    Tool,
    ToolContext,
    ToolError,
    ToolInput,
    ToolResult,
)
from app.agent.tools.derived import gap, share, total
from app.causes.profit import AttributionUnavailableError, attribute_profit_change
from app.detection.config import default_config
from app.detection.incidents import EntityGraph, rank_candidates
from app.detection.models import Incident
from app.detection.pipeline import attribution_windows, daily_figures, expected_impact
from app.detection.repository import load_incident
from app.detection.series import StoreSeries
from app.facts import sql
from app.facts.formulas import REGISTRY
from app.facts.model import Fact, Period, Scope
from app.facts.registry import UnknownFormulaError
from app.facts.repository import get_facts

SENSITIVITY_VERSION = "sensitivity_v1"
# (name, baseline shift in days, fixed window length in days or None for the pipeline's own)
VARIANTS: tuple[tuple[str, int, int | None], ...] = (
    ("reference", 0, None),
    ("baseline_minus_7", -7, None),
    ("baseline_plus_7", 7, None),
    ("window_14", 0, 14),
    ("window_28", 0, 28),
    ("window_42", 0, 42),
)
RECONCILED_MONEY = ("revenue", "cogs", "fees", "refunds", "contribution_margin")


def _graph(series: StoreSeries) -> EntityGraph:
    return EntityGraph({c.campaign_id: frozenset(c.promoted) for c in series.campaigns.values()})


def _incident(ctx: ToolContext, incident_id: str) -> Incident:
    stored = load_incident(ctx.conn, ctx.store_id, incident_id)
    if stored is None:
        raise ToolError("not_found", f"no incident {incident_id}")
    return stored.incident


def _period(series: StoreSeries, first: int, end: int) -> Period:
    return Period.days(series.day(first), series.day(first) + timedelta(days=end - first))


def _view(p: Period) -> PeriodView:
    return PeriodView(start=p.start.date(), end_exclusive=p.end.date())


# --- run_sensitivity -----------------------------------------------------------------------


class SensitivityQuery(ToolInput):
    incident_id: str = Field(pattern=r"^inc-[0-9a-f]{12}$")


class VariantView(ToolResult):
    name: str
    baseline: PeriodView | None
    current: PeriodView | None
    valid: bool = Field(description="the windows fit in the data, baseline before current")
    baseline_overlaps_incident: bool = Field(description="baseline ends after first detection")
    top_driver: str | None = Field(description="largest negative level-1 profit driver")
    top_driver_contribution: FactView | None
    expected_monthly_impact: FactView | None
    top_cause_family: str | None
    top_cause_entity: str | None


class SensitivityView(ToolResult):
    incident_id: str
    version: str
    variants: list[VariantView]
    stable: bool = Field(description="same top cause and same impact sign in every valid variant")
    unstable_because: list[str]


def _windows(
    series: StoreSeries, incident: Incident, shift: int, length: int | None
) -> tuple[Period, Period] | None:
    cfg = default_config()
    end = series.days
    if length is None:
        baseline, current = attribution_windows(series, incident.first_seen, cfg)
        b0 = series.index(baseline.start.date()) + shift
        b1 = series.index(baseline.end.date()) + shift
        c0 = series.index(current.start.date())
    else:
        cut = series.index(incident.first_seen) - cfg.attribution.pre_incident_gap_days
        b0, b1, c0 = cut - length, cut, end - length
    if b0 < 0 or b1 > c0 or b1 <= b0 or c0 >= end:
        return None
    return _period(series, b0, b1), _period(series, c0, end)


def _sign(value: Decimal | None) -> int:
    return 0 if value is None or value == 0 else (1 if value > 0 else -1)


def run_sensitivity(ctx: ToolContext, q: SensitivityQuery) -> SensitivityView:
    incident = _incident(ctx, q.incident_id)
    series = ctx.series()
    cfg = default_config()
    graph = _graph(series)
    figures = daily_figures(series)
    group = list(incident.symptoms)
    seen = series.index(incident.first_seen)
    views: list[VariantView] = []
    outcomes: list[tuple[str, tuple[str, str] | None, int]] = []
    for name, shift, length in VARIANTS:
        windows = _windows(series, incident, shift, length)
        if windows is None:
            views.append(
                VariantView(
                    name=name,
                    baseline=None,
                    current=None,
                    valid=False,
                    baseline_overlaps_incident=False,
                    top_driver=None,
                    top_driver_contribution=None,
                    expected_monthly_impact=None,
                    top_cause_family=None,
                    top_cause_entity=None,
                )
            )
            continue
        baseline, current = windows
        try:
            attribution = attribute_profit_change(ctx.facts, baseline, current)
        except AttributionUnavailableError:
            attribution = None
        impact, impact_fact = expected_impact(
            ctx.facts, series, group, graph, baseline, current, cfg, figures
        )
        driver = attribution.largest_negative() if attribution else None
        driver_view = None
        if attribution is not None and driver is not None:
            driver_view = ctx.view(_fact_by_id(ctx, attribution.level1[driver].fact_id))
        ranked = rank_candidates(group, graph, cfg, attribution)
        top = (ranked[0].family.value, str(ranked[0].entity)) if ranked else None
        outcomes.append((name, top, _sign(impact.p50)))
        views.append(
            VariantView(
                name=name,
                baseline=_view(baseline),
                current=_view(current),
                valid=True,
                baseline_overlaps_incident=series.index(baseline.end.date()) > seen,
                top_driver=driver.value if driver else None,
                top_driver_contribution=driver_view,
                expected_monthly_impact=ctx.view(impact_fact),
                top_cause_family=top[0] if top else None,
                top_cause_entity=top[1] if top else None,
            )
        )
    reasons: list[str] = []
    if len(outcomes) < 2:
        reasons.append("fewer than two valid variants")
    else:
        ref_name, ref_top, ref_sign = outcomes[0]
        for name, top, sign in outcomes[1:]:
            if top != ref_top:
                reasons.append(f"top cause differs in {name} from {ref_name}")
            if sign != ref_sign:
                reasons.append(f"impact sign differs in {name} from {ref_name}")
    return SensitivityView(
        incident_id=incident.incident_id,
        version=SENSITIVITY_VERSION,
        variants=views,
        stable=not reasons,
        unstable_because=reasons,
    )


def _fact_by_id(ctx: ToolContext, fact_id: int) -> Fact:
    return get_facts(ctx.conn, ctx.store_id, [fact_id])[fact_id]


# --- check_reconciliation ------------------------------------------------------------------


class ReconciliationQuery(ToolInput):
    scope: EntityInput = Field(description="the store, or one campaign")
    period: PeriodInput


class MoneyCheck(ToolResult):
    metric: str
    store_total: FactView
    products_sum: FactView
    gap: FactView


class PurchasesCheck(ToolResult):
    campaign: EntityView
    attributed_purchases: FactView
    orders_with_promoted_products: FactView
    gap: FactView
    attributed_per_order: FactView
    over_attributed: bool | None = Field(description="platform claims more purchases than orders")


class ReconciliationView(ToolResult):
    money: list[MoneyCheck]
    purchases: list[PurchasesCheck]
    products_reconcile: bool | None = Field(description="every money gap is exactly zero")


def check_reconciliation(ctx: ToolContext, q: ReconciliationQuery) -> ReconciliationView:
    period = q.period.period()
    if q.scope.kind == "product":
        raise ToolError("unsupported_scope", "reconcile the store or a campaign")
    money: list[MoneyCheck] = []
    if q.scope.kind == "store":
        products = sql.product_ids(ctx.conn, ctx.store_id)
        for metric in RECONCILED_MONEY:
            store_fact = ctx.facts.fact(metric, Scope.store(), period)
            parts = [ctx.facts.fact(metric, Scope.product(p), period) for p in products]
            for part in parts:
                ctx.facts.persist(part)
            ctx.facts.persist(store_fact)
            summed = ctx.facts.persist(
                ctx.facts.adopt(total(parts, Scope.store(), period, store_fact))
            )
            money.append(
                MoneyCheck(
                    metric=metric,
                    store_total=ctx.view(store_fact),
                    products_sum=ctx.view(summed),
                    gap=ctx.view(gap(store_fact, summed)),
                )
            )
        campaigns = sql.campaign_ids(ctx.conn, ctx.store_id)
    else:
        assert q.scope.id is not None
        if q.scope.id not in sql.campaign_ids(ctx.conn, ctx.store_id):
            raise ToolError("not_found", f"no campaign {q.scope.id}")
        campaigns = [q.scope.id]
    purchases: list[PurchasesCheck] = []
    for cid in campaigns:
        c = Scope.campaign(cid)
        attributed = ctx.facts.persist(ctx.facts.fact("attributed_purchases", c, period))
        orders = ctx.facts.persist(ctx.facts.fact("orders", c, period))
        over = (
            None
            if attributed.value is None or orders.value is None
            else attributed.value > orders.value
        )
        purchases.append(
            PurchasesCheck(
                campaign=ctx.entity(c),
                attributed_purchases=ctx.view(attributed),
                orders_with_promoted_products=ctx.view(orders),
                gap=ctx.view(gap(attributed, orders)),
                attributed_per_order=ctx.view(share(attributed, orders)),
                over_attributed=over,
            )
        )
    gaps = [m.gap for m in money]
    balanced = (
        None if not gaps else all(g.value is not None and Decimal(g.value) == 0 for g in gaps)
    )
    return ReconciliationView(money=money, purchases=purchases, products_reconcile=balanced)


# --- get_method ----------------------------------------------------------------------------


class MethodQuery(ToolInput):
    fact_id: int | None = Field(default=None, description="give a fact id or an incident id")
    incident_id: str | None = Field(default=None, pattern=r"^inc-[0-9a-f]{12}$")

    @model_validator(mode="after")
    def _exactly_one(self) -> "MethodQuery":
        if (self.fact_id is None) == (self.incident_id is None):
            raise ValueError("give exactly one of fact_id and incident_id")
        return self


class ParameterView(ToolResult):
    name: str
    value: str  # configuration, not a measurement: never quote it as a number


class SymptomMethod(ToolResult):
    detector: str
    metric: str
    sections: list[str]
    parameters: list[ParameterView]
    baseline_ends_before_first_seen: bool | None


class MethodView(ToolResult):
    subject: str
    kind: Literal["fact", "incident"]
    formula: str | None
    formula_version: str | None
    description: str | None
    inputs: list[str]
    period: PeriodView | None
    baseline: PeriodView | None
    estimate_method: str | None
    source_tables: list[str]
    parent_roles: list[str]
    thresholds_version: str | None
    detectors: list[SymptomMethod]
    attribution_baseline: PeriodView | None
    attribution_current: PeriodView | None
    impact_method: str | None
    settings: list[ParameterView]


DERIVED_METHODS: dict[str, str] = {
    "profit_delta": "net_profit(current) - net_profit(baseline)",
    "profit_driver": "exact two-level Shapley contribution of a driver to the net profit change",
    "expected_monthly_impact": "incident's Shapley contributions over the current window, "
    "scaled to 30 days; P10/P50/P90 by a seeded 7-day block bootstrap",
    "derived.compute": "arithmetic over facts requested by the agent (references only)",
    "derived.difference": "last day minus first day of a daily series",
    "derived.mean": "mean of the defined days of a daily series",
    "derived.daily_slope": "OLS slope of a daily series per day, normal 80% interval",
    "derived.sum": "sum of the parts",
    "derived.gap": "whole minus the sum of its parts",
    "derived.share": "numerator divided by denominator",
}
DETECTOR_SECTIONS: dict[str, tuple[str, ...]] = {
    "campaign_cpa_z": ("robust_z", "campaign_cpa", "multiple_testing"),
    "campaign_cpa_cusum": ("cusum", "campaign_cpa"),
    "product_units_z": ("robust_z", "product_units", "multiple_testing"),
    "product_unit_cost_z": ("robust_z", "product_unit_cost", "multiple_testing"),
    "product_unit_fee_z": ("robust_z", "product_unit_fee", "multiple_testing"),
    "store_payment_fee_rate_z": ("robust_z", "store_payment_fee_rate"),
    "store_payment_fee_rate_cusum": ("cusum", "store_payment_fee_rate"),
    "store_gross_margin_rate_z": ("robust_z", "store_gross_margin_rate"),
    "store_gross_margin_rate_cusum": ("cusum", "store_gross_margin_rate"),
    "campaign_profit_negative": ("campaign_profit",),
    "product_cover_below_lead_time": ("inventory_cover",),
    "product_refund_rate_band": ("refund_rate", "multiple_testing"),
    "campaign_attribution_collapse": ("attribution_collapse",),
    "campaign_incrementality": ("incrementality",),
}


def _parameters(sections: tuple[str, ...]) -> list[ParameterView]:
    cfg = default_config().model_dump()
    return [
        ParameterView(name=f"{section}.{key}", value=str(value))
        for section in sections
        for key, value in cfg.get(section, {}).items()
    ]


def _empty_method(subject: str, kind: Literal["fact", "incident"]) -> dict[str, Any]:
    return {
        "subject": subject,
        "kind": kind,
        "formula": None,
        "formula_version": None,
        "description": None,
        "inputs": [],
        "period": None,
        "baseline": None,
        "estimate_method": None,
        "source_tables": [],
        "parent_roles": [],
        "thresholds_version": None,
        "detectors": [],
        "attribution_baseline": None,
        "attribution_current": None,
        "impact_method": None,
        "settings": [],
    }


def get_method(ctx: ToolContext, q: MethodQuery) -> MethodView:
    if q.fact_id is not None:
        found = get_facts(ctx.conn, ctx.store_id, [q.fact_id], with_lineage=True)
        if q.fact_id not in found:
            raise ToolError("not_found", f"no fact {q.fact_id}")
        fact = found[q.fact_id]
        # Attribution facts are named per driver: `profit_driver.<driver>`.
        family = (
            fact.formula_id.split(".")[0]
            if fact.formula_id.startswith("profit_driver")
            else (fact.formula_id)
        )
        description: str | None
        try:
            formula = REGISTRY.get(fact.formula_id)
            description, inputs = formula.description, list(formula.inputs)
        except UnknownFormulaError:
            description, inputs = DERIVED_METHODS.get(family), []
        out = _empty_method(f"F{q.fact_id}", "fact") | {
            "formula": fact.formula_id,
            "formula_version": f"v{fact.formula_version}",
            "description": description,
            "inputs": inputs,
            "period": _view(fact.period),
            "baseline": _view(fact.baseline) if fact.baseline else None,
            "estimate_method": fact.method,
            "source_tables": sorted({s.table for s in fact.lineage.sources}),
            "parent_roles": sorted({p.role.split(":")[0] for p in fact.lineage.parents}),
        }
        return MethodView(**out)
    assert q.incident_id is not None
    stored = load_incident(ctx.conn, ctx.store_id, q.incident_id)
    if stored is None:
        raise ToolError("not_found", f"no incident {q.incident_id}")
    incident = stored.incident
    series = ctx.series()
    baseline, current = attribution_windows(series, incident.first_seen, default_config())
    detectors = []
    for s in incident.symptoms:
        sections = DETECTOR_SECTIONS.get(s.detector_id, ())
        base_facts = get_facts(ctx.conn, ctx.store_id, s.baseline_fact_ids)
        ends = [f.period.end.date() for f in base_facts.values()]
        detectors.append(
            SymptomMethod(
                detector=s.detector_id,
                metric=s.metric,
                sections=list(sections),
                parameters=_parameters(sections),
                baseline_ends_before_first_seen=max(ends) <= s.first_seen if ends else None,
            )
        )
    out = _empty_method(incident.incident_id, "incident") | {
        "thresholds_version": f"v{stored.thresholds_version}",
        "detectors": detectors,
        "attribution_baseline": _view(baseline),
        "attribution_current": _view(current),
        "impact_method": DERIVED_METHODS["expected_monthly_impact"],
        "settings": _parameters(("attribution", "materiality", "noise_band", "incidents")),
    }
    return MethodView(**out)


AUDIT_TOOLS: list[Tool[Any, Any]] = [
    Tool(
        "run_sensitivity",
        "Robustness audit of an incident: attribution, expected impact and "
        "top candidate cause recomputed under fixed window variants (baseline shifted by 7 days "
        "either way; windows of 14, 28 and 42 days). `stable` is computed by code.",
        SensitivityQuery,
        SensitivityView,
        run_sensitivity,
    ),
    Tool(
        "check_reconciliation",
        "Consistency audit: product sums against store totals for each "
        "money metric, and platform-attributed purchases against real orders of the promoted "
        "products, as gap facts.",
        ReconciliationQuery,
        ReconciliationView,
        check_reconciliation,
    ),
    Tool(
        "get_method",
        "Method audit: how a fact or an incident was computed (formula and version, "
        "windows, detector thresholds, settings).",
        MethodQuery,
        MethodView,
        get_method,
    ),
]
