"""Run the outbox worker.

    uv run python -m app.executor            # process every ready row once
    uv run python -m app.executor --loop 30  # and keep polling every 30 seconds

Adapters: the simulator always (synthetic stores); the Meta Marketing API when
META_ACCESS_TOKEN and META_AD_ACCOUNT_ID are set (sandbox ad account).
"""

import argparse
import time
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import Engine

from app.config import Settings, get_settings
from app.db import make_engine, tenant_transaction
from app.executor.adapters import Adapter
from app.executor.meta import MetaAdsAdapter
from app.executor.simulator import SimulatorAdapter
from app.executor.worker import Executor
from app.observability import configure_logging, get_logger
from app.privacy.connections import credentials, master_key


def store_meta_adapters(
    engine: Engine, settings: Settings
) -> Callable[[str, UUID], Adapter | None]:
    """A store's Meta adapter from its encrypted connection (ADR 0021), cached per store."""
    cache: dict[UUID, Adapter | None] = {}

    def resolve(provider: str, store_id: UUID) -> Adapter | None:
        if provider != "meta" or settings.token_encryption_key is None:
            return None
        if store_id not in cache:
            with tenant_transaction(engine, store_id) as conn:
                found = credentials(conn, store_id, "meta", master_key(settings))
            cache[store_id] = (
                MetaAdsAdapter(access_token=found[1], ad_account_id=found[0]) if found else None
            )
        return cache[store_id]

    return resolve


def build() -> Executor:
    settings = get_settings()
    engine = make_engine(settings.app_database_url)
    adapters: dict[str, Adapter] = {"simulator": SimulatorAdapter(engine)}
    if settings.meta_access_token and settings.meta_ad_account_id:
        adapters["meta"] = MetaAdsAdapter(
            access_token=settings.meta_access_token.get_secret_value(),
            ad_account_id=settings.meta_ad_account_id,
        )
    return Executor(
        engine,
        adapters,
        meta_links=dict(settings.meta_campaign_links),
        store_adapter=store_meta_adapters(engine, settings),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the outbox worker")
    parser.add_argument("--loop", type=float, help="poll every N seconds")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    executor = build()
    log = get_logger(__name__)
    while True:
        done = executor.run_once()
        log.info("executor.pass", processed=done)
        if args.loop is None:
            return 0
        time.sleep(args.loop)


if __name__ == "__main__":
    raise SystemExit(main())
