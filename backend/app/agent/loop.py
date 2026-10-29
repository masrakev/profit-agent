"""The tool loop shared by the investigator and Ask: call tools until the model answers, then
guard the answer.

Tool calls go through the registry (read-only tools only; unknown tools are refused), within a
budget of tool calls. The final answer is produced without tools and must pass the output guard,
whose known facts and entities are exactly those the tools returned in this run.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel

from app.agent.guard import GuardedOutcome, generate_guarded
from app.agent.llm.errors import LLMError
from app.agent.llm.provider import LLMProvider
from app.agent.llm.types import InputItem, LLMRequest, LLMResult, ReplayedItem, ToolOutput
from app.agent.tools import ToolContext, ToolOutcome, ToolRegistry

MAX_TOOL_CALLS = 12
ENTITY_KINDS = ("store", "product", "campaign")


@dataclass
class LoopTrace:
    tool_outcomes: list[ToolOutcome] = field(default_factory=list)
    results: list[LLMResult] = field(default_factory=list)
    stopped: str | None = None  # why the tool phase ended early, if it did

    @property
    def cost_usd(self) -> Decimal:
        return sum((r.cost_usd for r in self.results), Decimal(0))


def known_entities(outcomes: list[ToolOutcome]) -> set[str]:
    """Entities named in tool results: `store`, `product:<uuid>`, `campaign:<uuid>`."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            kind, ident = node.get("kind"), node.get("id")
            if kind in ENTITY_KINDS and "name" in node:
                found.add("store" if kind == "store" else f"{kind}:{ident}")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for outcome in outcomes:
        walk(outcome.result)
    return found


def run_tool_loop[T: BaseModel](
    provider: LLMProvider,
    registry: ToolRegistry,
    ctx: ToolContext,
    request: LLMRequest,
    schema: type[T],
    *,
    fallback: Callable[[str], T],
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> tuple[GuardedOutcome[T], LoopTrace]:
    trace = LoopTrace()
    items: list[InputItem] = list(request.input)
    tool_request = request.model_copy(update={"tools": registry.specs(), "output_schema": None})
    calls = 0
    while True:
        try:
            result = provider.generate(tool_request.model_copy(update={"input": tuple(items)}))
        except LLMError as exc:
            trace.stopped = f"model error during tool use ({type(exc).__name__})"
            break
        trace.results.append(result)
        if not result.tool_calls:
            break
        items.extend(ReplayedItem(item=i) for i in result.replay_items)
        for call in result.tool_calls:
            if calls >= max_tool_calls:
                # Every function call needs an output, even the ones beyond the budget.
                trace.stopped = "tool call budget reached"
                refused = ToolOutcome(
                    ok=False,
                    tool=call.name,
                    error_code="tool_budget",
                    error="tool call budget reached; answer now",
                )
                items.append(ToolOutput(call_id=call.call_id, output=refused.model_dump_json()))
                continue
            calls += 1
            outcome, output = registry.execute(ctx, call)
            trace.tool_outcomes.append(outcome)
            items.append(output)
        if trace.stopped:
            break
    final = request.model_copy(update={"input": tuple(items), "tools": ()})
    guarded = generate_guarded(
        provider,
        final,
        schema,
        known_facts=set(ctx.seen_fact_ids),
        known_entities=known_entities(trace.tool_outcomes),
        fallback=fallback,
    )
    return guarded, trace
