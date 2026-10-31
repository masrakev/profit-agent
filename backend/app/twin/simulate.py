"""Monte Carlo simulation of a scenario against "do nothing" over a horizon (ADR 0014).

Each draw takes one bootstrap fit per campaign, one platform over-attribution factor, one
organic demand rate and one price elasticity per product, and daily noise. The scenario and
"do nothing" are simulated with the same draws, so their difference reflects the action, not
the noise. Assumptions (also in ADR 0014):

- a campaign keeps spending at its recent daily level, with its observed day-to-day variation;
  a budget change scales that level; ad-driven purchases follow the fitted curve, are divided
  by the over-attribution factor and spread evenly over the promoted products;
- organic demand per product is its observed rate minus its ad-driven part, Poisson around it;
- a price change scales the net price and, through the elasticity, organic and ad-driven units;
  unit cost, fees per unit and the refund rate stay as observed;
- units sold cannot exceed stock on hand plus arrivals at the window's arrival rate (no reorder
  is assumed beyond that), unless a restock (in plans, an owner's reorder) restores the
  supply from its day on;
- an action takes effect on its `start` day and lasts `days` (the rest of the horizon if none);
- fixed costs continue at their daily rate.
"""

from dataclasses import dataclass
from uuid import UUID

import numpy as np
import numpy.typing as npt

from app.domain.hashing import canonical_json, sha256_hex
from app.twin.calibration import Calibration, load_calibration, widen
from app.twin.fit import BOOTSTRAP, OVER_ATTRIBUTION
from app.twin.model import (
    METRICS,
    Action,
    ActionKind,
    FloatArray,
    Range,
    Scenario,
    Simulation,
    TwinModel,
)

DRAWS = 1000
IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class _Draws:
    n: int
    curve: dict[UUID, IntArray]  # bootstrap fit per draw
    spend: dict[UUID, IntArray]  # (n, H) indices into the campaign's spend ratios
    z_campaign: dict[UUID, FloatArray]  # (n, H)
    over: FloatArray  # (n,)
    organic: dict[UUID, FloatArray]  # (n,) organic units per day
    z_product: dict[UUID, FloatArray]  # (n,)
    elasticity: dict[UUID, FloatArray]  # (n,)
    donor: IntArray  # (n,) campaign index for a new campaign's response
    donor_fit: IntArray  # (n,)
    z_new: FloatArray  # (n, H)


def _draws(model: TwinModel, horizon: int, n: int) -> _Draws:
    seed = int(sha256_hex(canonical_json([model.fingerprint, horizon, n]))[:16], 16)
    rng = np.random.default_rng(seed)
    curve, spend, z_campaign = {}, {}, {}
    for cid, c in sorted(model.campaigns.items()):
        curve[cid] = rng.integers(0, BOOTSTRAP, size=n)
        spend[cid] = rng.integers(0, len(c.spend_ratios), size=(n, horizon))
        z_campaign[cid] = rng.standard_normal((n, horizon))
    over = rng.uniform(*OVER_ATTRIBUTION, size=n)
    organic, z_product, elasticity = {}, {}, {}
    for pid, p in sorted(model.products.items()):
        rate = rng.gamma(p.units_observed + 0.5, 1.0 / model.window_days, size=n)
        organic[pid] = np.maximum(rate - p.ad_rate, 0.0)
        z_product[pid] = rng.standard_normal(n)
        e = p.elasticity
        if e.estimated:
            elasticity[pid] = np.clip(rng.normal(e.mean, e.sd, size=n), e.low, e.high)
        else:
            elasticity[pid] = rng.uniform(e.low, e.high, size=n)
    with_curve = max(1, sum(1 for c in model.campaigns.values() if c.curve is not None))
    return _Draws(
        n=n,
        curve=curve,
        spend=spend,
        z_campaign=z_campaign,
        over=over,
        organic=organic,
        z_product=z_product,
        elasticity=elasticity,
        donor=rng.integers(0, with_curve, size=n),
        donor_fit=rng.integers(0, BOOTSTRAP, size=n),
        z_new=rng.standard_normal((n, horizon)),
    )


def _active(start: int, days: int | None, horizon: int) -> npt.NDArray[np.bool_]:
    t = np.arange(horizon)
    return (t >= start) & (t < start + (days or horizon))


def _purchases(
    a: FloatArray, b: FloatArray, sigma: FloatArray, spend: FloatArray, z: FloatArray
) -> FloatArray:
    expected = a[:, None] * (1.0 - np.exp(-b[:, None] * spend))
    out: FloatArray = np.where(spend > 0, np.maximum(expected + sigma[:, None] * z, 0.0), 0.0)
    return out


def _run(
    model: TwinModel, scenario: Scenario, d: _Draws
) -> tuple[dict[str, FloatArray], list[str]]:
    """Totals per draw for each metric, and the reasons the evidence is weak."""
    h = scenario.horizon_days
    weak: list[str] = []
    budget = {cid: np.ones(h) for cid in model.campaigns}
    price = {pid: np.ones(h) for pid in model.products}
    launches: list[tuple[UUID, float, npt.NDArray[np.bool_]]] = []
    restocked: dict[UUID, int] = {}
    for action in scenario.actions:
        on = _active(action.start, action.days, h)
        factor = 1.0 + float(action.change)
        if action.kind is ActionKind.CHANGE_BUDGET and action.entity in budget:
            budget[action.entity][on] = factor
        elif action.kind is ActionKind.PAUSE_CAMPAIGN and action.entity in budget:
            budget[action.entity][on] = 0.0
        elif action.kind is ActionKind.CHANGE_ALL_AD_SPEND:
            for cid in budget:
                budget[cid][on] *= factor
        elif action.kind is ActionKind.CHANGE_PRICE and action.entity in price:
            price[action.entity][on] = factor
            if not model.products[action.entity].elasticity.estimated:
                weak.append("price response from the prior: the list price never changed enough")
        elif action.kind is ActionKind.RESTOCK_PRODUCT and action.entity in price:
            restocked[action.entity] = min(action.start, h)
        elif action.kind is ActionKind.LAUNCH_CAMPAIGN and action.entity in price:
            spends = [c.mean_spend for c in model.campaigns.values() if c.curve is not None]
            daily = float(action.daily_budget) if action.daily_budget else float(np.median(spends))
            launches.append((action.entity, daily, on))
            weak.append("a new campaign's response is borrowed from the store's other campaigns")

    n = d.n
    ad_units = {pid: np.zeros((n, h)) for pid in model.products}
    spend_total = np.zeros(n)
    for cid, c in sorted(model.campaigns.items()):
        spend = c.mean_spend * c.spend_ratios[d.spend[cid]] * budget[cid][None, :]
        spend_total += spend.sum(axis=1)
        if c.curve is None:
            continue
        if not np.all(budget[cid] == 1.0) and c.curve.spend_high > 0:
            planned = c.mean_spend * budget[cid]
            if planned.max() > c.curve.spend_high or (
                planned.min() > 0 and planned.min() < c.curve.spend_low
            ):
                weak.append("spend outside the observed range: the response curve is extrapolated")
        r = d.curve[cid]
        real = _purchases(c.curve.a[r], c.curve.b[r], c.curve.sigma[r], spend, d.z_campaign[cid])
        real = real / d.over[:, None]
        for pid in c.promoted:
            if pid in ad_units:
                ad_units[pid] += real / len(c.promoted) * model.products[pid].units_per_line
    donors = [c.curve for _, c in sorted(model.campaigns.items()) if c.curve is not None]
    for pid, daily, on in launches:
        if not donors:
            return {}, ["the store has no campaign to borrow a response curve from"]
        pairs = list(zip(d.donor % len(donors), d.donor_fit, strict=True))
        a = np.array([donors[k].a[f] for k, f in pairs])
        b = np.array([donors[k].b[f] for k, f in pairs])
        s = np.array([donors[k].sigma[f] for k, f in pairs])
        spend = np.where(on[None, :], daily, 0.0) * np.ones((n, 1))
        spend_total += spend.sum(axis=1)
        ad_units[pid] += _purchases(a, b, s, spend, d.z_new) / d.over[:, None]

    cm = np.zeros(n)
    units = np.zeros(n)
    sales = np.zeros(n)
    for pid, p in sorted(model.products.items()):
        effect = price[pid][None, :] ** d.elasticity[pid][:, None]  # (n, h)
        organic = d.organic[pid][:, None] * effect
        ad = ad_units[pid] * effect
        expected = organic.sum(axis=1)
        sold = np.maximum(expected + np.sqrt(expected) * d.z_product[pid], 0.0) + ad.sum(axis=1)
        per_day = organic + ad
        if p.on_hand is not None and pid in restocked:
            arrival = restocked[pid]
            supply = p.on_hand + p.inflow_rate * arrival + per_day[:, arrival:].sum(axis=1)
            sold = np.minimum(sold, supply)
        elif p.on_hand is not None:
            sold = np.minimum(sold, p.on_hand + p.inflow_rate * h)
        planned = per_day.sum(axis=1)
        scale = np.where(planned > 0, sold / np.where(planned > 0, planned, 1.0), 0.0)
        revenue = scale * (per_day * (p.net_price * price[pid])[None, :]).sum(axis=1)
        cm += revenue * (1.0 - p.refund_rate) - sold * (p.unit_cost + p.fee_per_unit)
        units += sold
        sales += revenue
    net = cm - spend_total - model.fixed_daily * h
    totals = {
        "contribution_margin": cm,
        "net_profit": net,
        "units": units,
        "ad_spend": spend_total,
        "revenue": sales,  # not one of the simulation's facts: plans of revenue goals use it
    }
    return totals, sorted(set(weak))


def _range(x: FloatArray) -> Range:
    p10, p50, p90 = np.percentile(x, [10, 50, 90])
    return Range(float(p10), float(p50), float(p90))


def simulate(
    model: TwinModel,
    scenario: Scenario,
    *,
    draws: int = DRAWS,
    calibration: Calibration | None = None,
) -> Simulation:
    """The scenario and "do nothing" over the scenario's horizon, with the same draws."""
    cal = calibration if calibration is not None else load_calibration()
    reason = _undefined_reason(model, scenario)
    if reason is not None:
        return _undefined(scenario, reason, cal)
    d = _draws(model, scenario.horizon_days, draws)
    base, _ = _run(model, Scenario(horizon_days=scenario.horizon_days), d)
    totals, weak = _run(model, scenario, d)
    if not totals:
        return _undefined(scenario, weak[0], cal)
    acting = not scenario.is_do_nothing
    return Simulation(
        scenario=scenario,
        totals={m: widen(_range(totals[m]), cal.factor(m, action=acting)) for m in METRICS},
        do_nothing={m: widen(_range(base[m]), cal.factor(m, action=False)) for m in METRICS},
        change={m: widen(_range(totals[m] - base[m]), cal.change_factor(m)) for m in METRICS},
        low_evidence=tuple(weak),
        calibration_version=cal.version,
    )


def change_draws(
    model: TwinModel,
    scenario: Scenario,
    *,
    draws: int = DRAWS,
    calibration: Calibration | None = None,
    background: tuple[Action, ...] = (),
) -> dict[str, FloatArray]:
    """The scenario minus doing nothing, draw by draw (the same draws), for plans: each
    metric's spread around its median widened by the twin's change calibration (revenue,
    never calibrated, as it is). `background` actions happen in both (the store's usual
    reorders). Empty when the scenario cannot be simulated."""
    cal = calibration if calibration is not None else load_calibration()
    if _undefined_reason(model, scenario) is not None:
        return {}
    h = scenario.horizon_days
    d = _draws(model, h, draws)
    base, _ = _run(model, Scenario(actions=background, horizon_days=h), d)
    totals, _ = _run(model, Scenario(actions=(*background, *scenario.actions), horizon_days=h), d)
    if not totals:
        return {}
    out: dict[str, FloatArray] = {}
    for metric, values in totals.items():
        change = values - base[metric]
        median = float(np.median(change))
        q = cal.change_factor(metric) if metric in METRICS else 0.0
        out[metric] = median + (change - median) * (1.0 + q)
    return out


def _undefined_reason(model: TwinModel, scenario: Scenario) -> str | None:
    for action in scenario.actions:
        known = model.campaigns if action.kind in _CAMPAIGN_ACTIONS else model.products
        if action.entity is not None and action.entity not in known:
            return f"unknown {action.kind.value} entity"
        if action.kind in _CAMPAIGN_ACTIONS and action.entity is not None:
            reason = model.campaigns[action.entity].undefined_reason
            if reason is not None:
                return reason
    return None


_CAMPAIGN_ACTIONS = frozenset({ActionKind.CHANGE_BUDGET, ActionKind.PAUSE_CAMPAIGN})


def _undefined(scenario: Scenario, reason: str, cal: Calibration) -> Simulation:
    return Simulation(
        scenario=scenario,
        totals={},
        do_nothing={},
        change={},
        undefined_reason=reason,
        calibration_version=cal.version,
    )
