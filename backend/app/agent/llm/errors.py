"""Errors of the model layer.

Retryable errors are transient on the provider side (rate limit, overload, server error,
timeout, lost connection): the provider retries them with backoff and counts them against the
circuit breaker. Everything else is raised to the caller at once.
"""


class LLMError(Exception):
    """Base class of every model-layer error."""


class RetryableLLMError(LLMError):
    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RateLimitedError(RetryableLLMError):
    """HTTP 429 `rate_limit_error`."""


class ProviderUnavailableError(RetryableLLMError):
    """HTTP 500 / 503 `server_error`, or a response that ended `failed` on the server side."""


class LLMTimeoutError(RetryableLLMError):
    """The client-side timeout expired."""


class LLMConnectionError(RetryableLLMError):
    """The connection failed before a response arrived."""


class NonRetryableLLMError(LLMError):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class InvalidRequestError(NonRetryableLLMError):
    """HTTP 400 / 404 / 413: the request must change before it can succeed."""


class AuthenticationFailedError(NonRetryableLLMError):
    """HTTP 401 / 402 / 403: key, billing or access."""


class GatewayTimeoutError(NonRetryableLLMError):
    """HTTP 504: the request does too much work for one non-streaming call. Retrying it as is
    does not help (shorter input, smaller output or lower effort does)."""


class ResponseFormatError(NonRetryableLLMError):
    """The response does not have the documented Responses API shape."""


class IncompleteResponseError(NonRetryableLLMError):
    """The response ended `incomplete` (e.g. it ran out of output tokens)."""


class StructuredOutputError(NonRetryableLLMError):
    """The model's structured output does not parse into the requested schema."""


class BudgetExceededError(LLMError):
    """The call could exceed the per-run, daily or total spending cap: it was not made."""


class CircuitOpenError(LLMError):
    """The provider failed repeatedly; calls are refused until the cool-down ends."""


class ContributorModeForbiddenError(LLMError):
    """Contributor mode (prompts may train Meta models) was requested for real store data."""


class RecordingForbiddenError(LLMError):
    """Record mode writes committed cassettes: only synthetic data may be recorded."""


class MissingApiKeyError(LLMError):
    """Live or record mode without `MODEL_API_KEY`."""


class CassetteMissError(LLMError):
    """Replay mode found no recorded response for the request."""

    def __init__(self, key: str, summary: str) -> None:
        super().__init__(f"no cassette {key} for {summary}; record it with LLM_MODE=record")
        self.key = key
