"""Persistence of facts and lineage. Facts are append-only and deduplicated by hash."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

import psycopg
from sqlalchemy import Connection, Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.domain.schema import fact_lineage, facts
from app.facts.model import (
    Fact,
    FactKind,
    FactStatus,
    Lineage,
    ParentRef,
    Period,
    Scope,
    ScopeKind,
    SourceRef,
    Unit,
)

SOURCE_ROLE = "source"


class FactIntegrityError(RuntimeError):
    """A stored fact no longer matches its stored hash."""


def save_fact(conn: Connection, fact: Fact, parent_ids: Mapping[str, int]) -> tuple[int, bool]:
    """Insert `fact` unless an identical one exists. Returns `(id, inserted)`.

    `parent_ids` maps each parent's fact hash to its database id; parents are saved first.
    """
    row = conn.execute(
        pg_insert(facts)
        .values(
            store_id=fact.store_id,
            formula_id=fact.formula_id,
            formula_version=fact.formula_version,
            kind=fact.kind.value,
            scope_kind=fact.scope.kind.value,
            scope_id=fact.scope.id,
            period_start=fact.period.start,
            period_end=fact.period.end,
            baseline_start=fact.baseline.start if fact.baseline else None,
            baseline_end=fact.baseline.end if fact.baseline else None,
            status=fact.status.value,
            value=fact.value,
            p10=fact.p10,
            p50=fact.p50,
            p90=fact.p90,
            method=fact.method,
            significant=fact.significant,
            unit=fact.unit.value,
            currency=fact.currency,
            undefined_reason=fact.undefined_reason,
            inputs_hash=fact.inputs_hash,
            fact_hash=fact.fact_hash,
        )
        .on_conflict_do_nothing(index_elements=["store_id", "fact_hash"])
        .returning(facts.c.id)
    ).first()
    if row is None:
        existing = conn.execute(
            select(facts.c.id).where(
                facts.c.store_id == fact.store_id, facts.c.fact_hash == fact.fact_hash
            )
        ).scalar_one()
        return int(existing), False
    fact_id = int(row.id)
    _save_lineage(conn, fact, fact_id, parent_ids)
    return fact_id, True


def _save_lineage(
    conn: Connection, fact: Fact, fact_id: int, parent_ids: Mapping[str, int]
) -> None:
    by_table: dict[str, list[UUID]] = defaultdict(list)
    for source in fact.lineage.sources:
        by_table[source.table].append(source.id)
    rows: list[tuple[Any, ...]] = [
        (fact.store_id, fact_id, SOURCE_ROLE, table, ids, None) for table, ids in by_table.items()
    ]
    rows.extend(
        (fact.store_id, fact_id, parent.role, None, None, parent_ids[parent.fact_hash])
        for parent in fact.lineage.parents
    )
    if not rows:
        return
    # Binary protocol on the same DBAPI connection (same transaction): uuid arrays of thousands
    # of ids are several times cheaper to send than through text adaptation.
    raw = conn.connection.driver_connection
    assert isinstance(raw, psycopg.Connection)
    with raw.cursor(binary=True) as cur:
        for row in rows:
            cur.execute(
                "INSERT INTO fact_lineage "
                "(store_id, fact_id, role, source_table, source_ids, parent_fact_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                row,
            )


def _fact_from_row(row: Row[Any], lineage: Lineage) -> Fact:
    fact = Fact(
        id=int(row.id),
        store_id=row.store_id,
        formula_id=row.formula_id,
        formula_version=int(row.formula_version),
        kind=FactKind(row.kind),
        scope=Scope(kind=ScopeKind(row.scope_kind), id=row.scope_id),
        period=Period(start=row.period_start, end=row.period_end),
        baseline=(
            Period(start=row.baseline_start, end=row.baseline_end)
            if row.baseline_start is not None
            else None
        ),
        status=FactStatus(row.status),
        value=row.value,
        unit=Unit(row.unit),
        currency=row.currency,
        undefined_reason=row.undefined_reason,
        p10=row.p10,
        p50=row.p50,
        p90=row.p90,
        method=row.method,
        significant=row.significant,
        inputs_hash=row.inputs_hash,
        lineage=lineage,
    )
    if fact.fact_hash != row.fact_hash:
        raise FactIntegrityError(f"fact {row.id} does not match its stored hash")
    return fact


def get_facts(
    conn: Connection, store_id: UUID, fact_ids: Iterable[int], *, with_lineage: bool = False
) -> dict[int, Fact]:
    ids = sorted(set(fact_ids))
    rows = conn.execute(
        select(facts).where(facts.c.store_id == store_id, facts.c.id.in_(ids))
    ).all()
    return {
        int(r.id): _fact_from_row(
            r, load_lineage(conn, store_id, int(r.id)) if with_lineage else Lineage()
        )
        for r in rows
    }


def load_lineage(conn: Connection, store_id: UUID, fact_id: int) -> Lineage:
    parent = facts.alias("parent")
    rows = conn.execute(
        select(
            fact_lineage.c.role,
            fact_lineage.c.source_table,
            fact_lineage.c.source_ids,
            parent.c.fact_hash,
        )
        .select_from(
            fact_lineage.outerjoin(
                parent,
                (parent.c.store_id == fact_lineage.c.store_id)
                & (parent.c.id == fact_lineage.c.parent_fact_id),
            )
        )
        .where(fact_lineage.c.store_id == store_id, fact_lineage.c.fact_id == fact_id)
        .order_by(fact_lineage.c.id)
    ).all()
    sources = tuple(
        SourceRef(table=r.source_table, id=source_id)
        for r in rows
        if r.source_table is not None
        for source_id in r.source_ids
    )
    parents = tuple(
        ParentRef(role=r.role, fact_hash=r.fact_hash) for r in rows if r.source_table is None
    )
    return Lineage(sources=sources, parents=parents)
