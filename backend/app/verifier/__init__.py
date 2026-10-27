"""Numeric grounding: LLM text may only show numbers through `{{F<id>}}` fact references."""

from app.verifier.render import UnknownFactReferenceError, format_fact, render
from app.verifier.verify import Violation, ViolationKind, verify

__all__ = [
    "UnknownFactReferenceError",
    "Violation",
    "ViolationKind",
    "format_fact",
    "render",
    "verify",
]
