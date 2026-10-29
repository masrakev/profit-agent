"""Build the provider from settings: transport by mode, key, caps and spend ledger.

- `live`: real HTTP; spend recorded in the shared ledger file.
- `record`: real HTTP, every exchange written as a cassette; synthetic data only.
- `replay` (the default): cassettes only, no key, no network; replayed costs are computed and
  traced but kept in memory, since no money is spent.
"""

from pathlib import Path

import httpx2
from opentelemetry.trace import TracerProvider

from app.agent.llm.budget import BudgetCaps, BudgetGuard, InMemorySpendLedger, JsonlSpendLedger
from app.agent.llm.cassette import CassetteStore, LLMMode, RecordTransport, ReplayTransport
from app.agent.llm.errors import MissingApiKeyError
from app.agent.llm.provider import MetaResponsesProvider
from app.agent.llm.resilience import RetryPolicy
from app.config import Settings, repo_path

REPLAY_KEY = "replay-mode-needs-no-key"


def build_provider(
    settings: Settings,
    *,
    mode: LLMMode | None = None,
    tracer_provider: TracerProvider | None = None,
    retry: RetryPolicy | None = None,
    live_transport: httpx2.BaseTransport | None = None,
    cassette_dir: Path | None = None,
) -> MetaResponsesProvider:
    mode = mode or LLMMode(settings.llm_mode)
    store = CassetteStore(cassette_dir or repo_path(settings.llm_cassette_dir))
    caps = BudgetCaps(
        per_run_usd=settings.llm_run_budget_usd,
        daily_usd=settings.llm_daily_budget_usd,
        total_usd=settings.llm_total_budget_usd,
    )
    transport: httpx2.BaseTransport
    if mode is LLMMode.REPLAY:
        transport = ReplayTransport(store)
        api_key = REPLAY_KEY
        guard = BudgetGuard(caps, InMemorySpendLedger())
    else:
        if settings.model_api_key is None or not settings.model_api_key.get_secret_value():
            raise MissingApiKeyError(f"LLM_MODE={mode.value} needs MODEL_API_KEY")
        api_key = settings.model_api_key.get_secret_value()
        inner = live_transport or httpx2.HTTPTransport(retries=0)
        transport = inner if mode is LLMMode.LIVE else RecordTransport(inner, store)
        guard = BudgetGuard(caps, JsonlSpendLedger(repo_path(settings.llm_spend_ledger)))
    return MetaResponsesProvider(
        api_key=api_key,
        transport=transport,
        budget=guard,
        transport_mode=mode.value,
        retry=retry,
        tracer_provider=tracer_provider,
        base_url=settings.model_base_url,
        timeout_s=settings.llm_timeout_s,
    )
