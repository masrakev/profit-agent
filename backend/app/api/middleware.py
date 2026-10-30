"""Request ids, security headers and rate limits, for every API response (ADR 0020).

- Request id: a valid incoming `X-Request-ID` is kept, otherwise one is made; it is in the
  response header, in error bodies and in every log line of the request.
- Security headers on `/api` responses: no sniffing, no framing, no referrer, a CSP that loads
  nothing, HSTS, and no caching (responses are per caller).
- Rate limits, fixed one-minute windows: per client IP, stricter on sign-in routes, and per
  store for store routes. Over a limit: 429 with `Retry-After`. Counters are kept in the
  process (one API process per deployment for now; a shared store such as Redis would be the
  next step with several).
"""

import re
import time
import uuid
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.problems import problem

REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
STORE_PATH = re.compile(r"^/api/v1/stores/([0-9a-fA-F-]{36})(?:/|$)")
SIGN_IN = ("/api/v1/auth/magic-links", "/api/v1/auth/sessions")
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"strict-transport-security", b"max-age=63072000; includeSubDomains"),
    (b"cache-control", b"no-store"),
    (b"cross-origin-resource-policy", b"same-origin"),
)


@dataclass
class Limits:
    per_ip: int = 120  # requests per minute from one client address
    per_store: int = 600  # requests per minute to one store
    sign_in_per_ip: int = 10  # sign-in requests per minute from one address


@dataclass
class RateLimiter:
    limits: Limits = field(default_factory=Limits)
    clock: Callable[[], float] = time.monotonic
    window_s: float = 60.0
    _counts: dict[tuple[str, int], int] = field(default_factory=dict)

    def hit(self, key: str, limit: int) -> float | None:
        """Count one request; the seconds to wait when over the limit, else None."""
        now = self.clock()
        window = int(now // self.window_s)
        if len(self._counts) > 10_000:  # drop past windows
            self._counts = {k: v for k, v in self._counts.items() if k[1] >= window}
        count = self._counts.get((key, window), 0) + 1
        self._counts[(key, window)] = count
        if count > limit:
            return (window + 1) * self.window_s - now
        return None


def _client(scope: Scope) -> str:
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


class ApiMiddleware:
    """The rate limiter is the application's `state.limiter` (replaceable, e.g. in tests)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        rid = incoming if REQUEST_ID.match(incoming) else uuid.uuid4().hex
        state: MutableMapping[str, Any] = scope.setdefault("state", {})
        state["request_id"] = rid
        path: str = scope.get("path", "")
        api = path.startswith("/api/")
        structlog.contextvars.bind_contextvars(request_id=rid)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = [(b"x-request-id", rid.encode())]
                if api:
                    extra.extend(SECURITY_HEADERS)
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        try:
            limiter: RateLimiter = scope["app"].state.limiter
            wait = self._limited(limiter, scope, path) if api else None
            if wait is not None:
                response = problem(
                    Request(scope),
                    429,
                    detail="too many requests: retry later",
                    headers={"Retry-After": str(max(1, int(wait + 0.999)))},
                )
                await response(scope, receive, send_with_headers)
                return
            await self.app(scope, receive, send_with_headers)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

    @staticmethod
    def _limited(limiter: RateLimiter, scope: Scope, path: str) -> float | None:
        limits, ip = limiter.limits, _client(scope)
        if path in SIGN_IN and scope.get("method") == "POST":
            wait = limiter.hit(f"sign-in:{ip}", limits.sign_in_per_ip)
            if wait is not None:
                return wait
        wait = limiter.hit(f"ip:{ip}", limits.per_ip)
        if wait is not None:
            return wait
        store = STORE_PATH.match(path)
        if store is not None:
            return limiter.hit(f"store:{store.group(1).lower()}", limits.per_store)
        return None
