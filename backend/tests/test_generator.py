import dataclasses
import json
from collections import Counter
from datetime import timedelta
from uuid import UUID

import numpy as np
import pytest
from sqlalchemy import Engine, text

from app.db import tenant_transaction
from app.domain.audit import verify_chain
from app.facts import recompute
from bench.generator import (
    Fault,
    GeneratedStore,
    GeneratorConfig,
    Intervention,
    Restock,
    apply_faults,
    generate,
)
from bench.generator.__main__ import main as generator_main
from bench.scenarios.manifest import load_suite

SMALL = GeneratorConfig(seed=7, days=40)


@pytest.fixture(scope="module")
def small() -> GeneratedStore:
    return generate(SMALL)


def test_generation_is_deterministic(small: GeneratedStore) -> None:
    again = generate(SMALL)
    assert again == small
    other = generate(SMALL.model_copy(update={"seed": 8}))
    assert other.store.store_id != small.store.store_id
    assert other.orders != small.orders


def test_generated_store_respects_config() -> None:
    data = generate(GeneratorConfig(seed=42))
    assert 15 <= len(data.products) <= 40
    assert 3 <= len(data.campaigns) <= 8
    days = {o.ordered_at.date() for o in data.orders}
    assert len(days) == 120
    assert min(days) == GeneratorConfig(seed=42).start_date
    promoted = Counter(link.campaign_id for link in data.campaign_products)
    assert set(promoted) == {c.id for c in data.campaigns}
    # Supplier cost changes: earlier sales keep the cost snapshot taken at sale time.
    current = {p.id: p.unit_cost for p in data.products}
    assert any(line.unit_cost_at_sale != current[line.product_id] for line in data.lines)
    assert data.lost_sales_units > 0  # inventory constrains sales


def test_generated_records_are_consistent(small: GeneratedStore) -> None:
    lines_by_id = {line.id: line for line in small.lines}
    orders_by_id = {o.id: o for o in small.orders}
    end = small.orders[0].ordered_at.replace(hour=0, minute=0, second=0) + timedelta(
        days=SMALL.days
    )
    for refund in small.refunds:
        line = lines_by_id[refund.order_line_id]
        assert refund.order_id == line.order_id
        assert refund.amount == line.net_amount
        assert orders_by_id[line.order_id].ordered_at < refund.refunded_at < end
    assert all(s.units_on_hand >= 0 for s in small.inventory)
    starts = {t.campaign_id: t.start_day for t in small.campaign_truth}
    first_day = SMALL.start_date
    for metric in small.ad_metrics:
        assert (metric.metric_date - first_day).days >= starts[metric.campaign_id]
    assert small.counts()["orders"] == len(small.orders)


@dataclasses.dataclass(frozen=True)
class DropRefunds:
    """Example fault: drops a random half of the refunds."""

    name: str = "drop_refunds"

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        keep = tuple(r for r in data.refunds if rng.random() < 0.5)
        return dataclasses.replace(data, refunds=keep)


def test_faults_are_pure_and_seeded(small: GeneratedStore) -> None:
    fault = DropRefunds()
    assert isinstance(fault, Fault)
    first = apply_faults(small, [fault], seed=1)
    assert first == apply_faults(small, [fault], seed=1)
    assert len(first.refunds) < len(small.refunds)
    assert small == generate(SMALL)  # the input was not mutated
    assert generate(SMALL, faults=[fault]) == apply_faults(small, [fault], SMALL.seed)


@pytest.mark.db
def test_cli_loads_store_and_facts_recompute(
    app_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert generator_main(["--seed", "3", "--days", "40"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "created"
    assert generator_main(["--seed", "3", "--days", "40"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "exists"

    store_id = created["store_id"]
    assert recompute.main(["--store", store_id]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["inserted"] > 0
    with app_engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.store_id', :s, false)"), {"s": store_id})
        lineage = conn.execute(text("SELECT count(*) FROM fact_lineage")).scalar_one()
        orders = conn.execute(text("SELECT count(*) FROM orders")).scalar_one()
    assert lineage > 0
    assert orders == created["counts"]["orders"]
    with tenant_transaction(app_engine, UUID(store_id)) as conn:
        assert verify_chain(conn, UUID(store_id)).entries_checked == 2


def test_interventions_change_only_what_follows_them(small: GeneratedStore) -> None:
    day = 30
    first = SMALL.start_date + timedelta(days=day)
    cut = generate(SMALL, interventions=[Intervention(day=day, campaign=0, budget_multiplier=0.5)])
    paused = generate(SMALL, interventions=[Intervention(day=day, campaign=0, budget_multiplier=0)])
    assert cut.store.store_id == small.store.store_id == paused.store.store_id
    assert cut.interventions == (Intervention(day=day, campaign=0, budget_multiplier=0.5),)

    def figures(data: GeneratedStore, before: bool) -> list[tuple[object, ...]]:
        index = {c.id: i for i, c in enumerate(data.campaigns)}
        return sorted(
            (index[m.campaign_id], m.metric_date, m.spend, m.impressions, m.clicks)
            for m in data.ad_metrics
            if (m.metric_date < first) is before
        )

    # The same store: identical until the intervention, faults still find their entities.
    assert figures(cut, True) == figures(small, True) == figures(paused, True)
    early = {o.id for d in (cut, small) for o in d.orders if o.ordered_at.date() < first}

    def sales(data: GeneratedStore) -> list[object]:
        return sorted(str(ln.net_amount) for ln in data.lines if ln.order_id in early)

    assert sales(cut) == sales(small)

    def spend_after(data: GeneratedStore) -> float:
        return sum(float(f[2]) for f in figures(data, False) if f[0] == 0)

    assert 0 < spend_after(cut) < 0.6 * spend_after(small)
    assert spend_after(paused) == 0
    others = [f for f in figures(paused, False) if f[0] != 0]
    assert others
    assert len(others) == len([f for f in figures(small, False) if f[0] != 0])


def test_faults_still_apply_under_interventions() -> None:
    manifest = next(m for m in load_suite("golden") if m.scenario_id == "golden-cpa_drift")
    data = manifest.generate(interventions=[Intervention(100, 0, 0.7)])
    assert data.store.store_id == manifest.generate().store.store_id
    assert data.interventions == (Intervention(100, 0, 0.7),)


def test_a_restock_ends_a_stockout() -> None:
    manifest = next(
        m for m in load_suite("golden") if m.scenario_id == "golden-stockout_on_promoted"
    )
    label = manifest.labels[0]
    product = next(e.id for e in label.entities if e.kind.value == "product")
    assert product is not None
    restock = label.start_day + 10

    def sales_days(data: GeneratedStore) -> set[int]:
        orders = {o.id: o for o in data.orders}
        start = manifest.config.start_date
        return {
            (orders[line.order_id].ordered_at.date() - start).days
            for line in data.lines
            if line.product_id == product
        }

    def stock(data: GeneratedStore, day: int) -> int:
        when = manifest.config.start_date + timedelta(days=day)
        return next(
            s.units_on_hand
            for s in data.inventory
            if s.product_id == product and s.snapshot_date == when
        )

    plain = manifest.generate()
    restocked = manifest.generate(interventions=[Restock(day=restock, product=product)])
    assert not {d for d in sales_days(plain) if d >= label.start_day}  # lasts to the end
    after = sales_days(restocked)
    assert not {d for d in after if label.start_day <= d < restock}
    assert {d for d in after if d >= restock}
    assert stock(restocked, restock - 1) == 0
    assert stock(restocked, restock) > 0
    assert stock(plain, restock) == 0
