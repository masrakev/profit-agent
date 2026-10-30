"""The agent loop shared by the investigator and Ask.

Every request has the same prefix (system prompt, tool schemas, structured-output format); the
model either calls tools or answers in the schema, in the same requests. Answers are verified
(`check_output` plus caller checks): violations are fed back, at most `MAX_REGENERATIONS` times.
Budgets: at the tool-call cap the model is told to answer; at the cumulative input-token cap, or
when the provider fails, the session stops with no output and a stop reason.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.agent.guard import OutputViolation, check_output, feedback_messages
from app.agent.llm.errors import LLMError, StructuredOutputError
from app.agent.llm.models import ModelId, Usage, load_prices
from app.agent.llm.provider import LLMProvider
from app.agent.llm.types import (
    InputItem,
    LLMRequest,
    LLMResult,
    ReplayedItem,
    ToolOutput,
    UserMessage,
)
from app.agent.loop import known_entities
from app.agent.steps import Step, emit
from app.agent.tools import ToolContext, ToolOutcome, ToolRegistry

MAX_REGENERATIONS = 2
TOOL_BUDGET_REACHED = UserMessage(
    role="developer", text="The tool-call budget is used up: answer now with what you have."
)
BUDGET_STOPS = ("input token budget reached",)


class UsageSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    standard_cost_usd: Decimal = Decimal(0)  # the same tokens at Standard (production) prices
    latency_ms: float = 0.0

    def __add__(self, other: "UsageSummary") -> "UsageSummary":
        return UsageSummary(
            calls=self.calls + other.calls,
            input_tokens=self.input_tokens + other.input_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            standard_cost_usd=self.standard_cost_usd + other.standard_cost_usd,
            latency_ms=round(self.latency_ms + other.latency_ms, 3),
        )


def standard_model(model: ModelId) -> ModelId:
    """The Standard-mode model with the same capability (for production cost estimates)."""
    return ModelId.SPARK if model is ModelId.SPARK_CONTRIBUTOR else model


def summarize(results: list[LLMResult]) -> UsageSummary:
    prices = load_prices()
    total = Usage()
    for r in results:
        total = total + r.usage
    # Contributor runs (benchmark) are repriced at Standard prices: what production pays.
    standard = sum(
        (prices.cost(standard_model(ModelId(r.model)), r.usage) for r in results), Decimal(0)
    )
    return UsageSummary(
        calls=len(results),
        input_tokens=total.input_tokens,
        cached_tokens=total.cached_tokens,
        output_tokens=total.output_tokens,
        reasoning_tokens=total.reasoning_tokens,
        cost_usd=sum((r.cost_usd for r in results), Decimal(0)),
        standard_cost_usd=standard,
        latency_ms=round(sum(r.latency_ms for r in results), 3),
    )


@dataclass
class SessionResult[T: BaseModel]:
    output: T | None
    results: list[LLMResult] = field(default_factory=list)
    outcomes: list[ToolOutcome] = field(default_factory=list)
    tool_calls: int = 0
    regenerations: int = 0
    violations: int = 0  # literal numbers found in rejected outputs
    attached: list[int] = field(default_factory=list)  # facts code added to the evidence
    stop_reason: str | None = None
    elapsed_ms: float = 0.0

    @property
    def stopped_by_budget(self) -> bool:
        reason = self.stop_reason or ""
        return reason in BUDGET_STOPS or reason.startswith("model unavailable")

    def usage(self) -> UsageSummary:
        return summarize(self.results).model_copy(update={"latency_ms": self.elapsed_ms})


def run_session[T: BaseModel](
    provider: LLMProvider,
    registry: ToolRegistry,
    ctx: ToolContext,
    request: LLMRequest,
    schema: type[T],
    *,
    max_tool_calls: int,
    max_input_tokens: int,
    extra_entities: set[str] | None = None,
    prior_outcomes: list[ToolOutcome] | None = None,
    validate: Callable[[T], list[OutputViolation]] | None = None,
    before_answer: Callable[[list[ToolOutcome]], UserMessage | None] | None = None,
    repair: Callable[[T], tuple[T, list[int]]] | None = None,
) -> SessionResult[T]:
    """`request` holds the prefix and the first input items; tools and schema are set here."""
    items: list[InputItem] = list(request.input)
    base = request.model_copy(update={"tools": registry.specs(), "output_schema": schema})
    prior = list(prior_outcomes or [])
    run: SessionResult[T] = SessionResult(output=None)
    started = time.perf_counter()
    try:
        while True:
            if sum(r.usage.input_tokens for r in run.results) >= max_input_tokens:
                run.stop_reason = "input token budget reached"
                return run
            try:
                result = provider.generate(base.model_copy(update={"input": tuple(items)}))
            except StructuredOutputError as exc:
                run.regenerations += 1
                if run.regenerations > MAX_REGENERATIONS:
                    run.stop_reason = "output did not match the schema"
                    return run
                error = OutputViolation("", "schema", str(exc)[:300])
                items.extend(feedback_messages([error], "(not valid JSON for the schema)"))
                continue
            except LLMError as exc:
                run.stop_reason = f"model unavailable ({type(exc).__name__})"
                emit(Step("stopped", None, {"reason": run.stop_reason}))
                return run
            run.results.append(result)
            emit(
                Step(
                    "model",
                    result.model,
                    {
                        "input_tokens": result.usage.input_tokens,
                        "output_tokens": result.usage.output_tokens,
                        "tool_calls": len(result.tool_calls),
                    },
                )
            )
            if result.tool_calls:
                items.extend(ReplayedItem(item=i) for i in result.replay_items)
                for call in result.tool_calls:
                    if run.tool_calls >= max_tool_calls:
                        refused = ToolOutcome(
                            ok=False,
                            tool=call.name,
                            error_code="tool_budget",
                            error="tool-call budget used up: answer now",
                        )
                        items.append(
                            ToolOutput(call_id=call.call_id, output=refused.model_dump_json())
                        )
                        emit(Step("tool", call.name, {"ok": False, "error_code": "tool_budget"}))
                        continue
                    run.tool_calls += 1
                    outcome, output = registry.execute(ctx, call)
                    run.outcomes.append(outcome)
                    items.append(output)
                    emit(
                        Step(
                            "tool",
                            call.name,
                            {
                                "ok": outcome.ok,
                                "error_code": outcome.error_code,
                                "arguments": call.arguments[:500],
                            },
                        )
                    )
                if run.tool_calls >= max_tool_calls:
                    items.append(TOOL_BUDGET_REACHED)
                continue
            if result.refusal is not None:
                run.stop_reason = "the model declined to answer"
                return run
            if before_answer is not None and (nudge := before_answer(run.outcomes)) is not None:
                items.append(nudge)
                continue
            candidate = result.parsed
            assert isinstance(candidate, schema)
            if repair is not None:
                candidate, added = repair(candidate)
                if added:
                    run.attached.extend(added)
                    emit(Step("citation_attached", None, {"facts": added}))
            entities = known_entities([*prior, *run.outcomes]) | (extra_entities or set())
            violations = check_output(
                candidate, known_facts=set(ctx.seen_fact_ids), known_entities=entities
            )
            if validate is not None:
                violations.extend(validate(candidate))
            if not violations:
                run.output = candidate
                emit(Step("answer"))
                return run
            run.violations += sum(v.kind == "number" for v in violations)
            run.regenerations += 1
            emit(Step("regeneration", None, {"violations": [v.describe() for v in violations[:5]]}))
            if run.regenerations > MAX_REGENERATIONS:
                run.stop_reason = "its output failed verification after every regeneration"
                return run
            items.extend(feedback_messages(violations, candidate.model_dump_json()))
    finally:
        run.elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
