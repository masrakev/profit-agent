"""`LLMProvider` and its Meta Model API implementation (Responses API through the OpenAI SDK).

One call, in order:
1. data policy: Contributor-mode models only for synthetic data; reasoning effort supported;
2. budget: reserve the worst-case cost, or refuse before calling (`BudgetExceededError`);
3. circuit breaker, then the HTTP call through the injected transport (live, record, replay or
   fake), retried with backoff and jitter on retryable errors (SDK retries are disabled);
4. strict parsing of the documented response shape, status handling, structured output
   validated against the Pydantic schema;
5. exact cost from the versioned price table; the reservation is settled to it;
6. one OpenTelemetry span with model, mode, tokens, cost, latency, prompt hash and outcome.
"""

import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

import httpx2
import openai
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Tracer, TracerProvider
from pydantic import ValidationError

from app.agent.llm.budget import BudgetGuard
from app.agent.llm.errors import (
    AuthenticationFailedError,
    CassetteMissError,
    GatewayTimeoutError,
    IncompleteResponseError,
    InvalidRequestError,
    LLMConnectionError,
    LLMError,
    LLMTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
    RecordingForbiddenError,
    ResponseFormatError,
    RetryableLLMError,
    StructuredOutputError,
)
from app.agent.llm.models import (
    MODELS,
    DataOrigin,
    PriceTable,
    Usage,
    check_data_policy,
    load_prices,
)
from app.agent.llm.resilience import CircuitBreaker, RetryPolicy
from app.agent.llm.types import LLMRequest, LLMResult, ToolCall
from app.agent.llm.wire import (
    FunctionCallItem,
    MessageItem,
    OutputText,
    Refusal,
    WireResponse,
    parse_error,
    parse_response,
)
from app.observability import get_logger

BASE_URL = "https://api.meta.ai/v1"


class LLMProvider(Protocol):
    def generate(self, request: LLMRequest) -> LLMResult: ...


class MetaResponsesProvider:
    def __init__(
        self,
        *,
        api_key: str,
        transport: httpx2.BaseTransport,
        budget: BudgetGuard,
        transport_mode: str,
        prices: PriceTable | None = None,
        retry: RetryPolicy | None = None,
        breaker: CircuitBreaker | None = None,
        tracer_provider: TracerProvider | None = None,
        base_url: str = BASE_URL,
        timeout_s: float = 120.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        # The key is passed explicitly: the SDK must never pick up OPENAI_API_KEY.
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            timeout=timeout_s,
            http_client=httpx2.Client(transport=transport, timeout=timeout_s),
        )
        self.budget = budget
        self.transport_mode = transport_mode
        self.prices = prices or load_prices()
        self.retry = retry or RetryPolicy()
        self.breaker = breaker or CircuitBreaker()
        self._tracer: Tracer = (tracer_provider or trace.get_tracer_provider()).get_tracer(
            "app.agent.llm"
        )
        self._clock = clock
        self._log = get_logger(__name__)

    def generate(self, request: LLMRequest) -> LLMResult:
        spec = MODELS[request.model]
        with self._tracer.start_as_current_span("llm.generate") as span:
            span.set_attributes(
                {
                    "gen_ai.system": "meta",
                    "gen_ai.request.model": request.model.value,
                    "llm.data_mode": spec.mode.value,
                    "llm.data_origin": request.data_origin.value,
                    "llm.transport": self.transport_mode,
                    "llm.purpose": request.purpose,
                    "llm.run_id": request.run_id,
                    "llm.prompt_version": request.prompt_version,
                    "llm.reasoning_effort": request.reasoning_effort.value,
                }
            )
            usage, attempts, started = Usage(), 0, self._clock()
            try:
                check_data_policy(request.model, request.data_origin)
                if self.transport_mode == "record" and request.data_origin is not (
                    DataOrigin.SYNTHETIC
                ):
                    raise RecordingForbiddenError("real store data is never written to cassettes")
                if request.reasoning_effort not in spec.efforts:
                    raise InvalidRequestError(
                        f"{request.model} does not support reasoning effort "
                        f"{request.reasoning_effort}"
                    )
                bound = self.prices.upper_bound(
                    request.model, request.body_bytes(), request.max_output_tokens
                )
                reservation = self.budget.reserve(request.run_id, request.model.value, bound)
                try:

                    def attempt(n: int) -> WireResponse:
                        nonlocal usage, attempts
                        attempts = n
                        self.breaker.before_call()
                        wire = self._call(request)
                        usage = usage + _usage(wire)
                        _raise_for_status(wire)
                        self.breaker.record_success()
                        return wire

                    def failed(_: RetryableLLMError) -> None:
                        self.breaker.record_failure()

                    try:
                        wire = self.retry.run(attempt, failed)
                    except GatewayTimeoutError:
                        self.breaker.record_failure()
                        raise
                    result = self._result(request, wire, usage, attempts, started)
                finally:
                    self.budget.settle(reservation, self.prices.cost(request.model, usage))
            except Exception as exc:
                cost = self.prices.cost(request.model, usage)
                self._record(span, usage, cost, attempts, started, outcome=type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                self._log.warning(
                    "llm.call_failed",
                    model=request.model.value,
                    purpose=request.purpose,
                    error=type(exc).__name__,
                    attempts=attempts,
                    cost_usd=str(cost),
                )
                raise
            self._record(span, usage, result.cost_usd, attempts, started, outcome="ok")
            span.set_attribute("gen_ai.response.model", result.model)
            span.set_attribute("gen_ai.response.id", result.response_id)
            if result.request_id:
                span.set_attribute("llm.request_id", result.request_id)
            self._log.info(
                "llm.call",
                model=request.model.value,
                purpose=request.purpose,
                input_tokens=usage.input_tokens,
                cached_tokens=usage.cached_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                cost_usd=str(result.cost_usd),
                attempts=attempts,
            )
            return result

    def _call(self, request: LLMRequest) -> WireResponse:
        try:
            raw = self._client.responses.with_raw_response.create(**request.body())
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except openai.APIConnectionError as exc:
            cause = exc.__cause__
            if isinstance(cause, CassetteMissError):
                raise cause from None
            if cause is not None and not isinstance(cause, httpx2.TransportError):
                raise cause from None  # a bug in a transport, not a network failure
            raise LLMConnectionError(str(exc)) from exc
        except openai.APIStatusError as exc:
            raise _status_error(exc) from exc
        request_id = raw.http_response.headers.get("x-request-id")
        return parse_response(raw.http_response.content).model_copy(
            update={"request_id": request_id}
        )

    def _result(
        self, request: LLMRequest, wire: WireResponse, usage: Usage, attempts: int, started: float
    ) -> LLMResult:
        texts: list[str] = []
        refusal: str | None = None
        calls: list[ToolCall] = []
        replay = []
        items = wire.items()
        for raw, item in zip(wire.output, items, strict=True):
            if isinstance(item, MessageItem):
                for part in item.content:
                    if isinstance(part, OutputText):
                        texts.append(part.text)
                    elif isinstance(part, Refusal):
                        refusal = part.refusal
            elif isinstance(item, FunctionCallItem):
                calls.append(ToolCall(item.call_id, item.name, item.arguments))
                replay.append(raw)
            elif item.type == "reasoning":
                replay.append(raw)
        text = "".join(texts)
        parsed = None
        if request.output_schema is not None and not calls and refusal is None:
            try:
                parsed = request.output_schema.model_validate(json.loads(text))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise StructuredOutputError(
                    f"structured output does not match {request.output_schema.__name__}: {exc}"
                ) from exc
        return LLMResult(
            response_id=wire.id,
            model=wire.model,
            text=text,
            parsed=parsed,
            tool_calls=tuple(calls),
            refusal=refusal,
            usage=usage,
            cost_usd=self.prices.cost(request.model, usage),
            latency_ms=(self._clock() - started) * 1000,
            attempts=attempts,
            replay_items=tuple(replay),
            request_id=wire.request_id,
        )

    def _record(
        self,
        span: trace.Span,
        usage: Usage,
        cost: Decimal,
        attempts: int,
        started: float,
        *,
        outcome: str,
    ) -> None:
        span.set_attributes(
            {
                "gen_ai.usage.input_tokens": usage.input_tokens,
                "gen_ai.usage.cached_tokens": usage.cached_tokens,
                "gen_ai.usage.output_tokens": usage.output_tokens,
                "gen_ai.usage.reasoning_tokens": usage.reasoning_tokens,
                "llm.cost_usd": str(cost),
                "llm.latency_ms": round((self._clock() - started) * 1000, 3),
                "llm.attempts": attempts,
                "llm.outcome": outcome,
            }
        )


def _usage(wire: WireResponse) -> Usage:
    u = wire.usage
    return Usage(
        input_tokens=u.input_tokens,
        cached_tokens=u.input_tokens_details.cached_tokens,
        output_tokens=u.output_tokens,
        reasoning_tokens=u.output_tokens_details.reasoning_tokens,
    )


def _raise_for_status(wire: WireResponse) -> None:
    if wire.status == "completed":
        return
    if wire.status == "incomplete":
        reason = (wire.incomplete_details or {}).get("reason")
        raise IncompleteResponseError(f"response {wire.id} is incomplete: {reason}", code=reason)
    if wire.status == "failed":
        error = wire.error or {}
        code = error.get("code")
        message = f"response {wire.id} failed: {error.get('message')}"
        if code in ("server_error", "rate_limit_exceeded", "server_shutting_down"):
            raise ProviderUnavailableError(message)
        raise InvalidRequestError(message, code=code)
    raise ResponseFormatError(f"unexpected status {wire.status!r} for a synchronous request")


def _retry_after(headers: httpx2.Headers) -> float | None:
    value = headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _status_error(exc: openai.APIStatusError) -> LLMError:
    status = exc.status_code
    # The SDK exposes either the whole body or its inner `error` object.
    error = parse_error(exc.body) or parse_error({"error": exc.body})
    code = error.code if error else None
    message = f"HTTP {status}: {error.message if error else exc.message}"
    request_id = exc.response.headers.get("x-request-id")
    if request_id:
        message += f" (request {request_id})"
    if status == 429:
        return RateLimitedError(message, retry_after=_retry_after(exc.response.headers))
    if status == 504:
        return GatewayTimeoutError(message, status=status, code=code)
    if status >= 500:
        return ProviderUnavailableError(message, retry_after=_retry_after(exc.response.headers))
    if status in (401, 402, 403):
        return AuthenticationFailedError(message, status=status, code=code)
    return InvalidRequestError(message, status=status, code=code)
