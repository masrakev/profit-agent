import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from app.db import tenant_transaction
from app.facts import recompute
from app.facts.engine import FactEngine
from app.facts.formulas import REGISTRY
from app.facts.model import Fact, FactKind, FactStatus, Period, Scope, ScopeKind, Unit
from app.facts.registry import (
    Computed,
    Formula,
    FormulaRegistry,
    UnknownFormulaError,
    UnsupportedScopeError,
)
from app.facts.repository import FactIntegrityError, get_facts
from tests.builders import Scenario
from tests.conftest import create_store

JAN = Period.days(date(2026, 1, 1), date(2026, 2, 1))


def _seed(app_engine: Engine) -> tuple[UUID, UUID, list[UUID]]:
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        s = Scenario(conn, store)
        p = s.product("25.00", "10.00", "1.00")
        lines = [
            s.order(
                f"2026-01-{d:02d}T09:00:00", [(p, 1, "25.00", "10.00", "1.00")], payment_fee="1.00"
            )[0]
            for d in (2, 3, 4)
        ]
        s.refund(lines[0], "2026-01-10T00:00:00", "25.00")
        s.stock(p, "2026-01-30", 10)
        c = s.campaign([p])
        s.ad_day(c, "2026-01-02", "30.00", 2, "50.00")
        s.fixed_cost("62.00", "2026-01-01", "2026-02-01")
    return store, p, lines


@pytest.mark.db
def test_recompute_is_deterministic_and_idempotent(app_engine: Engine) -> None:
    store, _, _ = _seed(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        engine = FactEngine(conn, store)
        first, report1 = engine.persist_all(engine.compute_all(JAN))
    # A brand-new engine recomputes from scratch: same hashes, nothing new written.
    with tenant_transaction(app_engine, store) as conn:
        engine = FactEngine(conn, store)
        second, report2 = engine.persist_all(engine.compute_all(JAN))
    assert [f.fact_hash for f in first] == [f.fact_hash for f in second]
    assert [f.id for f in first] == [f.id for f in second]
    assert report1.inserted > 0
    assert report1.existing == 0
    assert report2.inserted == 0
    assert report2.existing == report1.inserted
    assert all(f.status is FactStatus.DEFINED for f in second)


@pytest.mark.db
def test_inputs_change_changes_hash(app_engine: Engine) -> None:
    store, p, _ = _seed(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        before = FactEngine(conn, store).fact("revenue", Scope.store(), JAN)
    with tenant_transaction(app_engine, store) as conn:
        Scenario(conn, store).order("2026-01-20T00:00:00", [(p, 1, "25.00", "10.00", "1.00")])
    with tenant_transaction(app_engine, store) as conn:
        after = FactEngine(conn, store).fact("revenue", Scope.store(), JAN)
    assert after.value == before.value + Decimal("25.00")
    assert after.inputs_hash != before.inputs_hash
    assert after.fact_hash != before.fact_hash


@pytest.mark.db
def test_lineage_round_trip(app_engine: Engine) -> None:
    store, _, lines = _seed(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        engine = FactEngine(conn, store)
        revenue = engine.persist(engine.fact("revenue", Scope.store(), JAN))
        margin = engine.persist(engine.fact("contribution_margin", Scope.store(), JAN))
    with tenant_transaction(app_engine, store) as conn:
        assert revenue.id is not None
        assert margin.id is not None
        loaded = get_facts(conn, store, [revenue.id, margin.id], with_lineage=True)
    assert {s.id for s in loaded[revenue.id].lineage.sources} == set(lines)
    assert {s.table for s in loaded[revenue.id].lineage.sources} == {"order_lines"}
    parents = loaded[margin.id].lineage.parents
    assert [p.role for p in parents] == ["revenue", "cogs", "fees", "refunds"]
    assert parents[0].fact_hash == revenue.fact_hash
    assert loaded[margin.id].fact_hash == margin.fact_hash
    assert loaded[margin.id].value == Decimal("75.00") - 30 - 6 - 25


@pytest.mark.db
def test_tampered_fact_is_detected(app_engine: Engine, owner_engine: Engine) -> None:
    store, _, _ = _seed(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        engine = FactEngine(conn, store)
        fact = engine.persist(engine.fact("revenue", Scope.store(), JAN))
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE facts SET value = value + 1 WHERE id = :id"), {"id": fact.id})
    with tenant_transaction(app_engine, store) as conn, pytest.raises(FactIntegrityError):
        get_facts(conn, store, [fact.id or 0])


@pytest.mark.db
def test_scope_and_formula_errors(app_engine: Engine) -> None:
    store, p, _ = _seed(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        engine = FactEngine(conn, store)
        with pytest.raises(UnsupportedScopeError):
            engine.fact("net_profit", Scope.product(p), JAN)
        with pytest.raises(UnknownFormulaError):
            engine.fact("ebitda", Scope.store(), JAN)
    with tenant_transaction(app_engine, uuid4()) as conn, pytest.raises(LookupError):
        FactEngine(conn, store)  # the tenant does not match: the store is invisible


@pytest.mark.db
def test_recompute_cli(app_engine: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    store, _, _ = _seed(app_engine)
    assert recompute.main(["--store", str(store)]) == 0
    summary = json.loads(capsys.readouterr().out)
    # Default period: every UTC day with an order (Jan 2 – Jan 4).
    assert summary["period"] == {
        "start": "2026-01-02T00:00:00+00:00",
        "end": "2026-01-05T00:00:00+00:00",
    }
    assert summary["inserted"] > 0
    assert (
        recompute.main(["--store", str(store), "--start", "2026-01-01", "--end", "2026-02-01"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["undefined_by_formula"] == {}
    with pytest.raises(SystemExit):
        recompute.main(["--store", str(store), "--start", "2026-01-01"])
    empty = create_store(app_engine)
    with pytest.raises(ValueError, match="no orders"):
        recompute.main(["--store", str(empty)])


def test_registry_rules() -> None:
    assert len(REGISTRY) == 24
    assert {f.formula_id for f in REGISTRY.for_scope(ScopeKind.STORE)} >= {
        "revenue",
        "net_profit",
        "roas",
        "poas",
        "cpa",
        "fixed_costs",
    }
    assert all(f.kind is FactKind.EXACT and f.version == 1 for f in REGISTRY)
    registry = FormulaRegistry()

    def compute(*_: object) -> Computed:
        return Computed(Decimal(0), None, "0" * 64)

    base = Formula(
        "x", 1, FactKind.EXACT, Unit.COUNT, frozenset({ScopeKind.STORE}), (), "", compute
    )
    registry.register(base)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(base)
    with pytest.raises(ValueError, match="unregistered inputs"):
        registry.register(
            Formula(
                "y",
                1,
                FactKind.EXACT,
                Unit.COUNT,
                frozenset({ScopeKind.STORE}),
                ("z",),
                "",
                compute,
            )
        )
    assert [f.formula_id for f in registry] == ["x"]


def _fact(**overrides: object) -> Fact:
    fields: dict[str, object] = {
        "store_id": UUID(int=1),
        "formula_id": "revenue",
        "formula_version": 1,
        "kind": FactKind.EXACT,
        "scope": Scope.store(),
        "period": JAN,
        "status": FactStatus.DEFINED,
        "value": Decimal("1.00"),
        "unit": Unit.MONEY,
        "currency": "USD",
        "inputs_hash": "a" * 64,
    }
    fields.update(overrides)
    return Fact.model_validate(fields)


def test_fact_invariants() -> None:
    assert _fact().fact_hash == _fact().fact_hash
    assert _fact().fact_hash != _fact(value=Decimal("1.0")).fact_hash  # scale is part of the value
    with pytest.raises(ValueError, match="defined fact"):
        _fact(value=None)
    with pytest.raises(ValueError, match="undefined fact"):
        _fact(status=FactStatus.UNDEFINED)
    with pytest.raises(ValueError, match="P10"):
        _fact(kind=FactKind.ESTIMATE)
    with pytest.raises(ValueError, match="method"):
        _fact(kind=FactKind.ESTIMATE, p10=Decimal(1), p50=Decimal(1), p90=Decimal(1))
    with pytest.raises(ValueError, match="currency"):
        _fact(unit=Unit.RATIO)
    with pytest.raises(ValueError, match="store scope"):
        Scope(kind=ScopeKind.STORE, id=uuid4())
    with pytest.raises(ValueError, match="end must be after"):
        Period.days(date(2026, 1, 2), date(2026, 1, 2))
    with pytest.raises(ValueError, match="timezone"):
        Period(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2))  # noqa: DTZ001
    plus_one = timezone(timedelta(hours=1))
    with pytest.raises(ValueError, match="UTC"):
        Period(
            start=datetime(2026, 1, 1, tzinfo=plus_one), end=datetime(2026, 1, 2, tzinfo=plus_one)
        )
