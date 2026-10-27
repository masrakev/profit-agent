"""Profit attribution facts against PostgreSQL: exact contributions, lineage, guards."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine

from app.causes.drivers import Driver
from app.causes.profit import AttributionUnavailableError, attribute_profit_change
from app.db import tenant_transaction
from app.facts.engine import FactEngine
from app.facts.model import Period, Scope
from app.facts.repository import get_facts
from tests.builders import Scenario
from tests.conftest import create_store

pytestmark = pytest.mark.db

BASE = Period.days(date(2026, 1, 1), date(2026, 1, 15))
CUR = Period.days(date(2026, 2, 1), date(2026, 2, 15))


def _cost_increase_store(app_engine: Engine) -> tuple[UUID, UUID, UUID]:
    """Identical sales in both periods except product A's unit cost: 8.00 -> 9.00."""
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        a = s.product("20.00", "8.00", "1.00")
        b = s.product("10.00", "5.00", "0.50")
        for month, cost in (("01", "8.00"), ("02", "9.00")):
            for day in range(2, 7):
                s.order(f"2026-{month}-{day:02d}T10:00:00", [(a, 2, "20.00", cost, "1.00")])
            for day in range(2, 5):
                s.order(f"2026-{month}-{day:02d}T12:00:00", [(b, 1, "10.00", "5.00", "0.50")])
    return store, a, b


def test_attribution_isolates_the_changed_driver_exactly(app_engine: Engine) -> None:
    # Delta = -(10 units x $1.00) = -10.00, all of it unit cost on product A.
    store, a, b = _cost_increase_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        result = attribute_profit_change(FactEngine(conn, store), BASE, CUR)
    assert result.delta == Decimal(-10)
    assert result.level1[Driver.UNIT_COST].value == Decimal(-10)
    assert all(c.value == 0 for d, c in result.level1.items() if d is not Driver.UNIT_COST)
    assert sum((c.value for c in result.level1.values()), Decimal(0)) == result.delta
    by_product = {c.scope.id: c.value for c in result.level2[Driver.UNIT_COST]}
    assert by_product == {a: Decimal(-10), b: Decimal(0)}
    assert result.largest_negative() is Driver.UNIT_COST

    with tenant_transaction(app_engine, store) as conn:
        ids = [
            result.delta_fact_id,
            result.level1[Driver.UNIT_COST].fact_id,
            result.level2[Driver.UNIT_COST][0].fact_id,
        ]
        facts = get_facts(conn, store, ids, with_lineage=True)
    delta, level1, level2 = (facts[i] for i in ids)
    assert delta.formula_id == "profit_delta"
    assert delta.baseline == BASE
    assert delta.period == CUR
    assert level1.method == "shapley_v1"
    assert level1.scope == Scope.store()
    assert sorted(p.role for p in level1.lineage.parents) == sorted(f"product:{p}" for p in (a, b))
    assert len(level2.lineage.parents) == 10  # 4 product figures + store units, both periods

    with tenant_transaction(app_engine, store) as conn:
        again = attribute_profit_change(FactEngine(conn, store), BASE, CUR)
    assert again.delta_fact_id == result.delta_fact_id  # identical inputs, identical facts


def test_attribution_guards(app_engine: Engine) -> None:
    store, _, _ = _cost_increase_store(app_engine)
    with tenant_transaction(app_engine, store) as conn, pytest.raises(ValueError, match="precede"):
        attribute_profit_change(FactEngine(conn, store), CUR, BASE)
    eur = create_store(app_engine, currency="EUR")
    with tenant_transaction(app_engine, eur) as conn:
        s = Scenario(conn, eur, currency="EUR")
        p = s.product("10.00", "4.00", "0")
        s.order("2026-02-03T10:00:00", [(p, 1, "10.00", "4.00", "0")], currency="USD")
    with tenant_transaction(app_engine, eur) as conn, pytest.raises(AttributionUnavailableError):
        attribute_profit_change(FactEngine(conn, eur), BASE, CUR)
