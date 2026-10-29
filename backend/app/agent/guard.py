"""Output guard (invariant 9, ADR 0010): every model output is parsed into its schema and
every piece of free text in it is verified before use.

A violation is any of: a literal number (verifier), a reference to a fact or entity that no
tool returned in this run, a malformed reference, a copied data block, an integer that is not
a known fact id, a tool call in a final answer, or output that does not match the schema. On a
violation the model regenerates, at most twice, with the violations fed back; then a
deterministic answer built only from facts is used instead.
"""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

from app.agent.llm.errors import LLMError, StructuredOutputError
from app.agent.llm.provider import LLMProvider
from app.agent.llm.types import LLMRequest, LLMResult, UserMessage
from app.agent.untrusted import contains_block_delimiters
from app.verifier import entity_references, fact_references, verify
from app.verifier.render import ENTITY_REFERENCE, REFERENCE

MAX_REGENERATIONS = 2


@dataclass(frozen=True)
class OutputViolation:
    path: str
    kind: str  # number | unknown_fact | unknown_entity | malformed_reference | data_block
    #            | number_field | tool_call | schema | refusal
    detail: str

    def describe(self) -> str:
        return f"{self.path}: {self.kind}: {self.detail}"


def _walk(value: Any, path: str) -> Iterator[tuple[str, Any]]:
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _walk(getattr(value, name), f"{path}.{name}" if path else name)
    elif isinstance(value, list | tuple):
        for i, item in enumerate(value):
            yield from _walk(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")
    else:
        yield path, value


def check_output(
    output: BaseModel, *, known_facts: set[int], known_entities: set[str]
) -> list[OutputViolation]:
    found: list[OutputViolation] = []
    for path, value in _walk(output, ""):
        if isinstance(value, Enum) or value is None or isinstance(value, bool):
            continue
        if isinstance(value, int):
            if value not in known_facts:
                found.append(OutputViolation(path, "number_field", f"{value} is not a known fact"))
            continue
        if isinstance(value, float | Decimal):
            found.append(OutputViolation(path, "number_field", "numbers are not allowed"))
            continue
        if not isinstance(value, str):
            continue
        for v in verify(value):
            found.append(OutputViolation(path, "number", v.message))
        for fid in sorted(fact_references(value) - known_facts):
            found.append(OutputViolation(path, "unknown_fact", f"{{{{F{fid}}}}} was not returned"))
        for ent in sorted(entity_references(value) - known_entities):
            found.append(OutputViolation(path, "unknown_entity", f"{ent} was not returned"))
        stripped = ENTITY_REFERENCE.sub("", REFERENCE.sub("", value))
        if "{{" in stripped or "}}" in stripped:
            found.append(OutputViolation(path, "malformed_reference", "use {{F<id>}} or {{E:...}}"))
        if contains_block_delimiters(value):
            found.append(OutputViolation(path, "data_block", "do not copy store data blocks"))
    return found


@dataclass
class GuardedOutcome[T: BaseModel]:
    output: T
    source: str  # "model" | "template"
    attempts: int
    violations: list[list[OutputViolation]] = field(default_factory=list)
    results: list[LLMResult] = field(default_factory=list)
    fallback_reason: str | None = None

    @property
    def cost_usd(self) -> Decimal:
        return sum((r.cost_usd for r in self.results), Decimal(0))


def feedback_messages(
    violations: list[OutputViolation], rejected: str
) -> tuple[UserMessage, UserMessage]:
    listed = "\n".join(f"- {v.describe()}" for v in violations[:20])
    return (
        UserMessage(role="developer", text=f"Rejected answer (for reference):\n{rejected[:4000]}"),
        UserMessage(
            role="developer",
            text="Your previous answer was rejected by the output verifier:\n"
            f"{listed}\nRewrite the whole answer in the same schema. Cite every quantity as a "
            "fact reference returned by a tool and every entity as an entity reference; write "
            "no number, name or id yourself.",
        ),
    )


def generate_guarded[T: BaseModel](
    provider: LLMProvider,
    request: LLMRequest,
    schema: type[T],
    *,
    known_facts: set[int],
    known_entities: set[str],
    fallback: Callable[[str], T],
    max_regenerations: int = MAX_REGENERATIONS,
) -> GuardedOutcome[T]:
    if request.output_schema is not schema:
        request = request.model_copy(update={"output_schema": schema})
    outcome: GuardedOutcome[T] | None = None
    history: list[list[OutputViolation]] = []
    results: list[LLMResult] = []
    for attempt in range(1, max_regenerations + 2):
        try:
            result = provider.generate(request)
        except StructuredOutputError as exc:
            violations = [OutputViolation("", "schema", str(exc)[:300])]
            rejected = "(output did not match the schema)"
        except LLMError as exc:
            reason = f"the model was unavailable ({type(exc).__name__})"
            outcome = _template(
                fallback, reason, attempt, history, results, known_facts, known_entities
            )
            return outcome
        else:
            results.append(result)
            if result.refusal is not None:
                return _template(
                    fallback,
                    "the model declined to answer",
                    attempt,
                    history,
                    results,
                    known_facts,
                    known_entities,
                )
            if result.tool_calls or not isinstance(result.parsed, schema):
                violations = [OutputViolation("", "tool_call", "a final answer was expected")]
                rejected = json.dumps([c.name for c in result.tool_calls])
            else:
                violations = check_output(
                    result.parsed, known_facts=known_facts, known_entities=known_entities
                )
                if not violations:
                    return GuardedOutcome(result.parsed, "model", attempt, history, results)
                rejected = result.parsed.model_dump_json()
        history.append(violations)
        request = request.model_copy(
            update={"input": (*request.input, *feedback_messages(violations, rejected))}
        )
    reason = "its output failed verification after every regeneration"
    return _template(
        fallback, reason, max_regenerations + 1, history, results, known_facts, known_entities
    )


def _template[T: BaseModel](
    fallback: Callable[[str], T],
    reason: str,
    attempts: int,
    history: list[list[OutputViolation]],
    results: list[LLMResult],
    known_facts: set[int],
    known_entities: set[str],
) -> GuardedOutcome[T]:
    output = fallback(reason)
    problems = check_output(output, known_facts=known_facts, known_entities=known_entities)
    if problems:  # a bug in the template, never acceptable
        raise AssertionError(f"fallback answer fails verification: {problems}")
    return GuardedOutcome(output, "template", attempts, history, results, reason)
