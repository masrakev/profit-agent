"""The store simulator: a synthetic store that lives day by day (Task 4 B3-B4, ADR 0017).

- `register(engine, manifest, today)`: loads the scenario's store with its data before day
  `today` (the simulator's today) and records it in `simulator_stores`.
- The executor's SimulatorAdapter changes the store's campaigns and records each change as an
  event at today.
- `advance(engine, store_id, days, restock=...)`: generates the scenario again with those events
  as interventions (and a supplier restock, if any, from today), and appends the next `days`
  days of data. Days before an event are identical to the store without it (the generator's
  guarantee), so the appended days are what the store does with the owner's actions applied.
"""

import dataclasses
import json
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from app.db import refresh_planner_statistics, tenant_transaction
from app.domain.repositories import (
    AdMetricsRepository,
    InventoryRepository,
    OrderRepository,
    RefundRepository,
)
from bench.generator import GeneratedStore, Intervention, Restock
from bench.generator.load import load
from bench.scenarios.manifest import ScenarioManifest, load_suite


def _day(data: GeneratedStore, when: date) -> int:
    return (when - data.config.start_date).days


def window(data: GeneratedStore, first: int, end: int) -> GeneratedStore:
    """The records of days [first, end): orders, their lines, refunds issued, stock, ad metrics."""
    orders = tuple(o for o in data.orders if first <= _day(data, o.ordered_at.date()) < end)
    ids = {o.id for o in orders}
    return dataclasses.replace(
        data,
        orders=orders,
        lines=tuple(line for line in data.lines if line.order_id in ids),
        refunds=tuple(r for r in data.refunds if first <= _day(data, r.refunded_at.date()) < end),
        inventory=tuple(s for s in data.inventory if first <= _day(data, s.snapshot_date) < end),
        ad_metrics=tuple(m for m in data.ad_metrics if first <= _day(data, m.metric_date) < end),
    )


def register(engine: Engine, manifest: ScenarioManifest, today: int) -> UUID:
    data = manifest.generate()
    load(engine, window(data, 0, today), manifest.config)
    store_id = data.store.store_id
    with tenant_transaction(engine, store_id) as conn:
        conn.execute(
            text(
                "INSERT INTO simulator_stores (store_id, suite, scenario_id, current_day, events) "
                "VALUES (:s, :suite, :scenario, :day, '[]'::jsonb)"
            ),
            {
                "s": store_id,
                "suite": manifest.suite,
                "scenario": manifest.scenario_id,
                "day": today,
            },
        )
    return store_id


def interventions(
    plain: GeneratedStore, events: Sequence[dict[str, Any]]
) -> list[Intervention | Restock]:
    """The executed actions as generator interventions: a budget multiplier relative to the
    generated budget (0 while paused), and restocks."""
    index = {c.id: i for i, c in enumerate(plain.campaigns)}
    base = {c.id: c.daily_budget for c in plain.campaigns}
    state: dict[UUID, tuple[str, Decimal]] = {
        c.id: ("ACTIVE", c.daily_budget) for c in plain.campaigns
    }
    out: list[Intervention | Restock] = []
    for e in events:
        if "restock_product" in e:
            out.append(Restock(day=int(e["day"]), product=UUID(e["restock_product"])))
            continue
        cid = UUID(e["campaign_id"])
        status, budget = state[cid]
        status = e.get("status") or status
        budget = Decimal(e["daily_budget"]) if e.get("daily_budget") else budget
        state[cid] = (status, budget)
        multiplier = 0.0 if status == "PAUSED" else float(budget / base[cid])
        out.append(
            Intervention(day=int(e["day"]), campaign=index[cid], budget_multiplier=multiplier)
        )
    return out


def _manifest(suite: str, scenario_id: str) -> ScenarioManifest:
    return next(m for m in load_suite(suite) if m.scenario_id == scenario_id)  # type: ignore[arg-type]


def advance(engine: Engine, store_id: UUID, days: int, *, restock: Sequence[UUID] = ()) -> int:
    """Append the next `days` days; returns the new today."""
    with tenant_transaction(engine, store_id) as conn:
        row = conn.execute(
            text("SELECT * FROM simulator_stores WHERE store_id = :s FOR UPDATE"), {"s": store_id}
        ).one()
        today = int(row.current_day)
        events = list(row.events) + [{"day": today, "restock_product": str(p)} for p in restock]
        manifest = _manifest(row.suite, row.scenario_id)
        plain = manifest.generate()
        data = manifest.generate(interventions=interventions(plain, events))
        end = min(today + days, manifest.config.days)
        new = window(data, today, end)
        OrderRepository(conn).add_many(new.orders, new.lines)
        RefundRepository(conn).add_many(new.refunds)
        InventoryRepository(conn).add_many(new.inventory)
        AdMetricsRepository(conn).add_many(new.ad_metrics)
        conn.execute(
            text(
                "UPDATE simulator_stores SET current_day = :d, events = CAST(:e AS jsonb), "
                "updated_at = now() WHERE store_id = :s"
            ),
            {"d": end, "e": json.dumps(events), "s": store_id},
        )
    refresh_planner_statistics(engine)
    return end


def today_date(manifest: ScenarioManifest, today: int) -> date:
    return manifest.config.start_date + timedelta(days=today)
