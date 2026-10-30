"""Alerts and their delivery (SPEC sections 4 and 6): severity, quiet hours, the daily budget,
deduplication, delivery records, and the worker's retries and failures."""

from datetime import UTC, date, datetime, time
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, text

from app.agent.llm import fake as f
from app.briefings.content import open_incidents
from app.briefings.models import BriefingKind
from app.briefings.service import generate
from app.channels.email import EmailError, RecordingSender
from app.db import tenant_transaction
from app.decisions.proposals import propose_for_incident
from app.decisions.store import get, propose
from app.delivery.alerts import OVER_BUDGET, QUIET, dispatch_alerts, plan, quiet_end
from app.delivery.queue import NO_EMAIL, NO_WHATSAPP, Subject, enqueue
from app.delivery.worker import DeliveryWorker
from app.detection import pipeline
from app.detection.models import AlertLevel, Candidate, EntityRef, FaultFamily
from app.facts.engine import FactEngine
from app.settings.models import AlertChannel, QuietHours, StoreSettings
from app.settings.repository import StoreSettingsRepository
from app.twin import fit_twin
from bench.scenarios.manifest import load_suite
from bench.simulator import register
from tests.action_helpers import Clock, option_set
from tests.conftest import create_store
from tests.llm_helpers import Harness

OWNER = "owner@example.com"
APP = "https://app.example"


def settings(**overrides: Any) -> StoreSettings:
    return StoreSettings(store_id=uuid4(), currency="USD", **overrides)


# --- the plan: pure rules --------------------------------------------------------------------


def test_critical_breaks_quiet_hours_and_the_budget() -> None:
    night = datetime(2026, 10, 30, 3, 0, tzinfo=UTC)  # 23:00 in New York
    s = settings(timezone="America/New_York", alert_budget_per_day=0)
    p = plan(AlertLevel.CRITICAL, now=night, settings=s, delivered_on=lambda _: 99)
    assert (p.status, p.deliver_at, p.reason) == ("sent", night, None)


def test_other_alerts_wait_for_the_end_of_quiet_hours() -> None:
    night = datetime(2026, 10, 30, 3, 0, tzinfo=UTC)  # 23:00 on the 29th in New York
    s = settings(timezone="America/New_York")
    p = plan(AlertLevel.HIGH, now=night, settings=s, delivered_on=lambda _: 0)
    assert (p.status, p.reason) == ("held", QUIET)
    assert p.deliver_at == datetime(2026, 10, 30, 11, 0, tzinfo=UTC)  # 07:00 EDT
    assert p.local_date == date(2026, 10, 30)
    day = datetime(2026, 10, 30, 15, 0, tzinfo=UTC)
    assert plan(AlertLevel.NORMAL, now=day, settings=s, delivered_on=lambda _: 0).status == "sent"


def test_the_budget_counts_the_day_of_delivery() -> None:
    s = settings(alert_budget_per_day=3)
    day = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    counts = {date(2026, 10, 30): 3, date(2026, 10, 31): 0}
    over = plan(AlertLevel.NORMAL, now=day, settings=s, delivered_on=counts.__getitem__)
    assert (over.status, over.reason) == ("deferred", OVER_BUDGET)
    late = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)  # quiet: tomorrow's budget applies
    held = plan(AlertLevel.DATA_QUALITY, now=late, settings=s, delivered_on=counts.__getitem__)
    assert (held.status, held.local_date) == ("held", date(2026, 10, 31))


def test_quiet_hours_across_midnight_and_a_clock_change() -> None:
    paris = ZoneInfo("Europe/Paris")
    quiet = QuietHours(start=time(21, 0), end=time(7, 0))
    before_dst_end = datetime(2026, 10, 24, 22, 0, tzinfo=paris)
    assert quiet_end(before_dst_end, quiet) == datetime(2026, 10, 25, 7, 0, tzinfo=paris)
    assert quiet_end(before_dst_end, quiet).utcoffset() != before_dst_end.utcoffset()
    early = datetime(2026, 10, 26, 6, 30, tzinfo=paris)
    assert quiet_end(early, quiet) == datetime(2026, 10, 26, 7, 0, tzinfo=paris)


# --- the store's channels --------------------------------------------------------------------


@pytest.mark.db
def test_channels_without_an_address(app_engine: Engine) -> None:
    store = create_store(app_engine)
    now = datetime.now(UTC)
    with tenant_transaction(app_engine, store) as conn:
        ids = enqueue(
            conn,
            store,
            Subject.BRIEFING,
            "b-1",
            channels=(AlertChannel.WEB, AlertChannel.EMAIL, AlertChannel.WHATSAPP),
            recipient=None,
            available_at=now,
            now=now,
        )
        again = enqueue(
            conn,
            store,
            Subject.BRIEFING,
            "b-1",
            channels=(AlertChannel.EMAIL,),
            recipient=OWNER,
            available_at=now,
            now=now,
        )
        rows = {
            r.channel: (r.status, r.last_error)
            for r in conn.execute(
                text("SELECT * FROM deliveries WHERE store_id = :s"), {"s": store}
            )
        }
    assert (len(ids), again) == (3, [])  # one delivery per message and channel
    assert rows == {
        "web": ("sent", None),
        "email": ("skipped", NO_EMAIL),
        "whatsapp": ("skipped", NO_WHATSAPP),
    }


# --- alerts on simulator stores --------------------------------------------------------------


def _store(engine: Engine, scenario_id: str, **overrides: Any) -> Any:
    manifest = next(m for m in load_suite("dev") if m.scenario_id == scenario_id)
    store = register(engine, manifest, 106)
    pipeline.run_pipeline(engine, store)
    with tenant_transaction(engine, store) as conn:
        repo = StoreSettingsRepository(conn)
        saved = repo.get_or_default(store).model_copy(
            update={"notification_email": OWNER, **overrides}
        )
        repo.save(saved, actor="test")
    return store


@pytest.fixture(scope="module")
def stockout(app_engine: Engine) -> Any:
    return _store(app_engine, "dev-stockout_on_promoted-04", timezone="America/New_York")


@pytest.fixture(scope="module")
def tracking(app_engine: Engine) -> Any:
    return _store(app_engine, "dev-tracking_break-02", alert_budget_per_day=0)


def data_end(engine: Engine, store: Any) -> date:
    with tenant_transaction(engine, store) as conn:
        last: date = conn.execute(
            text("SELECT max(ordered_at)::date + 1 FROM orders WHERE store_id = :s"),
            {"s": store},
        ).scalar_one()
    return last


def deliveries(engine: Engine, store: Any) -> list[Any]:
    with tenant_transaction(engine, store) as conn:
        return list(
            conn.execute(
                text("SELECT * FROM deliveries WHERE store_id = :s ORDER BY created_at, channel"),
                {"s": store},
            )
        )


@pytest.mark.db
def test_a_critical_alert_comes_with_its_decision(app_engine: Engine, stockout: Any) -> None:
    night = datetime.now(UTC).replace(hour=3, minute=0)  # 22:00 or 23:00 in New York
    [alert] = dispatch_alerts(app_engine, stockout, now=night)
    assert (alert.level, alert.status) == (AlertLevel.CRITICAL, "sent")
    assert alert.decision_id is not None
    with tenant_transaction(app_engine, stockout) as conn:
        decision = get(conn, stockout, alert.decision_id)
    assert (decision.source, decision.incident_id) == ("incident", alert.incident_id)
    rows = [r for r in deliveries(app_engine, stockout) if r.subject == "alert"]
    assert {(r.channel, r.status) for r in rows} == {("email", "pending"), ("web", "sent")}
    assert dispatch_alerts(app_engine, stockout, now=night) == []  # one alert per incident


@pytest.mark.db
def test_the_worker_sends_and_retries(app_engine: Engine, stockout: Any) -> None:
    sender = RecordingSender(failures=[EmailError("421 busy", retryable=True)])
    clock = Clock()
    worker = DeliveryWorker(app_engine, sender, APP, approval_secret="secret", clock=clock)
    assert worker.run_once() >= 1
    [row] = [r for r in deliveries(app_engine, stockout) if r.channel == "email"]
    assert (row.status, row.attempts, row.last_error) == ("pending", 1, "421 busy")
    assert worker.run_once() == 0  # backing off
    clock.advance(minutes=2)
    assert worker.run_once() >= 1
    [row] = [r for r in deliveries(app_engine, stockout) if r.channel == "email"]
    assert (row.status, row.attempts, row.provider) == ("sent", 2, "recording")
    assert row.provider_message_id.endswith("@recording>")
    [message] = [m for m in sender.sent if m.to == OWNER and "Critical alert" in m.subject]
    assert f"{APP}/approve#token=" in message.html
    assert "Approve: " in message.text
    assert "Data issue" not in message.html


@pytest.mark.db
def test_a_decision_proposed_by_the_owner_is_sent(app_engine: Engine, stockout: Any) -> None:
    with tenant_transaction(app_engine, stockout) as conn:
        campaign = conn.execute(
            text("SELECT id FROM ad_campaigns WHERE store_id = :s ORDER BY id LIMIT 1"),
            {"s": stockout},
        ).scalar_one()
        decision = propose(
            conn,
            FactEngine(conn, stockout),
            fit_twin(conn, stockout),
            option_set(campaign, change="-0.1", label="owner-email"),
            source="owner",
        )
    sender = RecordingSender()
    DeliveryWorker(app_engine, sender, APP, approval_secret="secret").run_once()
    [message] = [m for m in sender.sent if "decision is waiting" in m.subject]
    assert f"{APP}/decisions/{decision.decision_id}" in message.text
    assert f"{APP}/approve#token=" in message.text


@pytest.mark.db
def test_a_deferred_alert_goes_to_the_next_brief(app_engine: Engine, tracking: Any) -> None:
    [alert] = dispatch_alerts(app_engine, tracking)
    assert (alert.level, alert.status, alert.reason) == (
        AlertLevel.DATA_QUALITY,
        "deferred",
        OVER_BUDGET,
    )
    assert alert.decision_id is None  # data quality: fix the data, no decision
    assert [r for r in deliveries(app_engine, tracking) if r.subject == "alert"] == []
    brief = generate(
        app_engine,
        tracking,
        BriefingKind.DAILY,
        Harness([f.overloaded()], max_attempts=1).provider,
        local_today=data_end(app_engine, tracking),
    )
    assert alert.incident_id in brief.content.incident_ids
    with tenant_transaction(app_engine, tracking) as conn:
        status, briefing = conn.execute(
            text("SELECT status, briefing_id FROM alerts WHERE alert_id = :a"),
            {"a": alert.alert_id},
        ).one()
    assert (status, briefing) == ("briefed", brief.briefing_id)
    rows = [r for r in deliveries(app_engine, tracking) if r.subject == "briefing"]
    assert {(r.channel, r.status) for r in rows} == {("email", "pending"), ("web", "sent")}
    # A refused recipient fails the delivery at once, recorded.
    sender = RecordingSender(failures=[EmailError("550 no such user", retryable=False)])
    DeliveryWorker(app_engine, sender, APP).run_once()
    [row] = [r for r in deliveries(app_engine, tracking) if r.channel == "email"]
    assert (row.status, row.last_error) == ("failed", "550 no such user")


@pytest.mark.db
def test_a_message_whose_subject_is_gone_fails(app_engine: Engine, tracking: Any) -> None:
    now = datetime.now(UTC)
    with tenant_transaction(app_engine, tracking) as conn:
        [missing] = enqueue(
            conn,
            tracking,
            Subject.BRIEFING,
            str(uuid4()),
            channels=(AlertChannel.EMAIL,),
            recipient=OWNER,
            available_at=now,
            now=now,
        )
    DeliveryWorker(app_engine, RecordingSender(), APP).run_once()
    [row] = [r for r in deliveries(app_engine, tracking) if r.delivery_id == missing]
    assert row.status == "failed"
    assert "does not exist" in row.last_error


@pytest.mark.db
def test_one_decision_per_incident_and_none_to_only_watch(
    app_engine: Engine, stockout: Any
) -> None:
    now = datetime.now(UTC)
    with tenant_transaction(app_engine, stockout) as conn:
        [incident] = [i for i in open_incidents(conn, stockout) if i.alert is AlertLevel.CRITICAL]
        first = propose_for_incident(conn, stockout, incident, now=now)
        again = propose_for_incident(conn, stockout, incident, now=now)
        watch = incident.model_copy(
            update={
                "incident_id": "inc-only-watch",
                "candidates": (
                    Candidate(
                        family=FaultFamily.MIX_SHIFT,
                        entity=EntityRef.store(),
                        score=1.0,
                        evidence=(),
                    ),
                ),
            }
        )
        assert propose_for_incident(conn, stockout, watch, now=now) is None
        conn.rollback()
    assert first is not None
    assert again is not None
    assert again.decision_id == first.decision_id
