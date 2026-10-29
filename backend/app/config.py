"""Application settings, read from the environment (and `.env` when present)."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Owner connection: migrations and test setup only.
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:55432/profit"
    # Application connection: a non-superuser role subject to row-level security.
    app_database_url: str = "postgresql+psycopg://profit_app:profit_app@localhost:55432/profit"
    app_db_role: str = "profit_app"
    app_db_password: str = "profit_app"  # noqa: S105 - local development default
    redis_url: str = "redis://localhost:56379/0"
    log_level: str = "INFO"

    # Meta Model API (ADR 0009). The key is only needed in live and record modes.
    model_api_key: SecretStr | None = None
    model_base_url: str = "https://api.meta.ai/v1"
    llm_timeout_s: float = 120.0
    llm_run_budget_usd: Decimal = Decimal("0.50")
    llm_daily_budget_usd: Decimal = Decimal("5.00")
    llm_total_budget_usd: Decimal | None = None  # e.g. a task's hard cap
    llm_spend_ledger: str = "data/llm_spend.jsonl"
    # replay: committed cassettes only, never the network (the default, and the only CI mode).
    llm_mode: Literal["live", "record", "replay"] = "replay"
    llm_cassette_dir: str = "backend/tests/cassettes"


REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_path(path: str) -> Path:
    """A settings path, relative to the repository root unless absolute."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
