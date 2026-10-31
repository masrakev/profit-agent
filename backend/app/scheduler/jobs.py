"""What the scheduler runs, as plain functions (the arq tasks in `worker` call them).

- Briefings: every few minutes, each store's due briefings in its own time zone (SPEC section
  4): the daily brief on its weekdays at its time, the weekly report on its weekday, the monthly
  review on its day of the month. A briefing is generated once per store, kind and local day
  (a briefing late because the scheduler was down is generated when it comes back that day).
- Detection: each store's detection run, then its alerts.
- Deliveries: the delivery worker's pass over due email deliveries.

One store's failure is logged and does not stop the others.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, text

from app.agent.llm.provider import LLMProvider
from app.agent.stages import Routing
from app.briefings.models import BriefingKind
from app.briefings.service import generate
from app.briefings.store import find
from app.db import tenant_transaction
from app.delivery.alerts import AlertOutcome, dispatch_alerts
from app.detection.pipeline import run_pipeline
from app.goals import service
from app.observability import get_logger
from app.settings.models import StoreSettings
from app.settings.repository import StoreSettingsRepository

log = get_logger(__name__)


def due(settings: StoreSettings, now: datetime) -> tuple[date, list[BriefingKind]]:
    """The store-local day and the briefings due on it by `now`."""
    local = now.astimezone(ZoneInfo(settings.timezone))
    today, moment = local.date(), local.time()
    kinds = []
    daily, weekly, monthly = settings.daily_brief, settings.weekly_report, settings.monthly_review
    if daily.enabled and today.isoweekday() in daily.weekdays and moment >= daily.at:
        kinds.append(BriefingKind.DAILY)
    if weekly.enabled and today.isoweekday() == weekly.weekday and moment >= weekly.at:
        kinds.append(BriefingKind.WEEKLY)
    if monthly.enabled and today.day == monthly.day_of_month and moment >= monthly.at:
        kinds.append(BriefingKind.MONTHLY)
    return today, kinds


def store_ids(engine: Engine) -> list[UUID]:
    with engine.connect() as conn:
        return list(conn.execute(text("SELECT scheduled_store_ids()")).scalars())


@dataclass(frozen=True)
class Done:
    store_id: UUID
    what: str
    ok: bool
    detail: str = ""


def _each(
    engine: Engine, what: str, run: Callable[[UUID], str], only: Sequence[UUID] | None
) -> list[Done]:
    out = []
    for store_id in store_ids(engine) if only is None else only:
        try:
            detail = run(store_id)
        except Exception as exc:  # one store's failure must not stop the others
            log.exception("scheduler.store_failed", store_id=str(store_id), job=what)
            out.append(Done(store_id, what, False, f"{type(exc).__name__}: {exc}"[:300]))
        else:
            if detail:
                out.append(Done(store_id, what, True, detail))
    return out


def briefings_tick(
    engine: Engine,
    provider: LLMProvider,
    now: datetime,
    *,
    routing: Routing = Routing.PRODUCTION,
    only: Sequence[UUID] | None = None,
) -> list[Done]:
    def run(store_id: UUID) -> str:
        with tenant_transaction(engine, store_id) as conn:
            settings = StoreSettingsRepository(conn).get_or_default(store_id)
            local_today, kinds = due(settings, now)
            todo = [k for k in kinds if find(conn, store_id, k, local_today) is None]
        made = []
        for kind in todo:
            record = generate(
                engine,
                store_id,
                kind,
                provider,
                local_today=local_today,
                now=now,
                routing=routing,
                run_id=f"briefing-{local_today.isoformat()}",
            )
            made.append(f"{kind.value}:{record.status}")
        return ", ".join(made)

    return _each(engine, "briefings", run, only)


def detect_and_alert(engine: Engine, store_id: UUID, now: datetime) -> list[AlertOutcome]:
    run_pipeline(engine, store_id)
    return dispatch_alerts(engine, store_id, now=now)


def detection_tick(
    engine: Engine, now: datetime, *, only: Sequence[UUID] | None = None
) -> list[Done]:
    def run(store_id: UUID) -> str:
        alerts = detect_and_alert(engine, store_id, now)
        return ", ".join(f"{a.level.value}:{a.status}" for a in alerts)

    return _each(engine, "detection", run, only)


def goals_weekly_tick(
    engine: Engine, now: datetime, *, only: Sequence[UUID] | None = None
) -> list[Done]:
    """Weekly tracking of every goal with an accepted plan (`app.goals.service.track`)."""

    def run(store_id: UUID) -> str:
        with tenant_transaction(engine, store_id) as conn:
            tracked = [
                service.track(conn, store_id, g.goal_id, now=now)
                for g in service.active_goals(conn, store_id)
            ]
        return ", ".join(f"{p.goal_id}:{p.status or p.verdict}" for p in tracked if p)

    return _each(engine, "goals_weekly", run, only)


def goals_monthly_tick(
    engine: Engine, now: datetime, *, only: Sequence[UUID] | None = None
) -> list[Done]:
    """The monthly re-forecast of goals beyond 90 days (`app.goals.service.reforecast`)."""

    def run(store_id: UUID) -> str:
        with tenant_transaction(engine, store_id) as conn:
            done = [
                service.reforecast(conn, store_id, g.goal_id, now=now)
                for g in service.active_goals(conn, store_id)
            ]
        return ", ".join(f"{p.goal_id}:{p.verdict}" for p in done if p)

    return _each(engine, "goals_monthly", run, only)
