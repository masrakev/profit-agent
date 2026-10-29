"""Numeric grounding: LLM text may only show numbers through `{{F<id>}}` fact references."""

from app.verifier.render import (
    UnknownFactReferenceError,
    entity_references,
    fact_references,
    format_fact,
    render,
)
from app.verifier.verify import Violation, ViolationKind, verify

__all__ = [
    "UnknownFactReferenceError",
    "Violation",
    "ViolationKind",
    "entity_references",
    "fact_references",
    "format_fact",
    "render",
    "verify",
]
