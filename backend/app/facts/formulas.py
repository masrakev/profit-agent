"""Formula definitions (version 1). See `docs/adr/0002-exact-money-in-sql.md`.

Base formulas aggregate NUMERIC columns in SQL. Derived formulas combine parent facts with exact
Decimal arithmetic (sums and differences trap on any rounding) or one HALF_EVEN division (ratios).
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from decimal import Decimal

from app.domain.hashing import canonical_json, sha256_hex
from app.facts import sql
from app.facts.arith import UndefinedValue, exact_mul, exact_sub, exact_sum, ratio
from app.facts.model import (
    Fact,
    FactKind,
    Lineage,
    ParentRef,
    Period,
    Scope,
    ScopeKind,
    SourceRef,
    Unit,
)
from app.facts.registry import Computed, ComputeFn, FactContext, Formula, FormulaRegistry

STORE = frozenset({ScopeKind.STORE})
PRODUCT = frozenset({ScopeKind.PRODUCT})
CAMPAIGN = frozenset({ScopeKind.CAMPAIGN})
STORE_PRODUCT = STORE | PRODUCT
STORE_CAMPAIGN = STORE | CAMPAIGN

INVENTORY_TRAILING_DAYS = 28

ParentSpec = tuple[str, str, Scope, Period]  # (role, formula_id, scope, period)


def from_aggregate(ctx: FactContext, agg: sql.Aggregate, *, money: bool) -> Computed:
    lineage = Lineage(sources=tuple(SourceRef(table=agg.table, id=i) for i in agg.ids))
    currency = ctx.currency if money else None
    if money:
        foreign = sorted(agg.currencies - {ctx.currency})
        if foreign:
            return Computed(
                value=None,
                currency=currency,
                inputs_hash=agg.inputs_hash,
                lineage=lineage,
                undefined_reason=(
                    f"rows in {', '.join(foreign)} differ from store currency {ctx.currency}; "
                    "currency conversion is not supported"
                ),
            )
    return Computed(agg.value, currency, agg.inputs_hash, lineage)


def derive(
    ctx: FactContext,
    parents: Sequence[ParentSpec],
    fn: Callable[[Mapping[str, Decimal]], Decimal],
    *,
    money: bool,
) -> Computed:
    """Compute a fact from parent facts, propagating undefined parents and checking currencies."""
    facts: dict[str, Fact] = {
        role: ctx.fact(fid, scope, period) for role, fid, scope, period in parents
    }
    lineage = Lineage(
        parents=tuple(ParentRef(role=role, fact_hash=f.fact_hash) for role, f in facts.items())
    )
    inputs_hash = sha256_hex(
        canonical_json(sorted([role, f.fact_hash] for role, f in facts.items()))
    )
    currency = ctx.currency if money else None

    def undefined(reason: str) -> Computed:
        return Computed(None, currency, inputs_hash, lineage, reason)

    missing = [f for f in facts.values() if not f.is_defined]
    if missing:
        return undefined(
            "; ".join(f"{f.formula_id} is undefined ({f.undefined_reason})" for f in missing)
        )
    currencies = {f.currency for f in facts.values() if f.currency is not None}
    if len(currencies) > 1:
        return undefined(f"parent facts mix currencies {sorted(currencies)}")
    values = {role: f.value for role, f in facts.items() if f.value is not None}
    try:
        value = fn(values)
    except UndefinedValue as exc:
        return undefined(exc.reason)
    return Computed(value, currency, inputs_hash, lineage)


def _same(scope: Scope, period: Period, *pairs: tuple[str, str]) -> list[ParentSpec]:
    return [(role, fid, scope, period) for role, fid in pairs]


# --- base formulas over order lines and refunds -------------------------------------------------


def _lines(value_expr: str, repr_columns: tuple[str, ...], *, money: bool) -> ComputeFn:
    def compute(ctx: FactContext, scope: Scope, period: Period) -> Computed:
        agg = sql.line_aggregate(
            ctx.conn,
            ctx.store_id,
            scope,
            period,
            value_expr=value_expr,
            repr_columns=repr_columns,
        )
        return from_aggregate(ctx, agg, money=money)

    return compute


def _refunds(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    return from_aggregate(
        ctx, sql.refund_aggregate(ctx.conn, ctx.store_id, scope, period), money=True
    )


REVENUE = _lines("ol.net_amount", ("ol.net_amount",), money=True)
UNITS = _lines("ol.quantity", ("ol.quantity",), money=False)
COGS = _lines(
    "ol.quantity * ol.unit_cost_at_sale", ("ol.quantity", "ol.unit_cost_at_sale"), money=True
)
FEES = _lines(
    "ol.quantity * ol.unit_fee_at_sale + ol.payment_fee_alloc",
    ("ol.quantity", "ol.unit_fee_at_sale", "ol.payment_fee_alloc"),
    money=True,
)


def _contribution(prefix: str) -> ComputeFn:
    def compute(ctx: FactContext, scope: Scope, period: Period) -> Computed:
        return derive(
            ctx,
            _same(
                scope,
                period,
                ("revenue", f"{prefix}revenue"),
                ("cogs", f"{prefix}cogs"),
                ("fees", f"{prefix}fees"),
                ("refunds", f"{prefix}refunds"),
            ),
            lambda v: exact_sub(v["revenue"], v["cogs"], v["fees"], v["refunds"]),
            money=True,
        )

    return compute


def _gross_margin(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    return derive(
        ctx,
        _same(scope, period, ("revenue", "revenue"), ("cogs", "cogs")),
        lambda v: exact_sub(v["revenue"], v["cogs"]),
        money=True,
    )


# --- advertising -------------------------------------------------------------------------------


def _ad_metric(column: str, *, money: bool) -> ComputeFn:
    def compute(ctx: FactContext, scope: Scope, period: Period) -> Computed:
        agg = sql.ad_metric_aggregate(ctx.conn, ctx.store_id, scope, period, column=column)
        return from_aggregate(ctx, agg, money=money)

    return compute


def _campaign_attributed_contribution(v: Mapping[str, Decimal]) -> Decimal:
    if v["attributed_revenue"] == 0:
        return Decimal(0)
    return ratio(
        exact_mul(v["attributed_revenue"], v["promoted_contribution_margin"]),
        v["promoted_revenue"],
        denominator_name="promoted_revenue",
    )


def _attributed_contribution(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    if scope.kind is ScopeKind.CAMPAIGN:
        return derive(
            ctx,
            _same(
                scope,
                period,
                ("attributed_revenue", "attributed_revenue"),
                ("promoted_revenue", "promoted_revenue"),
                ("promoted_contribution_margin", "promoted_contribution_margin"),
            ),
            _campaign_attributed_contribution,
            money=True,
        )
    parents: list[ParentSpec] = [
        (f"campaign:{cid}", "attributed_contribution", Scope.campaign(cid), period)
        for cid in sql.campaign_ids(ctx.conn, ctx.store_id)
    ]
    return derive(ctx, parents, lambda v: exact_sum(*v.values()), money=True)


def _ratio_of(numerator: str, denominator: str, *, money: bool) -> ComputeFn:
    def compute(ctx: FactContext, scope: Scope, period: Period) -> Computed:
        return derive(
            ctx,
            _same(scope, period, ("numerator", numerator), ("denominator", denominator)),
            lambda v: ratio(v["numerator"], v["denominator"], denominator_name=denominator),
            money=money,
        )

    return compute


def _campaign_profit(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    return derive(
        ctx,
        _same(
            scope,
            period,
            ("attributed_contribution", "attributed_contribution"),
            ("ad_spend", "ad_spend"),
        ),
        lambda v: exact_sub(v["attributed_contribution"], v["ad_spend"]),
        money=True,
    )


def _attribution_ratio(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    sales = "promoted_revenue" if scope.kind is ScopeKind.CAMPAIGN else "revenue"
    return _ratio_of("attributed_revenue", sales, money=False)(ctx, scope, period)


# --- store-level profit ------------------------------------------------------------------------


def _contribution_after_ads(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    return derive(
        ctx,
        _same(
            scope, period, ("contribution_margin", "contribution_margin"), ("ad_spend", "ad_spend")
        ),
        lambda v: exact_sub(v["contribution_margin"], v["ad_spend"]),
        money=True,
    )


def _fixed_costs(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    return from_aggregate(ctx, sql.fixed_cost_aggregate(ctx.conn, ctx.store_id, period), money=True)


def _net_profit(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    return derive(
        ctx,
        _same(
            scope,
            period,
            ("contribution_after_ads", "contribution_after_ads"),
            ("fixed_costs", "fixed_costs"),
        ),
        lambda v: exact_sub(v["contribution_after_ads"], v["fixed_costs"]),
        money=True,
    )


# --- inventory ---------------------------------------------------------------------------------


def _units_on_hand(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    assert scope.id is not None
    agg = sql.latest_inventory(ctx.conn, ctx.store_id, scope.id, period)
    if agg is None:
        inputs_hash = sha256_hex(
            canonical_json(
                {"table": "inventory_snapshots", "product": scope.id, "none_before": period.end}
            )
        )
        return Computed(
            None, None, inputs_hash, undefined_reason="no inventory snapshot before period end"
        )
    return from_aggregate(ctx, agg, money=False)


def _inventory_cover_days(ctx: FactContext, scope: Scope, period: Period) -> Computed:
    trailing = Period(start=period.end - timedelta(days=INVENTORY_TRAILING_DAYS), end=period.end)
    return derive(
        ctx,
        [
            ("units_on_hand", "units_on_hand", scope, period),
            ("units_trailing", "units", scope, trailing),
        ],
        lambda v: ratio(
            exact_mul(v["units_on_hand"], Decimal(INVENTORY_TRAILING_DAYS)),
            v["units_trailing"],
            denominator_name=f"units sold in the trailing {INVENTORY_TRAILING_DAYS} days",
        ),
        money=False,
    )


# --- registry ----------------------------------------------------------------------------------


def build_registry() -> FormulaRegistry:
    registry = FormulaRegistry()

    def add(
        formula_id: str,
        unit: Unit,
        scopes: frozenset[ScopeKind],
        compute: ComputeFn,
        description: str,
        inputs: tuple[str, ...] = (),
    ) -> None:
        registry.register(
            Formula(
                formula_id=formula_id,
                version=1,
                kind=FactKind.EXACT,
                unit=unit,
                scopes=scopes,
                inputs=inputs,
                description=description,
                compute=compute,
            )
        )

    sales = "order lines of non-cancelled orders, by order date (UTC)"
    promoted = "over all sales of the products the campaign promotes (not only ad-attributed)"
    for prefix, scopes, suffix in (
        ("", STORE_PRODUCT, ""),
        ("promoted_", CAMPAIGN, f" {promoted}"),
    ):
        add(
            f"{prefix}revenue",
            Unit.MONEY,
            scopes,
            REVENUE,
            f"Σ line net amount (unit price × quantity − discount; excludes tax and shipping) of "
            f"{sales}{suffix}",
        )
        add(f"{prefix}cogs", Unit.MONEY, scopes, COGS, f"Σ quantity × unit_cost_at_sale{suffix}")
        add(
            f"{prefix}fees",
            Unit.MONEY,
            scopes,
            FEES,
            "Σ quantity × unit_fee_at_sale + payment fee allocated to the line "
            f"(pro rata to line net amount){suffix}",
        )
        add(
            f"{prefix}refunds",
            Unit.MONEY,
            scopes,
            _refunds,
            f"Σ merchandise refund amounts (excl. tax and shipping), by refund date (UTC){suffix}",
        )
        add(
            f"{prefix}contribution_margin",
            Unit.MONEY,
            scopes,
            _contribution(prefix),
            f"revenue − cogs − fees − refunds{suffix}",
            inputs=tuple(f"{prefix}{n}" for n in ("revenue", "cogs", "fees", "refunds")),
        )
    add("units", Unit.COUNT, STORE_PRODUCT, UNITS, f"Σ quantity of {sales}")
    add(
        "gross_margin",
        Unit.MONEY,
        STORE_PRODUCT,
        _gross_margin,
        "revenue − cogs",
        inputs=("revenue", "cogs"),
    )
    add(
        "ad_spend",
        Unit.MONEY,
        STORE_CAMPAIGN,
        _ad_metric("spend", money=True),
        "Σ daily ad spend; a day counts when its UTC midnight is in the period",
    )
    add(
        "attributed_revenue",
        Unit.MONEY,
        STORE_CAMPAIGN,
        _ad_metric("attributed_revenue", money=True),
        "Σ revenue attributed by the ad platform (platform-reported, not reconciled to orders)",
    )
    add(
        "attributed_purchases",
        Unit.COUNT,
        STORE_CAMPAIGN,
        _ad_metric("attributed_purchases", money=False),
        "Σ purchases attributed by the ad platform",
    )
    add(
        "attributed_contribution",
        Unit.MONEY,
        STORE_CAMPAIGN,
        _attributed_contribution,
        "campaign: attributed_revenue × promoted_contribution_margin ÷ promoted_revenue "
        "(0 when attributed_revenue is 0); store: Σ over campaigns",
        inputs=("attributed_revenue", "promoted_revenue", "promoted_contribution_margin"),
    )
    add(
        "roas",
        Unit.RATIO,
        STORE_CAMPAIGN,
        _ratio_of("attributed_revenue", "ad_spend", money=False),
        "attributed_revenue ÷ ad_spend",
        inputs=("attributed_revenue", "ad_spend"),
    )
    add(
        "poas",
        Unit.RATIO,
        STORE_CAMPAIGN,
        _ratio_of("attributed_contribution", "ad_spend", money=False),
        "attributed_contribution ÷ ad_spend",
        inputs=("attributed_contribution", "ad_spend"),
    )
    add(
        "cpa",
        Unit.MONEY,
        STORE_CAMPAIGN,
        _ratio_of("ad_spend", "attributed_purchases", money=True),
        "ad_spend ÷ attributed_purchases",
        inputs=("ad_spend", "attributed_purchases"),
    )
    add(
        "contribution_after_ads",
        Unit.MONEY,
        STORE,
        _contribution_after_ads,
        "contribution_margin − ad_spend",
        inputs=("contribution_margin", "ad_spend"),
    )
    add(
        "fixed_costs",
        Unit.MONEY,
        STORE,
        _fixed_costs,
        "Σ fixed cost item amount × (overlap of item span with period ÷ item span)",
    )
    add(
        "net_profit",
        Unit.MONEY,
        STORE,
        _net_profit,
        "contribution_after_ads − fixed_costs",
        inputs=("contribution_after_ads", "fixed_costs"),
    )
    add(
        "units_on_hand",
        Unit.COUNT,
        PRODUCT,
        _units_on_hand,
        "units on hand in the latest end-of-day snapshot whose day ended by the period end",
    )
    add(
        "inventory_cover_days",
        Unit.DAYS,
        PRODUCT,
        _inventory_cover_days,
        f"units_on_hand ÷ (units sold in [end − {INVENTORY_TRAILING_DAYS}d, end) ÷ "
        f"{INVENTORY_TRAILING_DAYS})",
        inputs=("units_on_hand", "units"),
    )
    add(
        "campaign_profit",
        Unit.MONEY,
        CAMPAIGN,
        _campaign_profit,
        "attributed_contribution − ad_spend",
        inputs=("attributed_contribution", "ad_spend"),
    )
    add(
        "mer",
        Unit.RATIO,
        STORE,
        _ratio_of("revenue", "ad_spend", money=False),
        "revenue ÷ ad_spend (marketing efficiency ratio)",
        inputs=("revenue", "ad_spend"),
    )
    add(
        "attribution_ratio",
        Unit.RATIO,
        STORE_CAMPAIGN,
        _attribution_ratio,
        "campaign: attributed_revenue ÷ promoted_revenue; store: attributed_revenue ÷ revenue",
        inputs=("attributed_revenue", "promoted_revenue", "revenue"),
    )
    add(
        "refund_rate",
        Unit.RATIO,
        STORE_PRODUCT,
        _ratio_of("refunds", "revenue", money=False),
        "refunds (by refund date) ÷ revenue (by order date)",
        inputs=("refunds", "revenue"),
    )
    return registry


REGISTRY = build_registry()
