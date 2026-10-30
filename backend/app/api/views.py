"""What the web platform receives: facts with their formatted value, and documents (briefings,
the overview) whose text cites facts and entities by reference, with those facts and the raw
names alongside. The platform renders each reference as a clickable number or a name, and
escapes names itself (they are data)."""

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Connection

from app.briefings.models import Document, Section
from app.channels.render import load_entity_names
from app.facts.model import Fact
from app.facts.repository import get_facts
from app.verifier import entity_references, fact_references
from app.verifier.render import format_fact


class FactOut(BaseModel):
    fact_id: int
    metric: str
    formula_version: int
    kind: str
    status: str
    formatted: str  # as shown to the owner (a range for an estimate)
    value: str | None
    p10: str | None = None
    p50: str | None = None
    p90: str | None = None
    unit: str
    currency: str | None
    scope: str  # store, product:<id> or campaign:<id>
    period_start: datetime
    period_end: datetime
    baseline_start: datetime | None = None
    baseline_end: datetime | None = None
    method: str | None = None
    significant: bool | None = None
    undefined_reason: str | None = None


def _str(value: Any) -> str | None:
    return None if value is None else str(value)


def fact_out(fact: Fact) -> FactOut:
    assert fact.id is not None
    scope = (
        fact.scope.kind.value
        if fact.scope.id is None
        else f"{fact.scope.kind.value}:{fact.scope.id}"
    )
    return FactOut(
        fact_id=fact.id,
        metric=fact.formula_id,
        formula_version=fact.formula_version,
        kind=fact.kind.value,
        status=fact.status.value,
        formatted=format_fact(fact),
        value=_str(fact.value),
        p10=_str(fact.p10),
        p50=_str(fact.p50),
        p90=_str(fact.p90),
        unit=fact.unit.value,
        currency=fact.currency,
        scope=scope,
        period_start=fact.period.start,
        period_end=fact.period.end,
        baseline_start=fact.baseline.start if fact.baseline else None,
        baseline_end=fact.baseline.end if fact.baseline else None,
        method=fact.method,
        significant=fact.significant,
        undefined_reason=fact.undefined_reason,
    )


class Cited(BaseModel):
    facts: dict[str, FactOut]  # by fact id (JSON keys are strings)
    names: dict[str, str]  # entity reference -> raw merchant name


def cited(conn: Connection, store_id: UUID, texts: Iterable[str]) -> Cited:
    texts = list(texts)
    ids = {i for t in texts for i in fact_references(t)}
    refs = {r for t in texts for r in entity_references(t)} | {"store"}
    found = get_facts(conn, store_id, ids)
    return Cited(
        facts={str(i): fact_out(f) for i, f in sorted(found.items())},
        names=load_entity_names(conn, store_id, refs),
    )


class DocumentOut(Cited):
    headline: str
    narrative: str | None = None
    sections: list[Section]


def document_out(
    conn: Connection, store_id: UUID, document: Document, narrative: str | None = None
) -> DocumentOut:
    texts = [*document.texts(), *([narrative] if narrative else [])]
    refs = cited(conn, store_id, texts)
    return DocumentOut(
        headline=document.headline,
        narrative=narrative,
        sections=list(document.sections),
        facts=refs.facts,
        names=refs.names,
    )
