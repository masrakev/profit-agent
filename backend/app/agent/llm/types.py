"""Provider-neutral request and result types, and their Responses API encoding."""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.llm.models import DataOrigin, ModelId, ReasoningEffort, Usage
from app.agent.llm.schema import strict_schema

TOOL_NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"  # the API also allows one dot; we never need it
MIN_OUTPUT_TOKENS = 16  # documented minimum of max_output_tokens


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolSpec(_Frozen):
    """A function tool the model may call. Parameters come from a Pydantic model."""

    name: str = Field(pattern=TOOL_NAME_PATTERN)
    description: str
    parameters: dict[str, Any]

    @classmethod
    def from_model(cls, name: str, description: str, model: type[BaseModel]) -> "ToolSpec":
        return cls(name=name, description=description, parameters=strict_schema(model))

    def wire(self) -> dict[str, Any]:
        # Flat shape on the Responses API (not nested under "function").
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "strict": True,
        }


class UserMessage(_Frozen):
    """Untrusted-capable content: the user's question, or data blocks. Never instructions."""

    text: str
    role: Literal["user", "developer"] = "user"

    def wire(self) -> dict[str, Any]:
        return {
            "type": "message",
            "role": self.role,
            "content": [{"type": "input_text", "text": self.text}],
        }


class ToolOutput(_Frozen):
    call_id: str = Field(min_length=1, max_length=64)
    output: str  # a JSON document, as a string

    def wire(self) -> dict[str, Any]:
        return {"type": "function_call_output", "call_id": self.call_id, "output": self.output}


class ReplayedItem(_Frozen):
    """An output item of an earlier turn (reasoning or function call) sent back as input, so the
    stateless conversation (`store: false`) keeps the model's reasoning across tool turns."""

    item: dict[str, Any]

    def wire(self) -> dict[str, Any]:
        return dict(self.item)


InputItem = UserMessage | ToolOutput | ReplayedItem


class LLMRequest(_Frozen):
    model: ModelId
    data_origin: DataOrigin
    instructions: str  # the system prompt: trusted, versioned text only
    prompt_version: str  # content hash of the prompt file(s)
    input: tuple[InputItem, ...]
    tools: tuple[ToolSpec, ...] = ()
    output_schema: type[BaseModel] | None = None
    schema_name: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    reasoning_effort: ReasoningEffort = ReasoningEffort.LOW
    max_output_tokens: int = Field(default=4096, ge=MIN_OUTPUT_TOKENS)
    # Routes requests sharing a prefix to the same cache. Defaults to the model, purpose and
    # prompt version, which name the shared prefix (see `cache_key`).
    prompt_cache_key: str | None = None
    run_id: str = "default"
    purpose: str = "unspecified"  # telemetry label, e.g. "investigate" or "smoke"
    store_id: UUID | None = None

    @field_validator("output_schema")
    @classmethod
    def _schema_is_strict_compatible(cls, value: type[BaseModel] | None) -> type[BaseModel] | None:
        if value is not None:
            strict_schema(value)
        return value

    def body(self) -> dict[str, Any]:
        """The `POST /v1/responses` body. Stable key order: it is hashed for cassettes."""
        body: dict[str, Any] = {
            "model": self.model.value,
            "instructions": self.instructions,
            "input": [item.wire() for item in self.input],
            "reasoning": {"effort": self.reasoning_effort.value},
            "max_output_tokens": self.max_output_tokens,
            # Store data is not retained server side; reasoning is carried over statelessly.
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        if self.tools:
            body["tools"] = [t.wire() for t in self.tools]
            body["tool_choice"] = "auto"  # the only value the API supports
        if self.output_schema is not None:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": self.schema_name or self.output_schema.__name__,
                    "schema": strict_schema(self.output_schema),
                    "strict": True,
                }
            }
        body["prompt_cache_key"] = self.cache_key
        return body

    @property
    def cache_key(self) -> str:
        """Measured live (2026-10-29): without a key, a follow-up turn reused the first turn's
        cached prefix about half the time (routing); with a stable key, most of the time."""
        return self.prompt_cache_key or (f"{self.model.value}:{self.purpose}:{self.prompt_version}")

    def body_bytes(self) -> int:
        return len(json.dumps(self.body(), ensure_ascii=False).encode("utf-8"))


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # raw JSON string as sent by the model; parse and validate before use

    def parsed_arguments(self) -> Any:
        return json.loads(self.arguments)


@dataclass(frozen=True)
class LLMResult:
    response_id: str
    model: str
    text: str
    parsed: BaseModel | None
    tool_calls: tuple[ToolCall, ...]
    refusal: str | None
    usage: Usage
    cost_usd: Decimal
    latency_ms: float
    attempts: int
    # Output items to send back on the next turn (reasoning and function calls).
    replay_items: tuple[dict[str, Any], ...] = field(default=())
    request_id: str | None = None  # the API's x-request-id, for support requests
