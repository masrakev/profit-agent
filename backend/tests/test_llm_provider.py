"""Meta Responses provider on the fake transport: request encoding, tool calls, structured
output, data policy, error mapping and retries, response-format checks, cost and telemetry."""

import json
from decimal import Decimal

import httpx2
import pytest

from app.agent.llm import (
    ContributorModeForbiddenError,
    DataOrigin,
    ModelId,
    ReasoningEffort,
    StructuredOutputError,
    ToolOutput,
    ToolSpec,
    UserMessage,
)
from app.agent.llm import fake as f
from app.agent.llm.errors import (
    AuthenticationFailedError,
    GatewayTimeoutError,
    IncompleteResponseError,
    InvalidRequestError,
    LLMConnectionError,
    LLMTimeoutError,
    RateLimitedError,
    ResponseFormatError,
)
from app.agent.llm.types import ReplayedItem
from tests.llm_helpers import Answer, Harness, request

TOOL = ToolSpec.from_model("get_answer", "Look something up.", Answer)


def test_request_body_follows_the_documented_shape() -> None:
    h = Harness([f.structured({"summary": "s", "fact_ids": [], "note": None})])
    h.provider.generate(
        request(tools=(TOOL,), output_schema=Answer, prompt_cache_key="investigator:abc")
    )
    body = h.transport.requests[0]
    assert body["model"] == "muse-spark-1.3"
    assert body["instructions"] == "You are a test."
    assert body["input"] == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]}
    ]
    assert body["store"] is False
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["reasoning"] == {"effort": "low"}
    assert body["max_output_tokens"] == 4096
    assert body["tool_choice"] == "auto"
    tool = body["tools"][0]
    assert set(tool) == {"type", "name", "description", "parameters", "strict"}  # flat shape
    assert tool["type"] == "function"
    assert tool["strict"] is True
    fmt = body["text"]["format"]
    assert (fmt["type"], fmt["name"], fmt["strict"]) == ("json_schema", "Answer", True)
    assert fmt["schema"]["additionalProperties"] is False
    assert body["prompt_cache_key"] == "investigator:abc"
    assert h.transport.headers[0]["authorization"] == "Bearer test-key"


def test_tool_call_round_trip_replays_reasoning_and_calls() -> None:
    h = Harness(
        [
            f.ok([f.reasoning("enc-1"), f.function_call("get_answer", {"q": "x"}, "call_1")]),
            f.structured({"summary": "done", "fact_ids": [7], "note": None}),
        ]
    )
    first = h.provider.generate(request(tools=(TOOL,), output_schema=Answer))
    assert [(c.call_id, c.name, c.parsed_arguments()) for c in first.tool_calls] == [
        ("call_1", "get_answer", {"q": "x"})
    ]
    assert first.parsed is None  # a tool turn carries no final answer
    assert [i["type"] for i in first.replay_items] == ["reasoning", "function_call"]
    follow_up = request(
        tools=(TOOL,),
        output_schema=Answer,
        input=(
            UserMessage(text="hello"),
            *(ReplayedItem(item=i) for i in first.replay_items),
            ToolOutput(call_id="call_1", output=json.dumps({"ok": True})),
        ),
    )
    second = h.provider.generate(follow_up)
    assert second.parsed == Answer(summary="done", fact_ids=[7], note=None)
    sent = h.transport.requests[1]["input"]
    assert [i["type"] for i in sent] == [
        "message",
        "reasoning",
        "function_call",
        "function_call_output",
    ]
    assert sent[1]["encrypted_content"] == "enc-1"
    assert sent[3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"ok": true}',
    }


def test_structured_output_must_match_the_schema() -> None:
    h = Harness(
        [
            f.ok([f.message("not json")]),
            f.structured({"summary": "s"}),  # missing fields
            f.ok([f.refusal("I cannot help with that.")]),
        ]
    )
    with pytest.raises(StructuredOutputError):
        h.provider.generate(request(output_schema=Answer))
    with pytest.raises(StructuredOutputError):
        h.provider.generate(request(output_schema=Answer))
    refused = h.provider.generate(request(output_schema=Answer))
    assert (refused.parsed, refused.refusal) == (None, "I cannot help with that.")


def test_plain_text_and_unknown_output_items() -> None:
    h = Harness([f.ok([{"type": "web_search_call", "id": "ws_1"}, f.message("Hi")])])
    result = h.provider.generate(request())
    assert (result.text, result.parsed, result.tool_calls) == ("Hi", None, ())


def test_contributor_mode_only_for_synthetic_data() -> None:
    h = Harness([f.ok([f.message("ok")], model="muse-spark-1.3-contributor")])
    with pytest.raises(ContributorModeForbiddenError):
        h.provider.generate(request(model=ModelId.SPARK_CONTRIBUTOR, data_origin=DataOrigin.REAL))
    assert h.transport.requests == []  # refused before any call
    assert h.guard.spent("default").total == 0
    ok = h.provider.generate(
        request(model=ModelId.SPARK_CONTRIBUTOR, data_origin=DataOrigin.SYNTHETIC)
    )
    assert ok.text == "ok"
    with pytest.raises(InvalidRequestError, match="reasoning effort"):
        h.provider.generate(
            request(
                model=ModelId.SPARK_CONTRIBUTOR,
                data_origin=DataOrigin.SYNTHETIC,
                reasoning_effort=ReasoningEffort.MAX,
            )
        )
    assert len(h.transport.requests) == 1


def test_retryable_errors_are_retried_with_backoff() -> None:
    h = Harness(
        [
            f.rate_limited(retry_after=2.5),
            f.overloaded(),
            f.error(500, "server_error", "boom"),
            f.ok([f.message("finally")]),
        ]
    )
    result = h.provider.generate(request())
    assert (result.text, result.attempts) == ("finally", 4)
    assert len(h.sleeps) == 3
    assert h.sleeps[0] >= 2.5  # Retry-After honoured
    assert 1.0 <= h.sleeps[1] < 2.0  # second backoff: 1 s plus up to 1 s of jitter
    assert 2.0 <= h.sleeps[2] < 3.0


def test_timeouts_and_connection_errors_are_retried() -> None:
    h = Harness(
        [
            f.Raise(httpx2.ReadTimeout),
            f.Raise(httpx2.ConnectError),
            f.ok([f.message("ok")]),
        ]
    )
    assert h.provider.generate(request()).attempts == 3


def test_retries_give_up() -> None:
    h = Harness([f.rate_limited(0.1)] * 3, max_attempts=3)
    with pytest.raises(RateLimitedError):
        h.provider.generate(request())
    assert len(h.transport.requests) == 3
    long_wait = Harness([f.rate_limited(retry_after=600), f.ok([f.message("x")])])
    with pytest.raises(RateLimitedError):  # a Retry-After beyond the limit is not waited for
        long_wait.provider.generate(request())
    assert long_wait.transport.remaining == 1
    timeouts = Harness([f.Raise(httpx2.ReadTimeout)] * 2, max_attempts=2)
    with pytest.raises(LLMTimeoutError):
        timeouts.provider.generate(request())
    lost = Harness([f.Raise(httpx2.ConnectError)], max_attempts=1)
    with pytest.raises(LLMConnectionError):
        lost.provider.generate(request())


@pytest.mark.parametrize(
    ("reply", "error", "code"),
    [
        (
            f.error(400, "invalid_request_error", "bad top_p", param="top_p"),
            InvalidRequestError,
            None,
        ),
        (
            f.error(404, "invalid_request_error", "no model", code="model_not_found"),
            InvalidRequestError,
            "model_not_found",
        ),
        (
            f.error(413, "invalid_request_error", "big", code="payload_too_large"),
            InvalidRequestError,
            "payload_too_large",
        ),
        (
            f.error(401, "authentication_error", "bad key", code="invalid_api_key"),
            AuthenticationFailedError,
            "invalid_api_key",
        ),
        (
            f.error(402, "billing_error", "billing", code="billing_not_configured"),
            AuthenticationFailedError,
            "billing_not_configured",
        ),
        (
            f.error(504, "server_error", "too slow", code="gateway_timeout"),
            GatewayTimeoutError,
            "gateway_timeout",
        ),
        (f.Reply(404, None), InvalidRequestError, None),  # unknown path: empty body
    ],
)
def test_non_retryable_errors_are_raised_at_once(
    reply: f.Reply, error: type[Exception], code: str | None
) -> None:
    h = Harness([reply, f.ok([f.message("never")])])
    with pytest.raises(error) as raised:
        h.provider.generate(request())
    assert getattr(raised.value, "code", None) == code
    assert h.transport.remaining == 1  # not retried


def test_response_status_handling_and_billing_of_incomplete_responses() -> None:
    use = f.usage(10, 16, reasoning=14)
    h = Harness(
        [
            f.ok(
                [f.reasoning()], status="incomplete", incomplete_reason="max_output_tokens", use=use
            ),
            f.ok([], status="failed", error={"code": "server_error", "message": "x"}),
            f.ok([f.message("recovered")]),
            f.ok([], status="failed", error={"code": "invalid_prompt", "message": "no"}),
            f.ok([], status="queued"),
        ]
    )
    with pytest.raises(IncompleteResponseError, match="max_output_tokens"):
        h.provider.generate(request())
    # Observed live: 10 input and 16 output tokens are billed although the response is incomplete.
    assert h.guard.spent("default").total == Decimal("0.0000805")
    assert h.provider.generate(request()).text == "recovered"  # failed + server_error: retried
    with pytest.raises(InvalidRequestError):
        h.provider.generate(request())
    with pytest.raises(ResponseFormatError, match="queued"):
        h.provider.generate(request())


@pytest.mark.parametrize(
    "body",
    [
        "not a response object",
        {
            "id": "r",
            "object": "chat.completion",
            "model": "m",
            "status": "completed",
            "output": [],
            "usage": f.usage(),
        },
        {"id": "r", "object": "response", "model": "m", "status": "completed", "output": []},
        {
            "id": "r",
            "object": "response",
            "model": "m",
            "status": "completed",
            "output": [{"type": "function_call", "name": "x", "arguments": "{}"}],
            "usage": f.usage(),
        },
        {
            "id": "r",
            "object": "response",
            "model": "m",
            "status": "completed",
            "output": [{"type": "message", "role": "assistant", "content": "flat"}],
            "usage": f.usage(),
        },
    ],
)
def test_unexpected_response_shapes_fail_loudly(body: object) -> None:
    h = Harness([f.Reply(200, body)])
    with pytest.raises(ResponseFormatError):
        h.provider.generate(request())


def test_a_transport_bug_is_not_mistaken_for_a_network_error() -> None:
    h = Harness([])  # nothing scripted: the fake raises AssertionError
    with pytest.raises(AssertionError):
        h.provider.generate(request())
    assert h.sleeps == []


def test_span_records_tokens_cost_and_outcome() -> None:
    h = Harness(
        [
            f.ok([f.message("ok")], use=f.usage(1000, 500, cached=400, reasoning=300)),
            f.error(400, "invalid_request_error", "bad"),
        ]
    )
    result = h.provider.generate(request(purpose="test", run_id="run-1"))
    # 600 uncached x 1.25 + 400 cached x 0.15 + 500 output x 4.25, per million tokens.
    assert result.cost_usd == Decimal("0.002935")
    with pytest.raises(InvalidRequestError):
        h.provider.generate(request())
    ok, failed = h.spans()
    attrs = dict(ok.attributes)
    assert attrs["gen_ai.request.model"] == "muse-spark-1.3"
    assert attrs["llm.data_mode"] == "standard"
    assert attrs["llm.transport"] == "fake"
    assert attrs["llm.prompt_version"] == "test-prompt-hash"
    assert (attrs["gen_ai.usage.input_tokens"], attrs["gen_ai.usage.cached_tokens"]) == (1000, 400)
    assert (attrs["gen_ai.usage.output_tokens"], attrs["gen_ai.usage.reasoning_tokens"]) == (
        500,
        300,
    )
    assert attrs["llm.cost_usd"] == "0.002935"
    assert attrs["llm.outcome"] == "ok"
    assert attrs["llm.latency_ms"] >= 0
    assert dict(failed.attributes)["llm.outcome"] == "InvalidRequestError"
    assert not failed.status.is_ok


def test_retry_after_header_that_is_not_a_number_is_ignored() -> None:
    h = Harness(
        [
            f.Reply(503, {"error": {"message": "x"}}, {"retry-after": "soon"}),
            f.ok([f.message("ok")]),
        ]
    )
    assert h.provider.generate(request()).attempts == 2
    assert h.sleeps[0] < 2.0
