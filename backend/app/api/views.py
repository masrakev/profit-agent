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

from app.agent.ask import AskResult
from app.agent.contracts import Answer
from app.briefings.models import Document, Section
from app.channels.render import load_entity_names
from app.facts.catalogue import fact_name, is_change, method_text
from app.facts.model import Fact
from app.facts.repository import get_facts
from app.verifier import entity_references, fact_references
from app.verifier.render import display_fact, display_quantiles, exact_quantiles, format_fact


class Text(BaseModel):
    formatted: str  # exact (the proof sheet's)
    display: str  # short (rounded, signed for a change)


class Quantiles(BaseModel):
    p10: Text
    p50: Text
    p90: Text


class FactOut(BaseModel):
    fact_id: int
    metric: str
    name: str  # what the number is, in a few words ("Change in net profit")
    formula_version: int
    kind: str
    status: str
    formatted: str  # exact, as cited (a range for an estimate): the proof sheet's
    display: str  # short: whole units, a range as "low to high", a change signed ("+$613")
    change: bool  # a difference between two states, shown with its sign
    quantiles: Quantiles | None = None  # an estimate's P10, P50 and P90 as texts
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
    method_description: str | None = None  # how an estimate was made, in words
    simulations: int | None = None  # how many simulated or resampled draws its range rests on
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
    change = is_change(fact.formula_id)
    exact, short = exact_quantiles(fact), display_quantiles(fact, signed=change)
    quantiles = (
        Quantiles(
            **{
                name: Text(formatted=formatted, display=display)
                for name, formatted, display in zip(
                    ("p10", "p50", "p90"), exact, short, strict=True
                )
            }
        )
        if exact is not None and short is not None
        else None
    )
    return FactOut(
        fact_id=fact.id,
        metric=fact.formula_id,
        name=fact_name(fact.formula_id),
        formula_version=fact.formula_version,
        kind=fact.kind.value,
        status=fact.status.value,
        formatted=format_fact(fact),
        display=display_fact(fact, signed=change),
        change=change,
        quantiles=quantiles,
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
        method_description=method_text(fact.method, fact.draws),
        simulations=fact.draws,
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


class AskOut(AskResult):
    """An answer with the facts and the names it cites: a client renders every `{{F<id>}}` as
    a clickable number and every `{{E:...}}` as a name (merchant data: escape it)."""

    facts: dict[str, FactOut]  # by fact id: the evidence and every cited fact
    names: dict[str, str]  # entity reference -> raw merchant name


def answer_texts(answer: Answer) -> list[str]:
    """Every text of an answer that may cite facts or entities."""
    return [
        answer.answer,
        answer.reasoning or "",
        *answer.alternatives,
        answer.uncertainty,
        answer.recommendation or "",
        answer.would_change_my_mind or "",
        *(entity for cause in answer.ranked_causes for entity in cause.entities),
    ]


def ask_out(conn: Connection, result: AskResult) -> AskOut:
    evidence = [f"{{{{F{i}}}}}" for i in result.answer.evidence]
    refs = cited(conn, result.store_id, [*answer_texts(result.answer), *evidence])
    return AskOut(**result.model_dump(), facts=refs.facts, names=refs.names)


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
