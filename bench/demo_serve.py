"""Serve the demo store (`make demo-seed`) for a demo or its end-to-end test.

    uv run python -m bench.demo_serve api         # make demo-api: the API on 127.0.0.1:8000
    uv run python -m bench.demo_serve worker      # the executor, which carries out approvals
    uv run python -m bench.demo_serve whatsapp    # WhatsApp: inbound messages and deliveries
    uv run python -m bench.demo_serve send-alert  # the open critical alert, sent on WhatsApp

Both use the `profit_demo` database. The API replays the demo's recorded model exchanges
(`backend/tests/cassettes/demo/`) at their recorded pace, so the agent's work streams on screen
as it did when recorded; `LLM_MODE=record` in the environment records new exchanges there
instead (a question not recorded yet, with a model key); `LLM_MODE=live` answers WhatsApp
questions with the model itself. All run on the store's clock
(bench/demo_clock.py): the wall's time of day, on the date the brief is dated. Never for real
stores.
"""

import argparse
import os
import sys
from contextlib import AbstractContextManager, nullcontext

from sqlalchemy import create_engine, text

import bench.demo_clock as clock
from app.config import get_settings
from bench.demo_seed import DEMO_DB, OWNER
from bench.runner.__main__ import _with_db


def demo_environment() -> None:
    """Point the app at the demo database and its cassettes, replayed at their pace."""
    settings = get_settings()
    os.environ["APP_DATABASE_URL"] = _with_db(settings.app_database_url, DEMO_DB)
    os.environ["DATABASE_URL"] = _with_db(settings.database_url, DEMO_DB)
    os.environ.setdefault("LLM_MODE", "replay")
    os.environ.setdefault("LLM_REPLAY_PACE", "true")
    os.environ.setdefault("LLM_CASSETTE_DIR", "backend/tests/cassettes/demo")
    os.environ["DEMO_OWNER_EMAIL"] = OWNER  # /demo opens the demo store without an email
    get_settings.cache_clear()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the demo store")
    parser.add_argument("what", choices=["api", "worker", "whatsapp", "send-alert"])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    demo_environment()
    with store_clock():
        if args.what == "api":
            import uvicorn

            uvicorn.run("app.api.main:app", host="127.0.0.1", port=args.port)
            return 0
        if args.what == "whatsapp":
            return whatsapp_worker()
        if args.what == "send-alert":
            return send_alert()
        from app.executor.__main__ import main as executor

        return executor(["--loop", "2"])


def whatsapp_worker() -> int:
    """The scheduler's WhatsApp part only (inbound messages, deliveries): no briefing or
    detection runs on the demo store, so its recorded exchanges stay as they are."""
    from arq import cron, run_worker

    from app.scheduler import worker

    run_worker(
        worker.WorkerSettings,  # type: ignore[arg-type]
        functions=[worker.deliveries, worker.whatsapp_inbound],
        cron_jobs=[cron(worker.deliveries, timeout=300)],
    )
    return 0


def send_alert() -> int:
    """Send the open critical alert (its decision still waiting) to the owner on WhatsApp."""
    from datetime import UTC, datetime

    from app.db import make_engine, tenant_transaction
    from app.delivery.queue import Subject, enqueue
    from app.settings.models import AlertChannel

    settings = get_settings()
    owner = create_engine(settings.database_url)
    with owner.connect() as conn:
        found = conn.execute(
            text(
                "SELECT a.store_id, a.alert_id FROM alerts a JOIN decisions d ON "
                "d.store_id = a.store_id AND d.decision_id = a.decision_id "
                "WHERE a.level = 'critical' AND d.status = 'proposed' "
                "ORDER BY a.deliver_at DESC LIMIT 1"
            )
        ).first()
    owner.dispose()
    if found is None:
        sys.stdout.write("No open critical alert: seed the demo again (make demo-seed).\n")
        return 1
    now = datetime.now(UTC)
    engine = make_engine(settings.app_database_url)
    with tenant_transaction(engine, found.store_id) as conn:
        enqueue(
            conn,
            found.store_id,
            Subject.ALERT,
            str(found.alert_id),
            channels=(AlertChannel.WHATSAPP,),
            recipient=None,
            available_at=now,
            now=now,
        )
    engine.dispose()
    sys.stdout.write("The alert is queued for WhatsApp: the WhatsApp worker sends it.\n")
    return 0


def store_clock() -> AbstractContextManager[None]:
    """The store's date at the wall's time, once the demo is seeded; the wall clock before."""
    engine = create_engine(get_settings().database_url)
    try:
        today = clock.store_today(engine)
    finally:
        engine.dispose()
    return nullcontext() if today is None else clock.travel(clock.on_store_date(today))


if __name__ == "__main__":
    sys.exit(main())
