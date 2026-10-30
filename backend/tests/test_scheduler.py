"""The scheduler: what is due in each store's time zone, the ticks, and the arq wiring (no
Redis needed: the tasks are called directly)."""

import asyncio
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from app.agent.llm import fake as f
from app.briefings.models import BriefingKind
from app.channels.email import RecordingSender
from app.db import tenant_transaction
from app.delivery.worker import DeliveryWorker
from app.scheduler import jobs, worker
from app.scheduler.jobs import Done, briefings_tick, detection_tick, due, store_ids
from app.settings.models import DailyBrief, StoreSettings
from app.settings.repository import StoreSettingsRepository
from bench.scenarios.manifest import load_suite
from bench.simulator import register
from tests.llm_helpers import Harness

D, W, M = BriefingKind.DAILY, BriefingKind.WEEKLY, BriefingKind.MONTHLY


def store_settings(**overrides: Any) -> StoreSettings:
    return StoreSettings(store_id=uuid4(), currency="USD", **overrides)


@pytest.mark.parametrize(
    ("now", "timezone", "expected"),
    [
        (datetime(2026, 10, 26, 8, 5, tzinfo=UTC), "UTC", (date(2026, 10, 26), [D, W])),  # Monday
        (datetime(2026, 10, 26, 7, 59, tzinfo=UTC), "UTC", (date(2026, 10, 26), [])),
        (datetime(2026, 10, 27, 9, 0, tzinfo=UTC), "UTC", (date(2026, 10, 27), [D])),
        (datetime(2026, 11, 1, 9, 0, tzinfo=UTC), "UTC", (date(2026, 11, 1), [M])),  # a Sunday
        # After the clock change of Nov 1, 08:00 in New York is 13:00 UTC (EST), not 12:00.
        (datetime(2026, 11, 2, 12, 0, tzinfo=UTC), "America/New_York", (date(2026, 11, 2), [])),
        (datetime(2026, 11, 2, 13, 0, tzinfo=UTC), "America/New_York", (date(2026, 11, 2), [D, W])),
        (datetime(2026, 11, 2, 12, 59, tzinfo=UTC), "Asia/Tokyo", (date(2026, 11, 2), [D, W])),
        (datetime(2026, 11, 2, 22, 0, tzinfo=UTC), "Asia/Tokyo", (date(2026, 11, 3), [])),
    ],
)
def test_what_is_due(now: datetime, timezone: str, expected: tuple[date, list[Any]]) -> None:
    assert due(store_settings(timezone=timezone), now) == expected


def test_a_disabled_or_moved_briefing() -> None:
    monday = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
    off = store_settings(daily_brief=DailyBrief(enabled=False))
    assert due(off, monday) == (date(2026, 10, 26), [W])
    late = store_settings(daily_brief=DailyBrief(at=time(11, 0)))
    assert due(late, monday)[1] == [W]


@pytest.fixture(scope="module")
def store(app_engine: Engine) -> Any:
    manifest = next(m for m in load_suite("dev") if m.scenario_id == "dev-healthy-07")
    store_id = register(app_engine, manifest, 106)
    with tenant_transaction(app_engine, store_id) as conn:
        repo = StoreSettingsRepository(conn)
        repo.save(
            repo.get_or_default(store_id).model_copy(update={"timezone": "Asia/Tokyo"}),
            actor="test",
        )
    return store_id


@pytest.mark.db
def test_the_briefing_tick_runs_once_per_day(app_engine: Engine, store: Any) -> None:
    assert store in store_ids(app_engine)
    monday_9am_tokyo = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    harness = Harness([f.overloaded(), f.overloaded()], max_attempts=1)
    done = briefings_tick(app_engine, harness.provider, monday_9am_tokyo, only=[store])
    assert done == [Done(store, "briefings", True, "daily:facts_only, weekly:facts_only")]
    again = briefings_tick(app_engine, harness.provider, monday_9am_tokyo, only=[store])
    assert again == []
    assert len(harness.transport.requests) == 2


@pytest.mark.db
def test_one_store_failing_does_not_stop_the_others(app_engine: Engine, store: Any) -> None:
    missing = uuid4()
    done = detection_tick(app_engine, datetime.now(UTC), only=[missing, store])
    assert [d.store_id for d in done] == [missing]  # the healthy store raised no alert
    assert not done[0].ok
    assert done[0].detail


@pytest.mark.db
def test_the_arq_tasks(app_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def tick(name: str) -> Any:
        def run(*_: Any, **__: Any) -> list[Done]:
            calls.append(name)
            return [Done(uuid4(), name, True, "x")]

        return run

    monkeypatch.setattr(jobs, "briefings_tick", tick("briefings"))
    monkeypatch.setattr(jobs, "detection_tick", tick("detection"))
    sender = RecordingSender()
    ctx: dict[str, Any] = {
        "engine": app_engine,
        "provider": Harness().provider,
        "delivery": DeliveryWorker(app_engine, sender, "https://app.example"),
    }
    assert asyncio.run(worker.briefings(ctx)) == 1
    assert asyncio.run(worker.detection(ctx)) == 1
    assert asyncio.run(worker.deliveries(ctx)) >= 0
    assert calls == ["briefings", "detection"]
    names = {c.name: c for c in worker.WorkerSettings.cron_jobs}
    assert set(names) == {"cron:briefings", "cron:detection", "cron:deliveries"}
    assert all(c.unique for c in names.values())
    assert names["cron:briefings"].minute == set(range(0, 60, 5))
    started: dict[str, Any] = {}
    asyncio.run(worker.startup(started))
    assert isinstance(started["delivery"], DeliveryWorker)
    asyncio.run(worker.shutdown(started))
