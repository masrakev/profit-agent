"""Fit the store twin on its recent history (ADR 0014).

Every input comes from the store's own data over a fit window ending at `as_of`:

- ad response per campaign, `purchases = a * (1 - exp(-b * spend))`, fitted on the platform's
  daily attributed purchases by least squares (profile over a grid of `b`, `a` in closed form),
  with a seeded bootstrap of days for parameter uncertainty;
- per product: units, net price, recent unit cost, fees, refund rate, stock on hand and arrivals,
  from the same daily series the facts are computed from;
- own-price elasticity, estimated only when the list price changed enough, otherwise the
  documented prior.

These are statistics for estimates, computed with floats; no exact fact comes from here.
"""

import math
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import numpy as np
from sqlalchemy import Connection, text

from app.detection.series import StoreSeries, load_series
from app.domain.hashing import canonical_json, sha256_hex
from app.twin.model import CampaignModel, CurveFit, Elasticity, FloatArray, ProductModel, TwinModel

TWIN_VERSION = 1
WINDOW_DAYS = 42
RECENT_DAYS = 14  # spend level and unit cost follow the last two weeks
MIN_CAMPAIGN_DAYS = 14
BOOTSTRAP = 500
B_GRID = np.geomspace(1e-3, 0.2, 80)  # half saturation between ~3.5 and ~700 per day of spend
# Platforms over-report the purchases their ads caused; real = attributed / factor, the factor
# drawn uniformly from this range (reconciliation studies; the bench world assumes the same).
OVER_ATTRIBUTION = (0.9, 1.35)
# Own-price elasticity when the list price never changed enough to estimate it: uniform on this
# range (consumer goods sold online). Wide on purpose; answers built on it carry low_evidence.
PRIOR_ELASTICITY = Elasticity(estimated=False, low=-3.0, high=-0.5, mean=-1.75, sd=0.72)
MIN_PRICE_CHANGE = 0.05  # two list prices at least 5% apart...
MIN_DAYS_PER_PRICE = 7  # ...each sold on at least 7 days


def _floats(values: Sequence[Decimal]) -> FloatArray:
    return np.array([float(v) for v in values], dtype=np.float64)


def profile_fit(spend: FloatArray, purchases: FloatArray) -> tuple[FloatArray, ...]:
    """Least squares of `a * (1 - exp(-b * s))` per row of `spend` / `purchases` (shape (R, n)):
    for each `b` of the grid the best `a` is closed form, then the best `b` is kept."""
    g = 1.0 - np.exp(-spend[:, :, None] * B_GRID[None, None, :])
    num = (purchases[:, :, None] * g).sum(axis=1)
    den = (g * g).sum(axis=1)
    a = np.where(den > 0, num / np.where(den > 0, den, 1.0), 0.0)
    sse = (purchases * purchases).sum(axis=1)[:, None] - a * num
    best = np.argmin(sse, axis=1)
    rows = np.arange(spend.shape[0])
    n = spend.shape[1]
    sigma = np.sqrt(np.maximum(sse[rows, best], 0.0) / max(n - 2, 1))
    return a[rows, best], B_GRID[best], sigma


def fit_curve(spend: FloatArray, purchases: FloatArray, rng: np.random.Generator) -> CurveFit:
    n = len(spend)
    idx = rng.integers(0, n, size=(BOOTSTRAP, n))
    a, b, sigma = profile_fit(spend[idx], purchases[idx])
    pa, pb, ps = profile_fit(spend[None, :], purchases[None, :])
    return CurveFit(
        a=a,
        b=b,
        sigma=sigma,
        point=(float(pa[0]), float(pb[0]), float(ps[0])),
        spend_low=float(spend.min()),
        spend_high=float(spend.max()),
    )


def response(curve_a: float, curve_b: float, spend: FloatArray) -> FloatArray:
    out: FloatArray = curve_a * (1.0 - np.exp(-curve_b * spend))
    return out


def _elasticity(days: list[tuple[float, float]]) -> Elasticity:
    """`days`: (list price, units) per day with sales. Estimated only from list-price changes."""
    by_price: dict[float, list[float]] = {}
    for price, units in days:
        by_price.setdefault(round(price, 2), []).append(units)
    levels = {p: u for p, u in by_price.items() if len(u) >= MIN_DAYS_PER_PRICE}
    if len(levels) < 2 or max(levels) / min(levels) - 1 < MIN_PRICE_CHANGE:
        return PRIOR_ELASTICITY
    x = np.array([math.log(p) for p, u in levels.items() for _ in u])
    y = np.array([math.log(v + 0.5) for u in levels.values() for v in u])
    xc = x - x.mean()
    slope = float((xc * (y - y.mean())).sum() / (xc * xc).sum())
    resid = y - (y.mean() + slope * xc)
    se = math.sqrt(float((resid**2).sum()) / max(len(x) - 2, 1) / float((xc * xc).sum()))
    low, high = -6.0, 0.0
    mean = min(max(slope, low), high)
    return Elasticity(estimated=True, low=low, high=high, mean=mean, sd=max(se, 0.05))


def _price_days(
    conn: Connection, store_id: UUID, first: date, end: date
) -> dict[UUID, list[tuple[float, float]]]:
    rows = conn.execute(
        text(
            "SELECT ol.product_id, (o.ordered_at AT TIME ZONE 'UTC')::date AS day, "
            "max(ol.unit_price) AS price, sum(ol.quantity) AS units "
            "FROM order_lines ol JOIN orders o ON o.store_id = ol.store_id AND o.id = ol.order_id "
            "WHERE ol.store_id = :sid AND o.ordered_at >= :first AND o.ordered_at < :end "
            "GROUP BY 1, 2"
        ),
        {"sid": store_id, "first": first, "end": end},
    )
    out: dict[UUID, list[tuple[float, float]]] = {}
    for row in rows:
        out.setdefault(row.product_id, []).append((float(row.price), float(row.units)))
    return out


def _catalog(conn: Connection, store_id: UUID) -> dict[UUID, tuple[float, float, float]]:
    rows = conn.execute(
        text("SELECT id, price, unit_cost, unit_fee FROM products WHERE store_id = :sid"),
        {"sid": store_id},
    )
    return {r.id: (float(r.price), float(r.unit_cost), float(r.unit_fee)) for r in rows}


def _currency(conn: Connection, store_id: UUID) -> str:
    return str(
        conn.execute(
            text("SELECT currency FROM stores WHERE store_id = :sid"), {"sid": store_id}
        ).scalar_one()
    )


def _ordered[T](items: dict[UUID, T]) -> list[T]:
    return [items[k] for k in sorted(items)]


def _seed(*parts: object) -> int:
    return int(sha256_hex(canonical_json([str(p) for p in parts]))[:16], 16)


def fit_twin(
    conn: Connection,
    store_id: UUID,
    *,
    as_of: date | None = None,
    window_days: int = WINDOW_DAYS,
    series: StoreSeries | None = None,
) -> TwinModel:
    """The twin of the store as of `as_of` (exclusive; default: the end of its data)."""
    series = series or load_series(conn, store_id)
    end = series.days if as_of is None else series.index(as_of)
    if end <= 0:
        raise ValueError("no data before as_of")
    start = max(0, end - window_days)
    days = end - start
    as_of_day = series.day(start) + timedelta(days=days)
    rng = np.random.default_rng(_seed("twin-fit", TWIN_VERSION, store_id, as_of_day))

    campaigns: dict[UUID, CampaignModel] = {}
    over = sum(OVER_ATTRIBUTION) / 2
    ad_units: dict[UUID, float] = {}
    for cid, c in sorted(series.campaigns.items()):
        spend = _floats(c.spend[start:end])
        purchases = _floats(c.attributed_purchases[start:end])
        active = spend > 0
        recent = spend[-RECENT_DAYS:]
        mean_spend = float(recent.mean()) if len(recent) else 0.0
        ratios = spend[active] / spend[active].mean() if active.any() else np.ones(1)
        curve: CurveFit | None = None
        reason = None
        if int(active.sum()) < MIN_CAMPAIGN_DAYS:
            reason = f"fewer than {MIN_CAMPAIGN_DAYS} days of spend in the fit window"
        else:
            curve = fit_curve(spend[active], purchases[active], rng)
            pa, pb, _ = curve.point
            # Ad-driven units over the window, spread evenly over the promoted products.
            real = float(response(pa, pb, spend[active]).sum()) / over
            for pid in c.promoted:
                ad_units[pid] = ad_units.get(pid, 0.0) + real / len(c.promoted)
        campaigns[cid] = CampaignModel(
            campaign_id=cid,
            promoted=tuple(c.promoted),
            mean_spend=mean_spend,
            spend_ratios=ratios,
            active_days=int(active.sum()),
            curve=curve,
            undefined_reason=reason,
        )

    catalog = _catalog(conn, store_id)
    prices = _price_days(conn, store_id, series.day(start), as_of_day)
    products: dict[UUID, ProductModel] = {}
    for pid, p in sorted(series.products.items()):
        units = float(sum(p.units[start:end]))
        revenue = float(sum(p.revenue[start:end]))
        lines = float(sum(p.lines[start:end]))
        recent_units = float(sum(p.units[end - RECENT_DAYS : end]))
        recent_cogs = float(sum(p.cogs[end - RECENT_DAYS : end]))
        price, cost, fee = catalog.get(pid, (0.0, 0.0, 0.0))
        unit_cost = (
            recent_cogs / recent_units
            if recent_units
            else (float(sum(p.cogs[start:end])) / units if units else cost)
        )
        on_hand_days = p.on_hand[start:end]
        known = [v for v in on_hand_days if v is not None]
        arrivals = 0.0
        for t in range(1, len(on_hand_days)):
            before, after = on_hand_days[t - 1], on_hand_days[t]
            if before is not None and after is not None:
                arrivals += max(0.0, after - before + float(p.units[start + t]))
        upl = units / lines if lines else 1.0
        products[pid] = ProductModel(
            product_id=pid,
            units_observed=units,
            ad_rate=ad_units.get(pid, 0.0) * upl / days,
            net_price=revenue / units if units else price,
            unit_cost=unit_cost,
            fee_per_unit=float(sum(p.fees[start:end])) / units if units else fee,
            refund_rate=float(sum(p.refunds[start:end])) / revenue if revenue else 0.0,
            units_per_line=upl,
            on_hand=float(known[-1]) if known else None,
            inflow_rate=arrivals / days,
            elasticity=_elasticity(prices.get(pid, [])),
        )
    fixed = _floats(series.fixed_costs[start:end])
    fingerprint = sha256_hex(
        canonical_json(
            {
                "version": TWIN_VERSION,
                "store": str(store_id),
                "as_of": as_of_day.isoformat(),
                "window": days,
                "units": f"{sum(m.units_observed for m in products.values()):.4f}",
                "spend": [str(sum(c.spend[start:end])) for c in _ordered(series.campaigns)],
            }
        )
    )[:16]
    return TwinModel(
        store_id=store_id,
        currency=_currency(conn, store_id),
        as_of=as_of_day,
        window_days=days,
        products=products,
        campaigns=campaigns,
        fixed_daily=float(fixed.mean()) if len(fixed) else 0.0,
        fingerprint=fingerprint,
    )
