"""The arq worker: cron jobs for briefings, detection with alerts, and deliveries.

    uv run arq app.scheduler.worker.WorkerSettings      # make scheduler

- briefings: every five minutes; each store's due briefings, in its time zone (`jobs.due`);
- detection: hourly; each store's detection run, then its alerts;
- deliveries: every minute; due email deliveries;
- retention: daily at 03:17 UTC; model traces past the retention period, expired sign-ins;
- goals_weekly: Mondays at 04:23 UTC; each planned goal's progress, due plan steps proposed;
- goals_monthly: on the 1st at 04:41 UTC; the re-forecast of goals beyond 90 days.

Each cron job is unique across workers (arq holds a lock per job), and every piece of work is
idempotent in the database (one briefing per store, kind and local day; one alert per incident
and level; one delivery per message and channel), so a second worker or a restart never sends
anything twice. The synchronous work runs in a thread, off the event loop.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.agent.llm.factory import build_provider
from app.agent.stages import Routing
from app.channels.email import sender_from_settings
from app.config import get_settings
from app.db import app_engine
from app.delivery.worker import DeliveryWorker
from app.observability import configure_logging, get_logger
from app.privacy.retention import purge
from app.scheduler import jobs

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx["engine"] = app_engine()
    ctx["provider"] = build_provider(settings)
    secret = settings.approval_link_secret
    ctx["delivery"] = DeliveryWorker(
        ctx["engine"],
        sender_from_settings(settings),
        settings.app_base_url,
        approval_secret=secret.get_secret_value() if secret else None,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    ctx["engine"].dispose()


async def briefings(ctx: dict[str, Any]) -> int:
    done = await asyncio.to_thread(
        jobs.briefings_tick, ctx["engine"], ctx["provider"], _now(), routing=Routing.PRODUCTION
    )
    log.info("scheduler.briefings", done=[(str(d.store_id), d.ok, d.detail) for d in done])
    return len(done)


async def detection(ctx: dict[str, Any]) -> int:
    done = await asyncio.to_thread(jobs.detection_tick, ctx["engine"], _now())
    log.info("scheduler.detection", done=[(str(d.store_id), d.ok, d.detail) for d in done])
    return len(done)


async def retention(ctx: dict[str, Any]) -> int:
    days = get_settings().model_trace_retention_days
    purged = await asyncio.to_thread(purge, ctx["engine"], _now(), days=days)
    log.info("scheduler.retention", **purged.__dict__)
    return purged.traces


async def goals_weekly(ctx: dict[str, Any]) -> int:
    done = await asyncio.to_thread(jobs.goals_weekly_tick, ctx["engine"], _now())
    log.info("scheduler.goals_weekly", done=[(str(d.store_id), d.ok, d.detail) for d in done])
    return len(done)


async def goals_monthly(ctx: dict[str, Any]) -> int:
    done = await asyncio.to_thread(jobs.goals_monthly_tick, ctx["engine"], _now())
    log.info("scheduler.goals_monthly", done=[(str(d.store_id), d.ok, d.detail) for d in done])
    return len(done)


async def deliveries(ctx: dict[str, Any]) -> int:
    worker: DeliveryWorker = ctx["delivery"]
    processed = await asyncio.to_thread(worker.run_once)
    if processed:
        log.info("scheduler.deliveries", processed=processed)
    return processed


class WorkerSettings:
    functions = (briefings, detection, deliveries, retention, goals_weekly, goals_monthly)
    cron_jobs = (
        cron(briefings, minute=set(range(0, 60, 5)), run_at_startup=True, timeout=1800),
        cron(detection, minute={7}, timeout=3000),
        cron(deliveries, timeout=300),
        cron(retention, hour={3}, minute={17}, timeout=3000),
        cron(goals_weekly, weekday={0}, hour={4}, minute={23}, timeout=3000),
        cron(goals_monthly, day={1}, hour={4}, minute={41}, timeout=3000),
    )
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 3
    job_timeout = 3600
