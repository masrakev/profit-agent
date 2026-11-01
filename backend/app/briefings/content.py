"""Assemble a briefing from facts (SPEC sections 5.1 to 5.3): sections, items and their order are
decided here, and every quantity is a persisted fact. A model only adds a short narrative on top
(app.briefings.service), and the briefing is complete without it.

Conventions (ADR 0019):
- the daily brief's "yesterday" is the last day of data, "this week" the seven days ending then;
- weekly: the last complete Monday-Sunday week, against the week before and the average of the
  four weeks before; monthly: the last complete calendar month, against the month before and the
  average of up to three months before;
- open incidents are those of the latest detection run; money at stake adds up their expected
  monthly impacts (estimates); data-quality incidents go to the data notice, never to the top
  items;
- decisions, actions and outcomes are listed for the time since the previous briefing of the
  same kind (real time: what happened since the owner last read one).
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import numpy as np
from sqlalchemy import Connection, text

from app.agent.tools.derived import compute, total
from app.briefings import periods, wording
from app.briefings.facts import Cited
from app.briefings.models import (
    BriefingContent,
    BriefingKind,
    Button,
    ButtonKind,
    Item,
    Section,
    Table,
)
from app.causes.drivers import LEVEL1_DRIVERS, Driver
from app.causes.noise import noise_band
from app.causes.profit import (
    AttributionUnavailableError,
    ProfitAttribution,
    attribute_profit_change,
)
from app.decisions.options import UNDERFUNDED_CAMPAIGN, OptionKind, build_options
from app.decisions.store import DecisionStatus, DecisionView, get
from app.detection.config import default_config
from app.detection.models import (
    ALERT_RANK,
    AlertLevel,
    FaultFamily,
    Incident,
    SymptomCategory,
)
from app.detection.pipeline import daily_figures
from app.detection.repository import load_incidents
from app.detection.series import StoreSeries, load_series
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.model import Fact, Period, Scope
from app.goals import service as goal_service
from app.policies.trust import trust_ledger
from app.settings.models import AutonomyLevel, StoreSettings
from app.settings.repository import StoreSettingsRepository
from app.twin import fit_twin
from app.twin.facts import input_facts, simulation_facts

MAX_TOP_ITEMS = 3
MAX_PRODUCTS = 5
MAX_OPPORTUNITIES = 3
SUMMARY_METRICS = (
    ("net_profit", "Net profit"),
    ("contribution_margin", "Contribution margin"),
    ("revenue", "Revenue"),
    ("ad_spend", "Ad spend"),
)
PRODUCT_DRIVERS = (
    Driver.VOLUME,
    Driver.MIX,
    Driver.PRICE,
    Driver.UNIT_COST,
    Driver.FEES,
    Driver.REFUNDS,
)
AUTONOMY = {
    AutonomyLevel.OBSERVE: "observe",
    AutonomyLevel.RECOMMEND: "recommend, you approve",
    AutonomyLevel.EXECUTE_CAPPED: "execute within the caps",
    AutonomyLevel.MANAGE_SCOPE: "manage a scope",
}
ACTIONS = {
    "pause_campaign": "pause a campaign",
    "resume_campaign": "resume a campaign",
    "change_budget": "change a daily budget",
}
SINCE = {
    BriefingKind.DAILY: timedelta(days=1),
    BriefingKind.WEEKLY: timedelta(days=7),
    BriefingKind.MONTHLY: timedelta(days=31),
}


@dataclass
class Context:
    conn: Connection
    store_id: UUID
    cited: Cited
    series: StoreSeries
    settings: StoreSettings
    day: date  # the last day of data the briefing covers
    stale: bool  # data stops before the store's local yesterday
    now: datetime

    @property
    def first(self) -> date:
        return self.series.start


def context(conn: Connection, store_id: UUID, *, local_today: date, now: datetime) -> Context:
    series = load_series(conn, store_id)
    if series.days == 0:
        raise ValueError("the store has no data yet")
    data_end = series.day(series.days)
    return Context(
        conn=conn,
        store_id=store_id,
        cited=Cited(conn, store_id),
        series=series,
        settings=StoreSettingsRepository(conn).get_or_default(store_id),
        day=periods.last_day(data_end, local_today),
        stale=data_end < local_today,
        now=now,
    )


def build(
    conn: Connection, store_id: UUID, kind: BriefingKind, *, local_today: date, now: datetime
) -> BriefingContent:
    ctx = context(conn, store_id, local_today=local_today, now=now)
    builder = {
        BriefingKind.DAILY: daily_brief,
        BriefingKind.WEEKLY: weekly_report,
        BriefingKind.MONTHLY: monthly_review,
    }[kind]
    return builder(ctx)


def _finish(
    ctx: Context,
    kind: BriefingKind,
    period: tuple[date, date],
    headline: str,
    sections: Sequence[Section],
    *,
    nothing_material: bool = False,
    incident_ids: Sequence[str] = (),
) -> BriefingContent:
    return BriefingContent(
        kind=kind,
        period_start=period[0],
        period_end=period[1],
        headline=headline,
        nothing_material=nothing_material,
        sections=tuple(s for s in sections if s.items or s.table or s.empty),
        fact_ids=tuple(sorted(ctx.cited.facts)),
        entities=tuple(sorted(ctx.cited.entities)),
        incident_ids=tuple(incident_ids),
    )


# --- shared pieces ---------------------------------------------------------------------------


def entity_ref(ctx: Context, entity: str) -> str:
    return ctx.cited.entity("store" if entity in ("store", "") else entity)


def open_incidents(conn: Connection, store_id: UUID) -> list[Incident]:
    """The latest detection run's incidents, most urgent first."""
    stored = load_incidents(conn, store_id)
    if not stored:
        return []
    latest = max(s.as_of for s in stored)
    current = [s.incident for s in stored if s.as_of == latest]
    return sorted(current, key=lambda i: (ALERT_RANK[i.alert], -i.severity_score, i.incident_id))


def incident_entity(incident: Incident) -> str:
    top = incident.candidates[0] if incident.candidates else None
    ref = top.entity if top is not None else (incident.entities[0] if incident.entities else None)
    return "store" if ref is None or ref.id is None else str(ref)


def top_family(incident: Incident) -> FaultFamily | None:
    return incident.candidates[0].family if incident.candidates else None


def impact_of(ctx: Context, incident: Incident) -> Fact | None:
    if incident.monthly_impact_fact_id is None:
        return None
    return ctx.cited.load([incident.monthly_impact_fact_id]).get(incident.monthly_impact_fact_id)


def decision_for(ctx: Context, incident_id: str) -> DecisionView | None:
    found = ctx.conn.execute(
        text(
            "SELECT decision_id FROM decisions WHERE store_id = :s AND incident_id = :i "
            "AND status = 'proposed' AND expires_at > :now ORDER BY created_at DESC LIMIT 1"
        ),
        {"s": ctx.store_id, "i": incident_id, "now": ctx.now},
    ).scalar()
    return None if found is None else get(ctx.conn, ctx.store_id, found)


def _recommended(ctx: Context, decision: DecisionView) -> tuple[str, tuple[Button, ...]]:
    option = decision.option(decision.recommended_option_id)
    words = wording.option(option.kind)
    if option.impact_fact_id is not None:
        impact = ctx.cited.load([option.impact_fact_id]).get(option.impact_fact_id)
        if impact is not None:
            words += f", expected net-profit change {ctx.cited.ref(impact)}"
    did = str(decision.decision_id)
    buttons = (
        Button(
            kind=ButtonKind.APPROVE,
            label="Approve",
            decision_id=did,
            option_id=option.option_id,
        ),
        Button(kind=ButtonKind.REVIEW, label="Review options", decision_id=did),
    )
    return words, buttons


def incident_item(ctx: Context, incident: Incident) -> Item:
    entity = entity_ref(ctx, incident_entity(incident))
    parts = [f"{entity}: {wording.cause(top_family(incident))}."]
    impact = impact_of(ctx, incident)
    loss = ctx.cited.loss(impact) if impact is not None else None
    if loss is not None:
        parts.append(f"It costs about {ctx.cited.ref(loss)} a month.")
    elif impact is not None and impact.is_defined:
        parts.append(f"Expected impact: {ctx.cited.ref(impact)} a month.")
    evidence = Button(kind=ButtonKind.EVIDENCE, label="Evidence", incident_id=incident.incident_id)
    decision = decision_for(ctx, incident.incident_id)
    if decision is not None:
        words, buttons = _recommended(ctx, decision)
        parts.append(f"Recommended: {words}.")
        return Item(
            text=" ".join(parts),
            level=incident.alert.value,
            incident_id=incident.incident_id,
            decision_id=str(decision.decision_id),
            buttons=(*buttons, evidence),
        )
    parts.append("Recommended: review the evidence before acting.")
    return Item(
        text=" ".join(parts),
        level=incident.alert.value,
        incident_id=incident.incident_id,
        buttons=(evidence,),
    )


def data_quality_item(ctx: Context, incident: Incident) -> Item:
    entity = entity_ref(ctx, incident_entity(incident))
    return Item(
        text=f"Data issue, not a profit issue: {entity}: {wording.cause(top_family(incident))}. "
        "Its reported numbers are unreliable until it is fixed; no budget action is "
        "recommended until then.",
        level=AlertLevel.DATA_QUALITY.value,
        incident_id=incident.incident_id,
        buttons=(
            Button(kind=ButtonKind.EVIDENCE, label="Evidence", incident_id=incident.incident_id),
        ),
    )


def pending_decisions(ctx: Context) -> Section:
    ids = ctx.conn.execute(
        text(
            "SELECT decision_id FROM decisions WHERE store_id = :s AND status = 'proposed' "
            "AND expires_at > :now ORDER BY created_at"
        ),
        {"s": ctx.store_id, "now": ctx.now},
    ).scalars()
    items = []
    for did in ids:
        decision = get(ctx.conn, ctx.store_id, did)
        words, buttons = _recommended(ctx, decision)
        items.append(
            Item(
                text=f"{entity_ref(ctx, decision.entity)}: {words}.",
                decision_id=str(did),
                incident_id=decision.incident_id,
                buttons=buttons,
            )
        )
    return Section(
        key="pending_decisions",
        title="Pending decisions",
        items=tuple(items),
        empty="No decision is waiting for you.",
    )


def data_notice(ctx: Context, incidents: Sequence[Incident]) -> Section:
    items: list[Item] = []
    if ctx.stale:
        items.append(
            Item(
                text="Your store data stops before yesterday: figures cover the latest day "
                "with data."
            )
        )
    latest = ctx.conn.execute(
        text(
            "SELECT (SELECT max(metric_date) FROM ad_metrics_daily WHERE store_id = :s), "
            "(SELECT max(ordered_at)::date FROM orders WHERE store_id = :s)"
        ),
        {"s": ctx.store_id},
    ).one()
    if latest[0] is not None and latest[1] is not None and latest[0] < latest[1]:
        items.append(
            Item(text="Ad data is behind your orders: ad figures for the latest days may be low.")
        )
    items.extend(data_quality_item(ctx, i) for i in incidents if i.alert is AlertLevel.DATA_QUALITY)
    return Section(key="data_notice", title="Data notice", items=tuple(items))


def _since(ctx: Context, kind: BriefingKind) -> datetime:
    previous = ctx.conn.execute(
        text(
            "SELECT max(created_at) FROM briefings WHERE store_id = :s AND kind = :k "
            "AND created_at < :now"
        ),
        {"s": ctx.store_id, "k": kind.value, "now": ctx.now},
    ).scalar()
    return previous or ctx.now - SINCE[kind]


# --- 5.1 daily brief -------------------------------------------------------------------------


def daily_brief(ctx: Context) -> BriefingContent:
    day = ctx.day
    c, store = ctx.cited, Scope.store()
    yesterday = c.get("net_profit", store, day, day + timedelta(days=1))
    week = (day - timedelta(days=6), day + timedelta(days=1))
    before = periods.previous(week)
    this_week = c.get("net_profit", store, *week)
    last_week = c.get("net_profit", store, *before)
    health = Section(
        key="health",
        title="Health",
        items=(
            Item(
                text=f"Net profit yesterday {c.ref(yesterday)}; this week {c.ref(this_week)} "
                f"against {c.ref(last_week)} the week before, "
                f"{c.direction(c.change(this_week, last_week))}."
            ),
        ),
    )
    incidents = open_incidents(ctx.conn, ctx.store_id)
    alerts = [
        i
        for i in incidents
        if i.is_alert
        and i.category is SymptomCategory.PROFITABILITY
        and i.alert is not AlertLevel.DATA_QUALITY
    ]
    impacts = [f for f in (impact_of(ctx, i) for i in alerts) if f is not None]
    losses = [x for x in (c.loss(f) for f in impacts) if x is not None]
    stake = c.stake(losses, *periods.day_period(day))
    money = Section(
        key="money_at_stake",
        title="Money at stake",
        items=(Item(text=f"About {c.ref(stake)} a month across open problems."),)
        if stake is not None
        else (),
    )
    top = [incident_item(ctx, i) for i in alerts[:MAX_TOP_ITEMS]]
    pending = pending_decisions(ctx)
    shown = {i.decision_id for i in top if i.decision_id}
    pending = pending.model_copy(
        update={"items": tuple(i for i in pending.items if i.decision_id not in shown)}
    )
    notice = data_notice(ctx, incidents)
    nothing = not top and not pending.items
    if nothing:
        return _finish(
            ctx,
            BriefingKind.DAILY,
            periods.day_period(day),
            "Nothing needs your attention today.",
            [health, notice],
            nothing_material=True,
            incident_ids=[i.incident_id for i in notice.items if i.incident_id],
        )
    critical = any(i.level == AlertLevel.CRITICAL.value for i in top)
    headline = (
        "A critical problem needs your attention today."
        if critical
        else "Some items need your attention today."
        if top
        else "A decision is waiting for you."
    )
    return _finish(
        ctx,
        BriefingKind.DAILY,
        periods.day_period(day),
        headline,
        [
            health,
            money,
            Section(key="top_items", title="Top items", items=tuple(top)),
            pending,
            notice,
        ],
        incident_ids=[i.incident_id for i in (*top, *notice.items) if i.incident_id],
    )


# --- 5.2 weekly report and 5.3 monthly review ------------------------------------------------


def _chain(period: tuple[date, date], count: int, *, monthly: bool) -> list[tuple[date, date]]:
    out, current = [], period
    for _ in range(count):
        current = periods.previous(current, monthly=monthly)
        out.append(current)
    return out


def summary(ctx: Context, period: tuple[date, date], *, monthly: bool, unit: str) -> Section:
    """Each metric this period, the period before, and the average of the periods before that
    are fully in the data (four weeks, or up to three months; at least two)."""
    c, store = ctx.cited, Scope.store()
    before = _chain(period, 3 if monthly else 4, monthly=monthly)
    history = [p for p in before if p[0] >= ctx.first]
    items = []
    for metric, label in SUMMARY_METRICS:
        current = c.get(metric, store, *period)
        last = c.get(metric, store, *before[0])
        line = (
            f"{label}: {c.ref(current)} this {unit} against {c.ref(last)} last {unit} "
            f"({c.direction(c.change(current, last))})"
        )
        if len(history) >= 2:
            parts = [c.get(metric, store, *p) for p in history]
            average = c.average(parts, history[-1][0], history[0][1])
            line += f", and {c.ref(average)} on average over the previous {unit}s"
        items.append(Item(text=line + "."))
    return Section(key="summary", title="Summary", items=tuple(items))


def _bridge(
    ctx: Context, period: tuple[date, date], baseline: tuple[date, date]
) -> ProfitAttribution:
    cfg = default_config()
    seed = int(sha256_hex(canonical_json([str(ctx.store_id), "briefing", period]))[:16], 16)
    band = noise_band(
        daily_figures(ctx.series),
        length=(period[1] - period[0]).days,
        history_end=ctx.series.index(baseline[1]),
        rng=np.random.default_rng(seed),
        resamples=cfg.noise_band.resamples,
        min_pairs=cfg.noise_band.min_pairs,
        quantiles=(cfg.noise_band.low_percentile, cfg.noise_band.high_percentile),
    )
    return attribute_profit_change(
        ctx.cited.engine, Period.days(*baseline), Period.days(*period), band
    )


def profit_bridge(
    ctx: Context, period: tuple[date, date], baseline: tuple[date, date]
) -> tuple[Section, ProfitAttribution | None]:
    c = ctx.cited
    try:
        attribution = _bridge(ctx, period, baseline)
    except AttributionUnavailableError:
        return (
            Section(
                key="profit_bridge",
                title="Profit bridge",
                empty="The profit bridge is not available for this period.",
            ),
            None,
        )
    facts = c.load([attribution.delta_fact_id, *(x.fact_id for x in attribution.level1.values())])
    delta = facts[attribution.delta_fact_id]
    items = [Item(text=f"Change in net profit: {c.direction(delta)}.")]
    for driver in LEVEL1_DRIVERS:
        contribution = attribution.level1.get(driver)
        if contribution is None:
            continue
        note = " (not significant)" if contribution.significant is False else ""
        label = wording.DRIVERS[driver].capitalize()
        part = facts[contribution.fact_id]
        items.append(Item(text=f"{label}: {c.gain_or_loss(part)}{note}."))
    return Section(key="profit_bridge", title="Profit bridge", items=tuple(items)), attribution


def campaigns(ctx: Context, period: tuple[date, date], baseline: tuple[date, date]) -> Section:
    c = ctx.cited
    rows: list[tuple[Decimal, tuple[str, ...]]] = []
    for cid in sorted(ctx.series.campaigns, key=str):
        scope = Scope.campaign(cid)
        spend = c.get("ad_spend", scope, *period)
        if not spend.is_defined or not spend.value:
            continue
        profit = c.get("campaign_profit", scope, *period)
        last = c.get("campaign_profit", scope, *baseline)
        rows.append(
            (
                profit.value if profit.value is not None else Decimal("Infinity"),
                (
                    c.entity(f"campaign:{cid}"),
                    c.ref(spend),
                    c.ref(c.get("attributed_contribution", scope, *period)),
                    c.amount(profit),
                    c.ref(c.get("poas", scope, *period)),
                    c.direction(c.change(profit, last)),
                    c.ref(c.get("attribution_ratio", scope, *period)),
                ),
            )
        )
    rows.sort(key=lambda r: r[0])
    return Section(
        key="campaigns",
        title="Campaigns",
        table=Table(
            columns=(
                "Campaign",
                "Spend",
                "Attributed contribution",
                "Campaign profit",
                "POAS",
                "Change in profit",
                "Attribution ratio",
            ),
            rows=tuple(r for _, r in rows),
        )
        if rows
        else None,
        empty=None if rows else "No campaign spent in this period.",
    )


def products(
    ctx: Context, attribution: ProfitAttribution | None, period: tuple[date, date]
) -> list[Section]:
    if attribution is None:
        return []
    c = ctx.cited
    by_product: dict[UUID, list[tuple[Driver, int]]] = defaultdict(list)
    for driver in PRODUCT_DRIVERS:
        for contribution in attribution.level2.get(driver, []):
            if contribution.scope.id is not None:
                by_product[contribution.scope.id].append((driver, contribution.fact_id))
    facts = c.load([fid for parts in by_product.values() for _, fid in parts])
    totals: list[tuple[Decimal, UUID, Fact, Driver, Fact]] = []
    for pid, parts in by_product.items():
        pieces = [facts[fid] for _, fid in parts]
        whole = c.keep(total(pieces, Scope.product(pid), Period.days(*period), pieces[0]))
        driver, fid = max(parts, key=lambda p: (abs(facts[p[1]].value or 0), p[0].value))
        totals.append((whole.value or Decimal(0), pid, whole, driver, facts[fid]))

    def item(entry: tuple[Decimal, UUID, Fact, Driver, Fact]) -> Item:
        _, pid, whole, driver, part = entry
        return Item(
            text=f"{c.entity(f'product:{pid}')} {c.gain_or_loss(whole)}, mostly "
            f"through {wording.DRIVERS[driver]} ({c.gain_or_loss(part)})."
        )

    gainers = sorted((t for t in totals if t[0] > 0), key=lambda t: (-t[0], str(t[1])))
    decliners = sorted((t for t in totals if t[0] < 0), key=lambda t: (t[0], str(t[1])))
    return [
        Section(
            key="products_up",
            title="Products gaining profit",
            items=tuple(item(t) for t in gainers[:MAX_PRODUCTS]),
        ),
        Section(
            key="products_down",
            title="Products losing profit",
            items=tuple(item(t) for t in decliners[:MAX_PRODUCTS]),
        ),
    ]


def inventory(ctx: Context, period: tuple[date, date]) -> Section:
    """Products out of stock, or whose stock covers less than the supplier lead time; those
    still advertised first."""
    c = ctx.cited
    found: list[tuple[bool, bool, str, Item]] = []
    for pid in sorted(ctx.series.products, key=str):
        scope = Scope.product(pid)
        span = Period.days(*period)
        on_hand = c.engine.fact("units_on_hand", scope, span)
        cover = c.engine.fact("inventory_cover_days", scope, span)
        lead = c.engine.fact("supplier_lead_time_days", scope, span)
        out = on_hand.is_defined and on_hand.value == 0
        short = cover.value is not None and lead.value is not None and cover.value < lead.value
        if not (out or short):
            continue
        product = c.entity(f"product:{pid}")
        if out:
            line = f"{product}: out of stock ({c.ref(c.keep(on_hand))} on hand)"
        else:
            line = f"{product}: stock covers {c.ref(c.keep(cover))}"
        if lead.is_defined:
            line += f", against a supplier lead time of {c.ref(c.keep(lead))}"
        promoters = [
            cid
            for cid in ctx.series.campaigns_promoting(pid)
            if (c.engine.fact("ad_spend", Scope.campaign(cid), span).value or 0) > 0
        ]
        if promoters:
            line += f"; still advertised by {c.entity(f'campaign:{promoters[0]}')}"
        found.append((not promoters, not out, str(pid), Item(text=line + ".")))
    found.sort(key=lambda f: f[:3])
    return Section(
        key="inventory",
        title="Inventory",
        items=tuple(f[3] for f in found),
        empty="Every product's stock covers its supplier lead time.",
    )


def decisions_and_outcomes(ctx: Context, kind: BriefingKind) -> Section:
    c, since = ctx.cited, _since(ctx, kind)
    items: list[Item] = []
    for row in ctx.conn.execute(
        text(
            "SELECT decision_id FROM decisions WHERE store_id = :s AND created_at >= :since "
            "AND created_at < :now ORDER BY created_at"
        ),
        {"s": ctx.store_id, "since": since, "now": ctx.now},
    ).scalars():
        d = get(ctx.conn, ctx.store_id, row)
        option = d.option(d.approved_option_id or d.recommended_option_id)
        items.append(
            Item(
                text=f"Decision on {entity_ref(ctx, d.entity)}: {wording.option(option.kind)}, "
                f"{d.status.value}.",
                decision_id=str(d.decision_id),
            )
        )
    for row in ctx.conn.execute(
        text(
            "SELECT action_id, kind, campaign_id, provider, rollback_of FROM actions "
            "WHERE store_id = :s AND status = 'executed' AND executed_at >= :since "
            "AND executed_at < :now ORDER BY executed_at"
        ),
        {"s": ctx.store_id, "since": since, "now": ctx.now},
    ):
        what = ACTIONS.get(row.kind, row.kind)
        note = " (a rollback)" if row.rollback_of is not None else ""
        items.append(
            Item(text=f"Executed: {what}, {c.entity(f'campaign:{row.campaign_id}')}{note}.")
        )
    items.extend(_outcomes(ctx, since))
    return Section(
        key="decisions",
        title="Decisions and outcomes",
        items=tuple(items),
        empty="No decision, action or outcome since the last report.",
    )


def _outcomes(ctx: Context, since: datetime) -> list[Item]:
    c = ctx.cited
    items = []
    for row in ctx.conn.execute(
        text(
            "SELECT o.status, o.effect_fact_id, o.payload, a.campaign_id FROM outcomes o "
            "JOIN actions a ON a.store_id = o.store_id AND a.action_id = o.action_id "
            "WHERE o.store_id = :s AND o.created_at >= :since AND o.created_at < :now "
            "ORDER BY o.created_at"
        ),
        {"s": ctx.store_id, "since": since, "now": ctx.now},
    ):
        campaign = c.entity(f"campaign:{row.campaign_id}")
        if row.status != "measured" or row.effect_fact_id is None:
            reason = (row.payload or {}).get("reason", "no measurement")
            items.append(Item(text=f"Outcome on {campaign}: not measured yet ({reason})."))
            continue
        ids = [row.effect_fact_id]
        predicted_id = (row.payload or {}).get("predicted_fact_id")
        if predicted_id is not None:
            ids.append(int(predicted_id))
        facts = c.load(ids)
        line = f"Outcome on {campaign}: measured effect {c.ref(facts[row.effect_fact_id])}"
        if predicted_id is not None and int(predicted_id) in facts:
            line += f" against a prediction of {c.ref(facts[int(predicted_id)])}"
        items.append(Item(text=line + "."))
    return items


def opportunities(ctx: Context) -> Section:
    try:
        model = fit_twin(ctx.conn, ctx.store_id, as_of=ctx.day + timedelta(days=1))
    except ValueError:
        return Section(key="opportunities", title="Opportunities")
    found: list[tuple[Decimal, str, Item]] = []
    floor = ctx.settings.materiality.absolute
    for cid in sorted(model.campaigns, key=str):
        if model.campaigns[cid].curve is None:
            continue
        options = build_options(
            model, UNDERFUNDED_CAMPAIGN, f"campaign:{cid}", floor_monthly=Decimal(floor)
        )
        best = options.option(options.recommended)
        sim = best.simulation
        if best.kind is not OptionKind.INCREASE_BUDGET or sim is None or sim.undefined_reason:
            continue
        facts = simulation_facts(
            ctx.cited.engine, model, sim, input_facts(ctx.cited.engine, model, sim)
        )
        change = ctx.cited.keep(facts["twin.change.net_profit"])
        found.append(
            (
                change.p50 or Decimal(0),
                str(cid),
                Item(
                    text=f"{ctx.cited.entity(f'campaign:{cid}')}: {wording.option(best.kind)}, "
                    f"expected net-profit change {ctx.cited.ref(change)}."
                ),
            )
        )
    found.sort(key=lambda f: (-f[0], f[1]))
    return Section(
        key="opportunities",
        title="Opportunities",
        items=tuple(f[2] for f in found[:MAX_OPPORTUNITIES]),
        empty="No opportunity clears the bar this time.",
    )


def watchlist(ctx: Context) -> Section:
    items = [
        Item(
            text=f"{entity_ref(ctx, incident_entity(i))}: {wording.cause(top_family(i))}, not "
            "material yet.",
            level=AlertLevel.WATCHLIST.value,
            incident_id=i.incident_id,
        )
        for i in open_incidents(ctx.conn, ctx.store_id)
        if i.alert is AlertLevel.WATCHLIST
    ]
    return Section(key="watchlist", title="Watchlist", items=tuple(items))


GOAL_STATUS = {"ahead": "ahead of", "on_track": "on track with", "behind": "behind"}


def goals(ctx: Context) -> Section:
    """Goal progress (SPEC 17.5): each planned goal's latest weekly tracking, and the
    revisions proposed since (a step superseded by a decision on more recent data)."""
    items = []
    for goal in goal_service.active_goals(ctx.conn, ctx.store_id):
        rows = goal_service.progress(ctx.conn, ctx.store_id, goal.goal_id)
        weekly = [p for p in rows if p.kind == "weekly"]
        target, actual = goal.target_fact_id, weekly[-1].actual_fact_id if weekly else None
        if target is None or actual is None:
            continue
        last = weekly[-1]
        ids = [target, actual, last.milestone_fact_id, last.probability_fact_id]
        facts = ctx.cited.load(i for i in ids if i is not None)
        words = goal_service.METRIC_WORDS[goal.metric]
        text = (
            f"Your goal of {ctx.cited.ref(facts[target])} in {words} by "
            f"{(goal.deadline - timedelta(days=1)).isoformat()}: "
            f"{ctx.cited.ref(facts[actual])} so far"
        )
        if last.status is not None and last.milestone_fact_id is not None:
            text += (
                f", {GOAL_STATUS[last.status]} the plan's milestone "
                f"({ctx.cited.ref(facts[last.milestone_fact_id])})"
            )
        if last.probability_fact_id is not None:
            text += (
                f"; the chance of reaching it is now "
                f"{ctx.cited.ref(facts[last.probability_fact_id])} ({last.verdict})"
            )
        text += "."
        proposed = [p.reason for p in rows if p.revision_proposed and p.as_of >= last.as_of]
        if proposed:
            text += f" A revision of the plan is proposed: {'; '.join(r for r in proposed if r)}."
        items.append(Item(text=text))
    return Section(key="goals", title="Goals", items=tuple(items))


def weekly_report(ctx: Context) -> BriefingContent:
    week = periods.week_period(ctx.day)
    before = periods.previous(week)
    bridge, attribution = profit_bridge(ctx, week, before)
    return _finish(
        ctx,
        BriefingKind.WEEKLY,
        week,
        "Your week.",
        [
            summary(ctx, week, monthly=False, unit="week"),
            bridge,
            campaigns(ctx, week, before),
            *products(ctx, attribution, week),
            inventory(ctx, week),
            decisions_and_outcomes(ctx, BriefingKind.WEEKLY),
            goals(ctx),
            opportunities(ctx),
            watchlist(ctx),
        ],
    )


# --- 5.3 monthly additions -------------------------------------------------------------------


def unit_economics(ctx: Context, month: tuple[date, date]) -> Section:
    c = ctx.cited
    rows: list[tuple[Decimal, tuple[str, ...]]] = []
    for pid in sorted(ctx.series.products, key=str):
        scope = Scope.product(pid)
        units = c.get("units", scope, *month)
        if not units.value:
            continue
        cells = [c.entity(f"product:{pid}"), c.ref(units)]
        for metric in ("revenue", "cogs", "fees", "refunds", "contribution_margin"):
            amount = c.get(metric, scope, *month)
            per_unit = c.keep(_per_unit(amount, units))
            cells.append(c.ref(per_unit))
        margin = c.get("contribution_margin", scope, *month)
        rows.append((-(margin.value or Decimal(0)), tuple(cells)))
    rows.sort(key=lambda r: (r[0], r[1][0]))
    return Section(
        key="unit_economics",
        title="Unit economics",
        table=Table(
            columns=(
                "Product",
                "Units",
                "Net price",
                "Unit cost",
                "Fees",
                "Refunds",
                "Contribution",
            ),
            rows=tuple(r for _, r in rows),
        )
        if rows
        else None,
        empty=None if rows else "No product sold this month.",
    )


def _per_unit(amount: Fact, units: Fact) -> Fact:
    assert amount.id is not None
    assert units.id is not None
    return compute(f"F{amount.id} / F{units.id}", {amount.id: amount, units.id: units})


def fixed_costs(ctx: Context, month: tuple[date, date]) -> Section:
    c, store = ctx.cited, Scope.store()
    now_ = c.get("fixed_costs", store, *month)
    last = c.get("fixed_costs", store, *periods.previous(month, monthly=True))
    return Section(
        key="fixed_costs",
        title="Fixed costs",
        items=(
            Item(
                text=f"Fixed costs: {c.ref(now_)} this month against {c.ref(last)} last month "
                f"({c.direction(c.change(now_, last))})."
            ),
        ),
    )


def trust(ctx: Context) -> Section:
    items = []
    for entry in trust_ledger(ctx.conn, ctx.store_id):
        level = AUTONOMY[AutonomyLevel(entry.level)]
        if entry.proposal is not None:
            note = "a promotion to the next autonomy level is proposed for your approval"
        elif entry.measured:
            note = "not enough measured outcomes yet to propose a change"
        else:
            note = "no measured outcome yet"
        items.append(
            Item(
                text=f"{ACTIONS.get(entry.action_type, entry.action_type).capitalize()}: "
                f"autonomy {level}; {note}."
            )
        )
    return Section(key="trust", title="Trust ledger", items=tuple(items))


def decision_review(ctx: Context) -> Section:
    c = ctx.cited
    since = _since(ctx, BriefingKind.MONTHLY)
    items = []
    for did in ctx.conn.execute(
        text(
            "SELECT decision_id FROM decisions WHERE store_id = :s AND created_at < :now "
            "AND (created_at >= :since OR updated_at >= :since) ORDER BY created_at"
        ),
        {"s": ctx.store_id, "since": since, "now": ctx.now},
    ).scalars():
        d = get(ctx.conn, ctx.store_id, did)
        option = d.option(d.approved_option_id or d.recommended_option_id)
        line = f"{entity_ref(ctx, d.entity)}: {wording.option(option.kind)}, {d.status.value}"
        if d.status is DecisionStatus.MEASURED:
            row = ctx.conn.execute(
                text(
                    "SELECT effect_fact_id, payload FROM outcomes WHERE store_id = :s AND "
                    "decision_id = :d AND status = 'measured' ORDER BY created_at DESC LIMIT 1"
                ),
                {"s": ctx.store_id, "d": did},
            ).first()
            if row is not None and row.effect_fact_id is not None:
                ids = [row.effect_fact_id]
                predicted = (row.payload or {}).get("predicted_fact_id")
                if predicted is not None:
                    ids.append(int(predicted))
                facts = c.load(ids)
                line += f"; measured {c.ref(facts[row.effect_fact_id])}"
                if predicted is not None and int(predicted) in facts:
                    line += f" against a prediction of {c.ref(facts[int(predicted)])}"
        items.append(Item(text=line + ".", decision_id=str(did)))
    return Section(
        key="decision_review",
        title="Decision review",
        items=tuple(items),
        empty="No decision this month.",
    )


def monthly_review(ctx: Context) -> BriefingContent:
    month = periods.month_period(ctx.day)
    before = periods.previous(month, monthly=True)
    bridge, attribution = profit_bridge(ctx, month, before)
    return _finish(
        ctx,
        BriefingKind.MONTHLY,
        month,
        "Your month.",
        [
            summary(ctx, month, monthly=True, unit="month"),
            bridge,
            campaigns(ctx, month, before),
            *products(ctx, attribution, month),
            unit_economics(ctx, month),
            fixed_costs(ctx, month),
            inventory(ctx, month),
            trust(ctx),
            decision_review(ctx),
            opportunities(ctx),
            watchlist(ctx),
        ],
    )


def utc_now() -> datetime:
    return datetime.now(UTC)
