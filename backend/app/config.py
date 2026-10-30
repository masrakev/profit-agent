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
    # Decisions and execution (ADRs 0016-0017).
    approval_link_secret: SecretStr | None = None  # HMAC key of email approval links
    admin_token: SecretStr | None = None  # the global kill switch endpoint
    meta_access_token: SecretStr | None = None  # Marketing API, sandbox ad account
    meta_ad_account_id: str | None = None  # act_<id>: the only account actions may touch
    # Our campaign id -> Meta campaign id, for synthetic stores mirrored on the sandbox (JSON).
    meta_campaign_links: dict[str, str] = {}
    # Email (ADR 0019). The default is Mailpit from docker compose (its inbox: localhost:8025);
    # a real provider is any SMTP relay, configured here.
    email_smtp_host: str = "localhost"
    email_smtp_port: int = 1025
    email_smtp_security: Literal["none", "starttls", "ssl"] = "none"
    email_smtp_username: str | None = None
    email_smtp_password: SecretStr | None = None
    email_smtp_timeout_s: float = 10.0
    email_from: str = "Profit Agent <briefings@profit-agent.localhost>"
    # Links in messages: the web platform (evidence, decisions, the approval confirmation page).
    app_base_url: str = "http://localhost:3000"
    # Session cookies are Secure (HTTPS only); turn off only for plain-HTTP local development.
    session_cookie_secure: bool = True
    # Master key wrapping the data keys of stores' platform tokens (32 bytes, base64url; ADR
    # 0021). Rotation: a new key id; tokens are re-wrapped, never re-entered.
    token_encryption_key: SecretStr | None = None
    token_encryption_key_id: str = "k1"  # noqa: S105 - the key's name, not the key
    model_trace_retention_days: int = 30


REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_path(path: str) -> Path:
    """A settings path, relative to the repository root unless absolute."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
