"""Muse Voice Transcribe (`muse-voice-transcribe-1.0`) through its file endpoint,
`POST /v1/asr/transcribe` (https://dev.meta.ai/docs/speech-to-text and the API reference,
checked on 2026-11-01), behind the same guards as the Responses API calls (ADR 0026).

One call, in order:
1. the audio is a WAV the endpoint accepts (RIFF/WAVE, mono, 16-bit integer PCM at 16 or
   24 kHz, at most 10 minutes and 32 MB), or `InvalidRequestError` before any call; recording
   writes committed cassettes, so only synthetic data is recorded;
2. budget: reserve the clip's worst-case cost (its duration rounded up to a second), or refuse
   before calling (`BudgetExceededError`);
3. circuit breaker, then the multipart upload through the injected transport (live, record,
   replay or fake), retried with backoff and jitter: a 429 like every model call, a server
   error once (the docs: retry once, then contact support with the session id);
4. strict parsing of the documented `TranscribeResponse`;
5. exact cost from the price table: the whole seconds of `audioDurationMs`, rounded down
   (failed requests and 429 responses are not billed); the reservation is settled to it;
6. one OpenTelemetry span with model, mode, audio size and duration, billed seconds, cost,
   latency and outcome. Never the transcript or the keywords: they are store text.

Request: a `request` JSON part (`model`, `audioEncoding: WAV`, `mode: PUSH_TO_TALK`, and the
optional `keywords` and `languageBias`) and the `audio` part. Response (`Accept:
application/json`): `sessionId`, `transcript`, `audioDurationMs`, `turns` (empty in
`PUSH_TO_TALK`).
"""

import io
import json
import math
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import httpx2
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Tracer, TracerProvider
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.llm.budget import BudgetGuard
from app.agent.llm.errors import (
    AuthenticationFailedError,
    InvalidRequestError,
    LLMConnectionError,
    LLMError,
    LLMTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
    RecordingForbiddenError,
    ResponseFormatError,
    RetryableLLMError,
)
from app.agent.llm.models import AudioModelId, DataOrigin, PriceTable, load_prices
from app.agent.llm.resilience import CircuitBreaker, RetryPolicy
from app.agent.llm.wire import parse_error
from app.observability import get_logger

BASE_URL = "https://api.meta.ai/v1"
PATH = "/asr/transcribe"
SAMPLE_RATES = frozenset({16_000, 24_000})
API_MAX_BYTES = 32 * 1024 * 1024  # larger bodies get HTTP 413
API_MAX_MS = 10 * 60 * 1000  # longer audio gets HTTP 400
MAX_KEYWORDS = 50
MAX_KEYWORD_CHARS = 30  # characters; a longer keyword gets HTTP 400


@dataclass(frozen=True)
class WavInfo:
    sample_rate: int
    frames: int
    size_bytes: int

    @property
    def duration_ms(self) -> int:
        return self.frames * 1000 // self.sample_rate


def inspect_wav(audio: bytes) -> WavInfo:
    """The clip's format, if the endpoint accepts it; `InvalidRequestError` otherwise."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as clip:
            channels, width, rate = clip.getnchannels(), clip.getsampwidth(), clip.getframerate()
            frames = clip.getnframes()
            info = WavInfo(rate, frames, len(audio))
            if channels != 1 or width != 2 or rate not in SAMPLE_RATES:
                raise InvalidRequestError(
                    f"WAV must be mono 16-bit PCM at 16 or 24 kHz, not {channels} channel(s), "
                    f"{width * 8}-bit, {rate} Hz",
                    code="unsupported_audio",
                )
            if info.size_bytes > API_MAX_BYTES or info.duration_ms > API_MAX_MS:
                raise InvalidRequestError("audio over the endpoint's limits", code="audio_too_long")
            if len(clip.readframes(frames)) != frames * width:
                raise InvalidRequestError("WAV data is truncated", code="unsupported_audio")
    except (wave.Error, EOFError) as exc:
        raise InvalidRequestError(f"not a PCM WAV file: {exc}", code="unsupported_audio") from exc
    return info


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TranscriptionRequest(_Frozen):
    audio: bytes = Field(repr=False)
    data_origin: DataOrigin
    # Recognition biasing: the store's product and campaign names, as data (never instructions).
    keywords: tuple[str, ...] = Field(default=(), max_length=MAX_KEYWORDS)
    language_bias: tuple[str, ...] = ()  # language names, e.g. "English"; empty: detected
    model: AudioModelId = AudioModelId.VOICE_TRANSCRIBE
    run_id: str = "default"
    purpose: str = "transcribe"
    store_id: UUID | None = None
    # Correlates the call in the provider's logs; echoed back. Not part of the cassette key.
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")

    def request_part(self) -> dict[str, Any]:
        """The `request` JSON part. Stable key order: it is hashed for cassettes."""
        part: dict[str, Any] = {
            "model": self.model.value,
            "audioEncoding": "WAV",
            "mode": "PUSH_TO_TALK",
        }
        keywords = [k[:MAX_KEYWORD_CHARS] for k in self.keywords if k.strip()]
        if keywords:
            part["keywords"] = keywords
        if self.language_bias:
            part["languageBias"] = list(self.language_bias)
        return part


class TranscribeWire(BaseModel):
    """The documented buffered response; unknown fields are allowed (the API may add some)."""

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    transcript: str
    audio_duration_ms: int = Field(alias="audioDurationMs", ge=0)
    turns: list[dict[str, Any]]


def parse_transcription(body: bytes | str) -> TranscribeWire:
    try:
        return TranscribeWire.model_validate(json.loads(body))
    except json.JSONDecodeError as exc:
        raise ResponseFormatError(f"response body is not JSON: {exc}") from exc
    except ValidationError as exc:
        raise ResponseFormatError(f"unexpected transcription shape: {exc}") from exc


@dataclass(frozen=True)
class Transcription:
    session_id: str
    transcript: str
    audio_duration_ms: int
    billed_seconds: int
    cost_usd: Decimal
    model: str
    latency_ms: float
    attempts: int
    request_id: str | None = None


@dataclass
class TranscribeRetryPolicy(RetryPolicy):
    """A 429 is retried with backoff like every model call; a server error only once."""

    server_error_attempts: int = 2

    def delay(self, attempt: int, error: RetryableLLMError) -> float | None:
        if isinstance(error, ProviderUnavailableError) and attempt >= self.server_error_attempts:
            return None
        return super().delay(attempt, error)


class Transcriber(Protocol):
    def transcribe(self, request: TranscriptionRequest) -> Transcription: ...


class MetaVoiceTranscriber:
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
        timeout_s: float = 60.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._client = httpx2.Client(
            transport=transport,
            base_url=base_url,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self.budget = budget
        self.transport_mode = transport_mode
        self.prices = prices or load_prices()
        self.retry = retry or TranscribeRetryPolicy()
        self.breaker = breaker or CircuitBreaker(name="meta-voice-transcribe")
        self._tracer: Tracer = (tracer_provider or trace.get_tracer_provider()).get_tracer(
            "app.agent.llm"
        )
        self._clock = clock
        self._log = get_logger(__name__)

    def close(self) -> None:
        """Release the HTTP connections."""
        self._client.close()

    def transcribe(self, request: TranscriptionRequest) -> Transcription:
        with self._tracer.start_as_current_span("voice.transcribe") as span:
            span.set_attributes(
                {
                    "gen_ai.system": "meta",
                    "gen_ai.request.model": request.model.value,
                    "llm.data_origin": request.data_origin.value,
                    "llm.transport": self.transport_mode,
                    "llm.purpose": request.purpose,
                    "llm.run_id": request.run_id,
                    "voice.audio_bytes": len(request.audio),
                    "voice.keywords": len(request.keywords),
                }
            )
            attempts, billed, started = 0, 0, self._clock()
            try:
                if self.transport_mode == "record" and request.data_origin is not (
                    DataOrigin.SYNTHETIC
                ):
                    raise RecordingForbiddenError("real store data is never written to cassettes")
                info = inspect_wav(request.audio)
                span.set_attribute("voice.clip_ms", info.duration_ms)
                bound = self.prices.audio_cost(request.model, math.ceil(info.duration_ms / 1000))
                reservation = self.budget.reserve(request.run_id, request.model.value, bound)
                actual = Decimal(0)  # failed requests and 429 responses are not billed
                try:

                    def attempt(n: int) -> tuple[TranscribeWire, str | None]:
                        nonlocal attempts
                        attempts = n
                        self.breaker.before_call()
                        found = self._call(request)
                        self.breaker.record_success()
                        return found

                    def failed(_: RetryableLLMError) -> None:
                        self.breaker.record_failure()

                    try:
                        wire, request_id = self.retry.run(attempt, failed)
                    except ResponseFormatError:
                        actual = bound  # an answer came back: the audio may be billed
                        raise
                    billed = wire.audio_duration_ms // 1000  # whole seconds, rounded down
                    actual = self.prices.audio_cost(request.model, billed)
                finally:
                    self.budget.settle(reservation, actual)
            except Exception as exc:
                self._record(span, 0, Decimal(0), attempts, started, outcome=type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                self._log.warning(
                    "voice.transcription_failed",
                    model=request.model.value,
                    purpose=request.purpose,
                    error=type(exc).__name__,
                    attempts=attempts,
                )
                raise
            cost = actual
            self._record(span, billed, cost, attempts, started, outcome="ok")
            span.set_attribute("voice.audio_duration_ms", wire.audio_duration_ms)
            span.set_attribute("voice.session_id", wire.session_id)
            if request_id:
                span.set_attribute("llm.request_id", request_id)
            self._log.info(
                "voice.transcribed",
                model=request.model.value,
                purpose=request.purpose,
                audio_duration_ms=wire.audio_duration_ms,
                billed_seconds=billed,
                transcript_chars=len(wire.transcript),
                cost_usd=str(cost),
                attempts=attempts,
            )
            return Transcription(
                session_id=wire.session_id,
                transcript=wire.transcript,
                audio_duration_ms=wire.audio_duration_ms,
                billed_seconds=billed,
                cost_usd=cost,
                model=request.model.value,
                latency_ms=(self._clock() - started) * 1000,
                attempts=attempts,
                request_id=request_id,
            )

    def _call(self, request: TranscriptionRequest) -> tuple[TranscribeWire, str | None]:
        part = json.dumps(request.request_part(), ensure_ascii=False).encode("utf-8")
        files = {
            "request": (None, part, "application/json"),
            "audio": ("audio.wav", request.audio, "audio/wav"),
        }
        params = {"sessionId": request.session_id} if request.session_id else None
        try:
            response = self._client.post(
                PATH, files=files, params=params, headers={"Accept": "application/json"}
            )
        except httpx2.TimeoutException as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except httpx2.TransportError as exc:
            raise LLMConnectionError(str(exc)) from exc
        if response.status_code >= 400:
            raise _status_error(response)
        return parse_transcription(response.content), response.headers.get("x-request-id")

    def _record(
        self,
        span: trace.Span,
        billed: int,
        cost: Decimal,
        attempts: int,
        started: float,
        *,
        outcome: str,
    ) -> None:
        span.set_attributes(
            {
                "voice.billed_seconds": billed,
                "llm.cost_usd": str(cost),
                "llm.latency_ms": round((self._clock() - started) * 1000, 3),
                "llm.attempts": attempts,
                "llm.outcome": outcome,
            }
        )


def _retry_after(headers: httpx2.Headers) -> float | None:
    value = headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _status_error(response: httpx2.Response) -> LLMError:
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = None
    error = parse_error(body)
    code = error.code if error else None
    message = f"HTTP {status}: {error.message if error else response.reason_phrase}"
    request_id = response.headers.get("x-request-id")
    if request_id:
        message += f" (request {request_id})"
    if status == 429:
        return RateLimitedError(message, retry_after=_retry_after(response.headers))
    if status >= 500:
        return ProviderUnavailableError(message, retry_after=_retry_after(response.headers))
    if status in (401, 402, 403):
        return AuthenticationFailedError(message, status=status, code=code)
    return InvalidRequestError(message, status=status, code=code)
