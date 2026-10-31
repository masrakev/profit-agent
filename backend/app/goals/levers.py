"""The lever library: proven ways to move a goal's metric (Task 6 B1, SPEC 17.3, ADR 0024).

Each lever is code: a name, its mechanism, the facts that make it applicable (preconditions,
read over the last 28 days), and the steps it proposes, each with twin actions whose effect the
plan builder simulates over the goal's horizon (`app.goals.plan`). A step is a `decision`
(executable through the normal flow: policy engine, the owner's approval, execution, measured
outcome), a `manual` step the owner does (a reorder), or an `experiment`.

- `reallocate_budget`: from a campaign losing money to one making money, within the budget cap.
- `scale_profitable`: raise a profitable campaign in steps up to the cap, stopping where the
  twin's marginal profit turns negative.
- `prevent_stockout`: reorder a product that sells and that the store does not keep supplied
  (no stock arrived in six weeks, and too little left for its lead time), before it runs
  out, timed with its supplier lead time.
- `cut_unsellable_spend`: stop spend on products without stock.
- `shift_to_margin`: move ad support from campaigns promoting low-margin products to campaigns
  promoting high-margin ones.

Experiments (`price_test`, `refund_reduction`, `creative_refresh`) each have a cap, a duration,
a success criterion and a measurement method; they never count in a goal's probability until
measured.

Step summaries are code text: entities and facts by reference only, no literal number.
"""

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from itertools import pairwise
from uuid import UUID

import numpy as np
from sqlalchemy import Connection

from app.detection.series import StoreSeries, load_series
from app.facts.engine import FactEngine
from app.facts.model import Fact, Period, Scope
from app.settings.repository import StoreSettingsRepository
from app.twin import Action, ActionKind, Scenario, TwinModel, change_draws

DECISION, MANUAL, EXPERIMENT = "decision", "manual", "experiment"
WINDOW = 28  # days of facts the preconditions read
SCALE_STEPS = (Decimal("0.1"), Decimal("0.2"), Decimal("0.3"))
DEFAULT_LEAD_DAYS = 14
USUAL_DAYS = 42  # a stock arrival this recent: the store reorders the product itself
HIGH_MARGIN, LOW_MARGIN = 1.25, 0.75  # times the median margin rate of promoted products
REFUND_MULTIPLE = 2.0  # a product's refund rate against the store's
CPA_RISE = 1.15  # recent CPA against the 14 days before
PRICE_TEST = Decimal("0.05")
CENT = Decimal("0.01")
CAMPAIGN_KINDS = (ActionKind.CHANGE_BUDGET, ActionKind.PAUSE_CAMPAIGN)


@dataclass(frozen=True)
class Experiment:
    cap: str
    duration_days: int
    success: str
    measurement: str


@dataclass(frozen=True)
class Step:
    lever: str
    kind: str  # decision | manual | experiment
    day: int  # days after the plan starts
    actions: tuple[Action, ...]
    summary: str
    evidence: tuple[int, ...]  # the facts that make the lever applicable
    experiment: Experiment | None = None

    @property
    def campaigns(self) -> set[UUID]:
        return {a.entity for a in self.actions if a.kind in CAMPAIGN_KINDS and a.entity}

    @property
    def entities(self) -> tuple[str, ...]:
        out = []
        for a in self.actions:
            if a.entity is not None:
                kind = "campaign" if a.kind in CAMPAIGN_KINDS else "product"
                out.append(f"{kind}:{a.entity}")
        return tuple(dict.fromkeys(out))


@dataclass
class Context:
    """What the levers read: the twin, the budget cap and the facts of the last 28 days."""

    model: TwinModel
    horizon: int
    cap: Decimal
    engine: FactEngine
    period: Period
    previous: Period  # the 14 days before the last 14, for CPA trends
    recent: Period
    usual: frozenset[UUID] = frozenset()  # products the store keeps supplied itself
    _facts: dict[tuple[str, Scope, Period], Fact] = field(default_factory=dict)

    def fact(self, metric: str, scope: Scope, period: Period | None = None) -> Fact:
        """The fact, persisted (so a step can cite it)."""
        key = (metric, scope, period or self.period)
        if key not in self._facts:
            self._facts[key] = self.engine.persist(self.engine.fact(*key))
        return self._facts[key]

    def value(self, metric: str, scope: Scope, period: Period | None = None) -> float | None:
        v = self.fact(metric, scope, period).value
        return None if v is None else float(v)

    def ref(self, metric: str, scope: Scope, period: Period | None = None) -> str:
        return "{{F" + str(self.fact(metric, scope, period).id) + "}}"

    def id(self, metric: str, scope: Scope, period: Period | None = None) -> int:
        fid = self.fact(metric, scope, period).id
        assert fid is not None
        return fid


def usual_supply(series: StoreSeries, model: TwinModel) -> frozenset[UUID]:
    """Products the store keeps supplied by its own reorders: stock arrived in the last six
    weeks (or two lead times), or what is on hand covers the supplier's lead time (there is
    time to reorder as usual)."""
    end = series.index(model.as_of)
    out = set()
    for pid, p in model.products.items():
        history = series.products.get(pid)
        lead = p.lead_time_days or DEFAULT_LEAD_DAYS
        rate = p.units_observed / model.window_days
        look = max(USUAL_DAYS, 2 * lead)
        stock = [] if history is None else history.on_hand[max(0, end - look) : end]
        arrived = any(b is not None and a is not None and b > a for a, b in pairwise(stock))
        covered = p.on_hand is not None and rate > 0 and p.on_hand / rate >= lead
        if arrived or covered:
            out.add(pid)
    return frozenset(out)


def usual_reorders(ctx: Context) -> tuple[Action, ...]:
    """The usual reorders as twin actions: the baseline forecast includes them, so every plan
    simulation assumes them, with or without its steps (a reorder step counts only what the
    store would otherwise lose)."""
    return tuple(
        Action(kind=ActionKind.RESTOCK_PRODUCT, entity=pid)
        for pid in sorted(ctx.usual)
        if ctx.model.products[pid].on_hand is not None
    )


def context(
    conn: Connection,
    store_id: UUID,
    model: TwinModel,
    horizon: int,
    series: StoreSeries | None = None,
) -> Context:
    end = model.as_of
    caps = StoreSettingsRepository(conn).get_or_default(store_id).spending_caps
    supplied = usual_supply(series or load_series(conn, store_id), model)
    return Context(
        model=model,
        horizon=horizon,
        cap=caps.max_budget_change_ratio,
        engine=FactEngine(conn, store_id),
        period=Period.days(end - timedelta(days=WINDOW), end),
        previous=Period.days(end - timedelta(days=WINDOW), end - timedelta(days=14)),
        recent=Period.days(end - timedelta(days=14), end),
        usual=supplied,
    )


def _e(kind: str, entity: UUID) -> str:
    return "{{E:" + kind + ":" + str(entity) + "}}"


def _ratio(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(CENT, rounding=ROUND_HALF_EVEN)


def _spending(ctx: Context) -> dict[UUID, float]:
    return {cid: c.mean_spend for cid, c in ctx.model.campaigns.items() if c.mean_spend > 0}


def _raise_for(moved: float, spend: float, cap: Decimal) -> Decimal:
    return min(cap, _ratio(moved / spend)) if spend > 0 else cap


# --- levers ---------------------------------------------------------------------------------


def reallocate_budget(ctx: Context) -> list[Step]:
    spending = _spending(ctx)
    profit = {c: ctx.value("campaign_profit", Scope.campaign(c)) for c in spending}
    losers = sorted((c for c in spending if (profit[c] or 0.0) < 0), key=lambda c: profit[c] or 0)
    winners = sorted(
        (
            c
            for c in spending
            if (profit[c] or 0.0) > 0 and ctx.model.campaigns[c].curve is not None
        ),
        key=lambda c: -(profit[c] or 0.0),
    )
    steps = []
    for loser, winner in zip(losers, winners, strict=False):
        moved = float(ctx.cap) * spending[loser]
        up = _raise_for(moved, spending[winner], ctx.cap)
        steps.append(
            Step(
                lever="reallocate_budget",
                kind=DECISION,
                day=0,
                actions=(
                    Action(kind=ActionKind.CHANGE_BUDGET, entity=loser, change=-ctx.cap),
                    Action(kind=ActionKind.CHANGE_BUDGET, entity=winner, change=up),
                ),
                summary=(
                    f"Lower the daily budget of {_e('campaign', loser)}, which loses money "
                    f"(campaign profit {ctx.ref('campaign_profit', Scope.campaign(loser))}), "
                    f"and raise {_e('campaign', winner)}'s, which makes money "
                    f"({ctx.ref('campaign_profit', Scope.campaign(winner))})."
                ),
                evidence=(
                    ctx.id("campaign_profit", Scope.campaign(loser)),
                    ctx.id("campaign_profit", Scope.campaign(winner)),
                ),
            )
        )
    return steps


def _profit_change(ctx: Context, actions: tuple[Action, ...]) -> float:
    draws = change_draws(ctx.model, Scenario(actions=actions, horizon_days=_twin_days(ctx)))
    return float(np.median(draws["net_profit"])) if draws else 0.0


def _twin_days(ctx: Context) -> int:
    return max(7, min(ctx.horizon, 90))


def scale_profitable(ctx: Context) -> list[Step]:
    steps = []
    for cid in sorted(_spending(ctx)):
        if ctx.model.campaigns[cid].curve is None:
            continue
        if (ctx.value("campaign_profit", Scope.campaign(cid)) or 0.0) <= 0:
            continue
        best, gained = Decimal(0), 0.0
        for change in (s for s in SCALE_STEPS if s <= ctx.cap):
            gain = _profit_change(
                ctx, (Action(kind=ActionKind.CHANGE_BUDGET, entity=cid, change=change),)
            )
            if gain - gained <= 0:  # the marginal profit of the next step turns negative
                break
            best, gained = change, gain
        if best > 0:
            steps.append(
                Step(
                    lever="scale_profitable",
                    kind=DECISION,
                    day=0,
                    actions=(Action(kind=ActionKind.CHANGE_BUDGET, entity=cid, change=best),),
                    summary=(
                        f"Raise the daily budget of {_e('campaign', cid)}, which makes money "
                        f"(campaign profit {ctx.ref('campaign_profit', Scope.campaign(cid))}), "
                        "up to where the twin finds the next increase would cost more than it "
                        "brings."
                    ),
                    evidence=(ctx.id("campaign_profit", Scope.campaign(cid)),),
                )
            )
    return steps


def prevent_stockout(ctx: Context) -> list[Step]:
    steps = []
    for pid, p in sorted(ctx.model.products.items()):
        rate = p.units_observed / ctx.model.window_days
        if p.on_hand is None or rate <= 0 or pid in ctx.usual:
            continue
        cover = p.on_hand / rate
        margin = ctx.value("contribution_margin", Scope.product(pid)) or 0.0
        if cover >= ctx.horizon or margin <= 0:
            continue
        lead = p.lead_time_days or DEFAULT_LEAD_DAYS
        order = max(0, int(cover) - lead)
        steps.append(
            Step(
                lever="prevent_stockout",
                kind=MANUAL,
                day=order,
                actions=(
                    Action(
                        kind=ActionKind.RESTOCK_PRODUCT,
                        entity=pid,
                        start=min(order + lead, _twin_days(ctx) - 1),
                    ),
                ),
                summary=(
                    f"Reorder {_e('product', pid)} in time: it sells "
                    f"({ctx.ref('units', Scope.product(pid))} units in four weeks, contribution "
                    f"margin {ctx.ref('contribution_margin', Scope.product(pid))}), its stock "
                    f"covers {ctx.ref('inventory_cover_days', Scope.product(pid))} days and its "
                    f"supplier takes {ctx.ref('supplier_lead_time_days', Scope.product(pid))}."
                ),
                evidence=(
                    ctx.id("units", Scope.product(pid)),
                    ctx.id("contribution_margin", Scope.product(pid)),
                    ctx.id("inventory_cover_days", Scope.product(pid)),
                ),
            )
        )
    return steps


def cut_unsellable_spend(ctx: Context) -> list[Step]:
    empty = {
        pid
        for pid, p in ctx.model.products.items()
        if p.on_hand is not None and p.on_hand < 1 and p.inflow_rate <= 0
    }
    steps = []
    for cid in sorted(_spending(ctx)):
        promoted = set(ctx.model.campaigns[cid].promoted)
        stuck = sorted(promoted & empty)
        if not stuck:
            continue
        everything = promoted <= empty
        action = (
            Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=cid)
            if everything
            else Action(kind=ActionKind.CHANGE_BUDGET, entity=cid, change=-ctx.cap)
        )
        steps.append(
            Step(
                lever="cut_unsellable_spend",
                kind=DECISION,
                day=0,
                actions=(action,),
                summary=(
                    f"{'Pause' if everything else 'Lower the budget of'} {_e('campaign', cid)}: "
                    + ", ".join(
                        f"{_e('product', p)} ({ctx.ref('units_on_hand', Scope.product(p))} units "
                        "on hand)"
                        for p in stuck
                    )
                    + " cannot be sold."
                ),
                evidence=tuple(ctx.id("units_on_hand", Scope.product(p)) for p in stuck),
            )
        )
    return steps


def shift_to_margin(ctx: Context) -> list[Step]:
    spending = _spending(ctx)
    rates: dict[UUID, float] = {}
    for cid in spending:
        if ctx.model.campaigns[cid].curve is None:
            continue
        cm = rev = 0.0
        for pid in ctx.model.campaigns[cid].promoted:
            cm += ctx.value("contribution_margin", Scope.product(pid)) or 0.0
            rev += ctx.value("revenue", Scope.product(pid)) or 0.0
        if rev > 0:
            rates[cid] = cm / rev
    if len(rates) < 2:
        return []
    median = statistics.median(rates.values())
    high = sorted((c for c in rates if rates[c] >= HIGH_MARGIN * median), key=lambda c: -rates[c])
    low = sorted((c for c in rates if rates[c] <= LOW_MARGIN * median), key=lambda c: rates[c])
    steps = []
    for weak, strong in zip(low, high, strict=False):
        up = _raise_for(float(ctx.cap) * spending[weak], spending[strong], ctx.cap)
        steps.append(
            Step(
                lever="shift_to_margin",
                kind=DECISION,
                day=0,
                actions=(
                    Action(kind=ActionKind.CHANGE_BUDGET, entity=weak, change=-ctx.cap),
                    Action(kind=ActionKind.CHANGE_BUDGET, entity=strong, change=up),
                ),
                summary=(
                    f"Move ad support from {_e('campaign', weak)}, whose products earn a low "
                    f"margin, to {_e('campaign', strong)}, whose products earn a high one "
                    "(the products' contribution margin over their revenue)."
                ),
                evidence=tuple(
                    ctx.id(m, Scope.product(pid))
                    for c in (weak, strong)
                    for pid in ctx.model.campaigns[c].promoted
                    for m in ("contribution_margin", "revenue")
                ),
            )
        )
    return steps


# --- experiments ----------------------------------------------------------------------------


def price_test(ctx: Context) -> list[Step]:
    untested = [
        pid for pid, p in ctx.model.products.items() if not p.elasticity.estimated and p.on_hand
    ]
    if not untested:
        return []
    pid = max(untested, key=lambda p: (ctx.value("revenue", Scope.product(p)) or 0.0, str(p)))
    return [
        Step(
            lever="price_test",
            kind=EXPERIMENT,
            day=0,
            actions=(Action(kind=ActionKind.CHANGE_PRICE, entity=pid, change=PRICE_TEST, days=14),),
            summary=(
                f"Test a small price increase on {_e('product', pid)}, the best seller whose "
                f"price has never changed (revenue {ctx.ref('revenue', Scope.product(pid))})."
            ),
            evidence=(ctx.id("revenue", Scope.product(pid)),),
            experiment=Experiment(
                cap="one product, at most 5% above its price",
                duration_days=14,
                success="its contribution margin over the test is above what synthetic "
                "control expects without the change",
                measurement="synthetic control on the product's contribution margin, as for "
                "every executed decision",
            ),
        )
    ]


def refund_reduction(ctx: Context) -> list[Step]:
    store = ctx.value("refund_rate", Scope.store()) or 0.0
    worst = [
        (ctx.value("refund_rate", Scope.product(pid)) or 0.0, pid)
        for pid in ctx.model.products
        if (ctx.value("revenue", Scope.product(pid)) or 0.0) > 0
    ]
    flagged = [(r, p) for r, p in worst if store > 0 and r >= REFUND_MULTIPLE * store]
    if not flagged:
        return []
    _, pid = max(flagged, key=lambda x: (x[0], str(x[1])))
    return [
        Step(
            lever="refund_reduction",
            kind=EXPERIMENT,
            day=0,
            actions=(),
            summary=(
                f"Find why {_e('product', pid)} is refunded so often (refund rate "
                f"{ctx.ref('refund_rate', Scope.product(pid))}, the store's "
                f"{ctx.ref('refund_rate', Scope.store())}) and fix its page or sizing."
            ),
            evidence=(
                ctx.id("refund_rate", Scope.product(pid)),
                ctx.id("refund_rate", Scope.store()),
            ),
            experiment=Experiment(
                cap="one product",
                duration_days=28,
                success="its refund rate falls by a third against the store's",
                measurement="the product's refund rate before and after, against the other "
                "products over the same weeks",
            ),
        )
    ]


def creative_refresh(ctx: Context) -> list[Step]:
    spending = _spending(ctx)
    rising = []
    for cid in spending:
        before = ctx.value("cpa", Scope.campaign(cid), ctx.previous)
        recent = ctx.value("cpa", Scope.campaign(cid), ctx.recent)
        if before and recent and recent >= CPA_RISE * before:
            rising.append((recent / before, cid))
    if not rising:
        return []
    _, cid = max(rising, key=lambda x: (x[0], str(x[1])))
    return [
        Step(
            lever="creative_refresh",
            kind=EXPERIMENT,
            day=0,
            actions=(),
            summary=(
                f"Refresh the creative of {_e('campaign', cid)}: its cost per purchase rose "
                f"(from {ctx.ref('cpa', Scope.campaign(cid), ctx.previous)} to "
                f"{ctx.ref('cpa', Scope.campaign(cid), ctx.recent)})."
            ),
            evidence=(
                ctx.id("cpa", Scope.campaign(cid), ctx.previous),
                ctx.id("cpa", Scope.campaign(cid), ctx.recent),
            ),
            experiment=Experiment(
                cap="one campaign, its budget unchanged",
                duration_days=14,
                success="its cost per purchase is a tenth lower than synthetic control expects",
                measurement="synthetic control on the campaign's cost per purchase",
            ),
        )
    ]


@dataclass(frozen=True)
class Lever:
    name: str
    mechanism: str
    preconditions: str
    propose: Callable[[Context], list[Step]]


LEVERS: tuple[Lever, ...] = (
    Lever(
        "reallocate_budget",
        "budget moves from a campaign whose ads cost more than they earn to one whose ads earn "
        "more than they cost",
        "a campaign with negative campaign profit and one with positive campaign profit and a "
        "fitted response curve, over the last 28 days",
        reallocate_budget,
    ),
    Lever(
        "scale_profitable",
        "more budget on a profitable campaign buys more profitable sales, until the response "
        "curve flattens",
        "positive campaign profit, a fitted response curve, and a positive marginal profit for "
        "the next increase in the twin",
        scale_profitable,
    ),
    Lever(
        "prevent_stockout",
        "sales a product would lose when it runs out are kept by reordering in time",
        "the product sells, has a positive contribution margin, no stock arrived in six weeks "
        "(or two lead times), and its stock covers less than its lead time and the goal's "
        "horizon",
        prevent_stockout,
    ),
    Lever(
        "cut_unsellable_spend",
        "ads for products that cannot be sold spend money for nothing",
        "a campaign promotes a product with no stock on hand and no stock arriving",
        cut_unsellable_spend,
    ),
    Lever(
        "shift_to_margin",
        "the same ad spend earns more on products with a higher margin",
        "two campaigns with fitted curves whose promoted products' margin rates (contribution "
        "margin over revenue) are above 1.25 and below 0.75 times the median",
        shift_to_margin,
    ),
)
EXPERIMENTS: tuple[Lever, ...] = (
    Lever(
        "price_test",
        "a price the store has never changed may be below what its buyers would pay",
        "a product with stock whose price never changed enough to estimate its elasticity",
        price_test,
    ),
    Lever(
        "refund_reduction",
        "refunds come back off revenue; a product refunded far more than the rest often has "
        "a fixable cause (sizing, description)",
        "a product refunded at least twice as often as the store",
        refund_reduction,
    ),
    Lever(
        "creative_refresh",
        "a campaign whose cost per purchase keeps rising often has a tired creative",
        "a campaign whose cost per purchase over the last 14 days is 15% above the 14 before",
        creative_refresh,
    ),
)


def candidates(ctx: Context) -> list[Step]:
    """Every step the levers propose for the store now, experiments included."""
    return [step for lever in (*LEVERS, *EXPERIMENTS) for step in lever.propose(ctx)]
