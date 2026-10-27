"""Application settings, read from the environment (and `.env` when present)."""

from functools import lru_cache

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
