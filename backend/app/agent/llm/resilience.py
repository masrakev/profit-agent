"""Retries with exponential backoff and jitter, and a per-provider circuit breaker.

Policy from https://dev.meta.ai/docs/error-handling: retry 429, 500 and 503 (and transient
network failures) with exponential backoff starting around half a second, doubling, plus up to a
second of jitter, honouring `Retry-After`; give up after a few attempts. Never retry 4xx client
errors or 504 as is. Clock, sleep and randomness are injected so tests are deterministic.
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar

from app.agent.llm.errors import CircuitOpenError, RetryableLLMError

T = TypeVar("T")


@dataclass
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 0.5
    factor: float = 2.0
    max_delay: float = 8.0
    max_jitter: float = 1.0
    max_retry_after: float = 60.0  # a longer Retry-After gives up instead of blocking
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=lambda: random.Random(0))  # noqa: S311

    def delay(self, attempt: int, error: RetryableLLMError) -> float | None:
        """Seconds to wait before attempt `attempt + 1`, or None to give up."""
        if attempt >= self.max_attempts:
            return None
        backoff = min(self.base_delay * self.factor ** (attempt - 1), self.max_delay)
        wait = backoff + self.rng.uniform(0, self.max_jitter)
        if error.retry_after is not None:
            if error.retry_after > self.max_retry_after:
                return None
            wait = max(wait, error.retry_after)
        return wait

    def run(self, call: Callable[[int], T], on_failure: Callable[[RetryableLLMError], None]) -> T:
        """Call `call(attempt)` until it succeeds, a non-retryable error escapes, or attempts run
        out (the last retryable error is raised)."""
        attempt = 1
        while True:
            try:
                return call(attempt)
            except RetryableLLMError as error:
                on_failure(error)
                wait = self.delay(attempt, error)
                if wait is None:
                    raise
                self.sleep(wait)
                attempt += 1


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Opens after `failure_threshold` consecutive provider failures; after `cooldown` seconds
    one trial call is let through (half open): success closes it, failure reopens it."""

    name: str = "meta-model-api"
    failure_threshold: int = 5
    cooldown: float = 30.0
    clock: Callable[[], float] = time.monotonic
    _failures: int = 0
    _opened_at: float | None = None
    _trial: bool = False

    @property
    def state(self) -> BreakerState:
        if self._opened_at is None:
            return BreakerState.CLOSED
        if self.clock() - self._opened_at >= self.cooldown:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    def before_call(self) -> None:
        state = self.state
        if state is BreakerState.OPEN or (state is BreakerState.HALF_OPEN and self._trial):
            raise CircuitOpenError(f"circuit {self.name} is open after repeated provider failures")
        if state is BreakerState.HALF_OPEN:
            self._trial = True

    def record_success(self) -> None:
        self._failures, self._opened_at, self._trial = 0, None, False

    def record_failure(self) -> None:
        self._failures += 1
        if self._trial or self._failures >= self.failure_threshold:
            self._opened_at, self._trial = self.clock(), False
