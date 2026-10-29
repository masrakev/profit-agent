"""Smoke check of the Meta Model API, per model: one tool call, then one structured output.

Each step is checked against what the provider expects (documented response shape, echoed
model, a `get_fact` call with valid arguments, a parsed answer echoing the fact reference).
Any difference is a failure with a message that says what differed. The prompt carries no store
data, so it may go to the Contributor-mode model (`DataOrigin.SYNTHETIC`).
"""

import json
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from app.agent.llm.errors import LLMError
from app.agent.llm.models import DataOrigin, ModelId, ReasoningEffort, Usage
from app.agent.llm.provider import LLMProvider
from app.agent.llm.types import LLMRequest, ReplayedItem, ToolOutput, ToolSpec, UserMessage
from app.domain.hashing import sha256_hex

INSTRUCTIONS = (
    "This is a connectivity test of a tool-using assistant. First call the tool get_fact for "
    "the fact the user asks about. When the tool result arrives, answer with the exact "
    "reference string it returned in fact_reference, and set used_tool to true."
)
QUESTION = "Look up the fact with id one and report its reference."
PROMPT_VERSION = sha256_hex(INSTRUCTIONS)[:16]
REFERENCE = "{{F1}}"


class FactQuery(BaseModel):
    fact_id: int


class SmokeAnswer(BaseModel):
    fact_reference: str
    used_tool: bool


TOOL = ToolSpec.from_model("get_fact", "Return the reference of a stored fact by id.", FactQuery)


class SmokeFailure(Exception):  # noqa: N818 - a check outcome
    pass


@dataclass(frozen=True)
class SmokeOutcome:
    model: ModelId
    ok: bool
    usage: Usage
    cost_usd: Decimal
    detail: str


def _request(
    model: ModelId, items: tuple[UserMessage | ReplayedItem | ToolOutput, ...]
) -> LLMRequest:
    return LLMRequest(
        model=model,
        data_origin=DataOrigin.SYNTHETIC,
        instructions=INSTRUCTIONS,
        prompt_version=PROMPT_VERSION,
        input=items,
        tools=(TOOL,),
        output_schema=SmokeAnswer,
        reasoning_effort=ReasoningEffort.LOW,
        max_output_tokens=2048,
        run_id=f"smoke-{model.value}",
        purpose="smoke",
    )


def run_model(provider: LLMProvider, model: ModelId) -> SmokeOutcome:
    usage, cost = Usage(), Decimal(0)
    try:
        question = (UserMessage(text=QUESTION),)
        first = provider.generate(_request(model, question))
        usage, cost = usage + first.usage, cost + first.cost_usd
        if first.model != model.value:
            raise SmokeFailure(f"response model {first.model!r}, requested {model.value!r}")
        if not first.tool_calls:
            raise SmokeFailure(f"expected a get_fact call, got text {first.text[:80]!r}")
        outputs = []
        for call in first.tool_calls:
            if call.name != TOOL.name:
                raise SmokeFailure(f"call to unknown tool {call.name!r}")
            try:
                FactQuery.model_validate_json(call.arguments)
            except ValidationError as exc:
                raise SmokeFailure(f"invalid get_fact arguments {call.arguments!r}") from exc
            outputs.append(
                ToolOutput(
                    call_id=call.call_id,
                    output=json.dumps({"fact_id": 1, "reference": REFERENCE}),
                )
            )
        replay = tuple(ReplayedItem(item=i) for i in first.replay_items)
        second = provider.generate(_request(model, (*question, *replay, *outputs)))
        usage, cost = usage + second.usage, cost + second.cost_usd
        if second.tool_calls:
            raise SmokeFailure("expected the final answer, got another tool call")
        answer = second.parsed
        if not isinstance(answer, SmokeAnswer):
            raise SmokeFailure(f"no structured answer (refusal={second.refusal!r})")
        if answer.fact_reference != REFERENCE or not answer.used_tool:
            raise SmokeFailure(f"answer does not echo the tool result: {answer!r}")
    except (SmokeFailure, LLMError) as exc:
        return SmokeOutcome(model, False, usage, cost, f"{type(exc).__name__}: {exc}")
    return SmokeOutcome(model, True, usage, cost, "tool call and structured output as expected")


def run(provider: LLMProvider, models: list[ModelId]) -> list[SmokeOutcome]:
    return [run_model(provider, m) for m in models]
