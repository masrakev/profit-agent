"""Builders shared by the model-layer tests: a provider on the fake transport, with no sleeping
and an in-memory span exporter."""

from decimal import Decimal
from typing import Any

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel

from app.agent.llm import (
    BudgetCaps,
    BudgetGuard,
    DataOrigin,
    InMemorySpendLedger,
    LLMRequest,
    MetaResponsesProvider,
    ModelId,
    UserMessage,
)
from app.agent.llm.fake import FakeTransport, Step
from app.agent.llm.resilience import CircuitBreaker, RetryPolicy


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Harness:
    def __init__(
        self,
        steps: list[Step] | None = None,
        *,
        caps: BudgetCaps | None = None,
        breaker: CircuitBreaker | None = None,
        max_attempts: int = 4,
    ) -> None:
        self.transport = FakeTransport(steps or [])
        self.sleeps: list[float] = []
        self.exporter = InMemorySpanExporter()
        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.guard = BudgetGuard(
            caps or BudgetCaps(Decimal("1.00"), Decimal("5.00")), InMemorySpendLedger()
        )
        self.clock = Clock()
        self.breaker = breaker or CircuitBreaker(clock=self.clock)
        self.provider = MetaResponsesProvider(
            api_key="test-key",
            transport=self.transport,
            budget=self.guard,
            transport_mode="fake",
            retry=RetryPolicy(max_attempts=max_attempts, sleep=self.sleeps.append),
            breaker=self.breaker,
            tracer_provider=tracer_provider,
        )

    def spans(self) -> list[Any]:
        return list(self.exporter.get_finished_spans())


def request(**overrides: Any) -> LLMRequest:
    fields: dict[str, Any] = {
        "model": ModelId.SPARK,
        "data_origin": DataOrigin.REAL,
        "instructions": "You are a test.",
        "prompt_version": "test-prompt-hash",
        "input": (UserMessage(text="hello"),),
    }
    fields.update(overrides)
    return LLMRequest(**fields)


class Answer(BaseModel):
    summary: str
    fact_ids: list[int]
    note: str | None = None
