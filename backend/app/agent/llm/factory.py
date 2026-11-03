"""Build the provider (and the transcriber) from settings: transport by mode, key, caps and spend
ledger.

- `live`: real HTTP; spend recorded in the shared ledger file.
- `record`: real HTTP, every exchange written as a cassette; synthetic data only.
- `replay` (the default): cassettes only, no key, no network; replayed costs are computed and
  traced but kept in memory, since no money is spent.
"""

from dataclasses import dataclass
from pathlib import Path

import httpx2
from opentelemetry.trace import TracerProvider

from app.agent.llm.budget import BudgetCaps, BudgetGuard, InMemorySpendLedger, JsonlSpendLedger
from app.agent.llm.cassette import CassetteStore, LLMMode, RecordTransport, ReplayTransport
from app.agent.llm.errors import MissingApiKeyError
from app.agent.llm.provider import MetaResponsesProvider
from app.agent.llm.resilience import RetryPolicy
from app.agent.llm.transcribe import MetaVoiceTranscriber, TranscribeRetryPolicy
from app.config import Settings, repo_path

REPLAY_KEY = "replay-mode-needs-no-key"


@dataclass(frozen=True)
class _Wiring:
    mode: LLMMode
    transport: httpx2.BaseTransport
    api_key: str
    guard: BudgetGuard


def _wiring(
    settings: Settings,
    mode: LLMMode | None,
    live_transport: httpx2.BaseTransport | None,
    cassette_dir: Path | None,
) -> _Wiring:
    mode = mode or LLMMode(settings.llm_mode)
    store = CassetteStore(cassette_dir or repo_path(settings.llm_cassette_dir))
    caps = BudgetCaps(
        per_run_usd=settings.llm_run_budget_usd,
        daily_usd=settings.llm_daily_budget_usd,
        total_usd=settings.llm_total_budget_usd,
    )
    if mode is LLMMode.REPLAY:
        guard = BudgetGuard(caps, InMemorySpendLedger())
        replay = ReplayTransport(store, pace=settings.llm_replay_pace)
        return _Wiring(mode, replay, REPLAY_KEY, guard)
    if settings.model_api_key is None or not settings.model_api_key.get_secret_value():
        raise MissingApiKeyError(f"LLM_MODE={mode.value} needs MODEL_API_KEY")
    inner = live_transport or httpx2.HTTPTransport(retries=0)
    transport = inner if mode is LLMMode.LIVE else RecordTransport(inner, store)
    guard = BudgetGuard(caps, JsonlSpendLedger(repo_path(settings.llm_spend_ledger)))
    return _Wiring(mode, transport, settings.model_api_key.get_secret_value(), guard)


def build_provider(
    settings: Settings,
    *,
    mode: LLMMode | None = None,
    tracer_provider: TracerProvider | None = None,
    retry: RetryPolicy | None = None,
    live_transport: httpx2.BaseTransport | None = None,
    cassette_dir: Path | None = None,
) -> MetaResponsesProvider:
    w = _wiring(settings, mode, live_transport, cassette_dir)
    return MetaResponsesProvider(
        api_key=w.api_key,
        transport=w.transport,
        budget=w.guard,
        transport_mode=w.mode.value,
        retry=retry,
        tracer_provider=tracer_provider,
        base_url=settings.model_base_url,
        timeout_s=settings.llm_timeout_s,
    )


def build_transcriber(
    settings: Settings,
    *,
    mode: LLMMode | None = None,
    tracer_provider: TracerProvider | None = None,
    retry: TranscribeRetryPolicy | None = None,
    live_transport: httpx2.BaseTransport | None = None,
    cassette_dir: Path | None = None,
) -> MetaVoiceTranscriber:
    """Muse Voice Transcribe, with the same modes, key, caps and spend ledger as the provider."""
    w = _wiring(settings, mode, live_transport, cassette_dir)
    return MetaVoiceTranscriber(
        api_key=w.api_key,
        transport=w.transport,
        budget=w.guard,
        transport_mode=w.mode.value,
        retry=retry,
        tracer_provider=tracer_provider,
        base_url=settings.model_base_url,
        timeout_s=settings.voice_timeout_s,
    )
