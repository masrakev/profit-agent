"""A deterministic fake of the Meta Model API for tests and dry runs.

`FakeTransport` is an HTTP transport the real SDK client talks to: it answers each
`POST /v1/responses` with the next scripted step and records the request bodies it received.
The builders produce bodies in the documented Responses API format
(https://dev.meta.ai/docs/protocols/responses and the error-handling page), so the provider is
exercised end to end, SDK included, without a network or a key.
"""

import json
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import count
from typing import Any

import httpx2

_ids = count(1)


@dataclass(frozen=True)
class Reply:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Raise:
    """The transport raises instead of answering (e.g. `httpx2.ReadTimeout`)."""

    error: type[httpx2.TransportError]
    message: str = "scripted transport failure"


# A step may also be a function of the request body: a scripted model that reads tool results.
Step = Reply | Raise | Callable[[dict[str, Any]], Reply]


class FakeTransport(httpx2.BaseTransport):
    def __init__(self, steps: Iterable[Step] = ()) -> None:
        self._steps: deque[Step] = deque(steps)
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []

    def add(self, *steps: Step) -> "FakeTransport":
        self._steps.extend(steps)
        return self

    @property
    def remaining(self) -> int:
        return len(self._steps)

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.method != "POST" or not request.url.path.endswith("/responses"):
            return httpx2.Response(404, request=request)
        self.requests.append(json.loads(request.read() or b"{}"))
        self.headers.append({k.lower(): v for k, v in request.headers.items()})
        if not self._steps:
            raise AssertionError("FakeTransport: no scripted step left for this request")
        step = self._steps.popleft()
        if callable(step) and not isinstance(step, Reply | Raise):
            step = step(self.requests[-1])
        if isinstance(step, Raise):
            raise step.error(step.message, request=request)
        return httpx2.Response(step.status, json=step.body, headers=step.headers, request=request)


# --- builders for documented response bodies -------------------------------------------------


def usage(
    input_tokens: int = 100, output_tokens: int = 20, *, cached: int = 0, reasoning: int = 0
) -> dict[str, Any]:
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "total_tokens": input_tokens + output_tokens,
    }


def message(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": f"msg_fake_{next(_ids)}",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def refusal(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": f"msg_fake_{next(_ids)}",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "refusal", "refusal": text}],
    }


def function_call(
    name: str, arguments: dict[str, Any] | str, call_id: str | None = None
) -> dict[str, Any]:
    n = next(_ids)
    return {
        "type": "function_call",
        "id": f"fc_fake_{n}",
        "call_id": call_id or f"call_fake_{n}",
        "name": name,
        "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        "status": "completed",
    }


def reasoning(encrypted: str = "ZmFrZS1yZWFzb25pbmc=") -> dict[str, Any]:
    n = next(_ids)
    return {
        "type": "reasoning",
        "id": f"rs_fake_{n}:rs_{n}",
        "summary": [],
        "encrypted_content": encrypted,
    }


def response(
    output: list[dict[str, Any]],
    *,
    model: str = "muse-spark-1.3",
    status: str = "completed",
    use: dict[str, Any] | None = None,
    incomplete_reason: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"resp_fake_{next(_ids)}",
        "object": "response",
        "created_at": 1793268567.0,  # observed live as a float
        "model": model,
        "status": status,
        "output": output,
        "usage": use or usage(),
        "error": error,
        "incomplete_details": (
            {"reason": incomplete_reason} if incomplete_reason is not None else None
        ),
        "store": False,
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": True,
    }


def ok(output: list[dict[str, Any]], **kwargs: Any) -> Reply:
    return Reply(200, response(output, **kwargs))


def structured(payload: dict[str, Any], **kwargs: Any) -> Reply:
    """A structured-output answer: the JSON document as the message text."""
    return ok([reasoning(), message(json.dumps(payload))], **kwargs)


def error(
    status: int,
    error_type: str,
    message_text: str,
    *,
    code: str | None = None,
    param: str | None = None,
    retry_after: float | None = None,
) -> Reply:
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    body = {"error": {"message": message_text, "type": error_type, "param": param, "code": code}}
    return Reply(status, body, headers)


def rate_limited(retry_after: float | None = 1.0) -> Reply:
    return error(
        429,
        "rate_limit_error",
        "Rate limit exceeded",
        code="rate_limit_exceeded",
        retry_after=retry_after,
    )


def overloaded(retry_after: float | None = None) -> Reply:
    return error(
        503,
        "server_error",
        "Service overloaded",
        code="service_overloaded",
        retry_after=retry_after,
    )
