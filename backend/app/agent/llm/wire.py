"""The Responses API wire format (https://dev.meta.ai/docs/protocols/responses, checked on
2026-10-28), validated strictly so that a format change fails loudly instead of silently.

Only the fields the provider relies on are required; unknown fields and unknown output item
types are allowed (the API may add them).
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.llm.errors import ResponseFormatError


class _Wire(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class OutputText(_Wire):
    type: Literal["output_text"]
    text: str


class Refusal(_Wire):
    type: Literal["refusal"]
    refusal: str


class OtherContent(_Wire):
    type: str


class MessageItem(_Wire):
    type: Literal["message"]
    role: Literal["assistant"]
    content: list[OutputText | Refusal | OtherContent]
    status: str | None = None


class FunctionCallItem(_Wire):
    type: Literal["function_call"]
    call_id: str = Field(min_length=1, max_length=64)
    name: str
    arguments: str  # a JSON document, as a string
    status: str | None = None


class ReasoningItem(_Wire):
    type: Literal["reasoning"]
    id: str
    summary: list[dict[str, Any]]
    encrypted_content: str | None = None


class OtherItem(_Wire):
    type: str


def _item_type(value: Any) -> str:
    kind = value.get("type") if isinstance(value, dict) else getattr(value, "type", None)
    return kind if kind in ("message", "function_call", "reasoning") else "other"


AnyItem = MessageItem | FunctionCallItem | ReasoningItem | OtherItem
_ITEM_MODELS: dict[str, type[AnyItem]] = {
    "message": MessageItem,
    "function_call": FunctionCallItem,
    "reasoning": ReasoningItem,
    "other": OtherItem,
}


class InputTokensDetails(_Wire):
    cached_tokens: int = Field(ge=0)


class OutputTokensDetails(_Wire):
    reasoning_tokens: int = Field(ge=0)


class WireUsage(_Wire):
    input_tokens: int = Field(ge=0)
    input_tokens_details: InputTokensDetails
    output_tokens: int = Field(ge=0)
    output_tokens_details: OutputTokensDetails
    total_tokens: int = Field(ge=0)


class WireResponse(_Wire):
    id: str
    object: Literal["response"]
    model: str
    status: Literal["completed", "failed", "in_progress", "cancelled", "queued", "incomplete"]
    output: list[dict[str, Any]]
    usage: WireUsage
    error: dict[str, Any] | None = None
    incomplete_details: dict[str, Any] | None = None

    def items(self) -> list[AnyItem]:
        parsed: list[AnyItem] = []
        for raw in self.output:
            kind = _item_type(raw)
            try:
                parsed.append(_ITEM_MODELS[kind].model_validate(raw))
            except ValidationError as exc:
                raise ResponseFormatError(f"output item of type {kind!r}: {exc}") from exc
        return parsed


class WireError(_Wire):
    message: str
    type: str | None = None
    param: str | None = None
    code: str | None = None


def parse_response(body: bytes | str) -> WireResponse:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ResponseFormatError(f"response body is not JSON: {exc}") from exc
    try:
        return WireResponse.model_validate(data)
    except ValidationError as exc:
        raise ResponseFormatError(f"unexpected response shape: {exc}") from exc


def parse_error(body: Any) -> WireError | None:
    """The `error` object of an error response, or None when the body has none (e.g. 404 with an
    empty body)."""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        try:
            return WireError.model_validate(body["error"])
        except ValidationError:
            return None
    return None
