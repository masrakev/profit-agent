"""WhatsApp in the delivery pipeline (app/delivery): the same severity, quiet hours, budget,
retries, circuit breaker and delivery records as email; the verified number only; a session
message inside the 24-hour window, the template outside it."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from app.channels.email import RecordingSender
from app.channels.whatsapp import FakeWhatsApp, WhatsAppError
from app.db import tenant_transaction
from app.decisions.store import propose
from app.delivery.alerts import dispatch_alerts
from app.delivery.queue import NO_WHATSAPP, Subject, notify_whatsapp
from app.delivery.worker import DeliveryWorker
from app.detection.pipeline import run_pipeline
from app.facts.engine import FactEngine
from app.goals import service as goals
from app.settings.models import AlertChannel
from app.settings.repository import StoreSettingsRepository
from app.twin import fit_twin
from app.whatsapp import numbers
from bench.demo_seed import owner_option
from bench.generator.load import load
from bench.scenarios.manifest import load_suite

pytestmark = pytest.mark.db
SECRET = "test-signing-secret"
PHONE = "15557770001"
NOON = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)  # outside the default quiet hours (UTC store)


@pytest.fixture(scope="module")
def store(app_engine: Engine) -> UUID:
    manifest = next(m for m in load_suite("golden") if m.scenario_id == "golden-cpa_drift")
    data = manifest.generate()
    load(app_engine, data, manifest.config)
    store_id = data.store.store_id
    run_pipeline(app_engine, store_id)
    with tenant_transaction(app_engine, store_id) as conn:  # an owner's decision, proposed
        propose(
            conn,
            FactEngine(conn, store_id),
            fit_twin(conn, store_id),
            owner_option(data.campaigns[0].id, Decimal("-0.1")),
            source="owner",
            now=NOON,
        )
    return store_id


def a_decision(engine: Engine, store: UUID) -> UUID:
    with tenant_transaction(engine, store) as conn:
        found: UUID = conn.execute(
            text("SELECT decision_id FROM decisions WHERE store_id = :s LIMIT 1"), {"s": store}
        ).scalar_one()
    return found


def with_whatsapp(engine: Engine, store: UUID, *, verified: bool = True) -> None:
    with tenant_transaction(engine, store) as conn:
        repo = StoreSettingsRepository(conn)
        current = repo.get_or_default(store)
        repo.save(
            current.model_copy(
                update={
                    "alert_channels": (AlertChannel.WEB, AlertChannel.WHATSAPP),
                    "whatsapp_number": f"+{PHONE}",
                }
            ),
            actor="test",
        )
        found = numbers.state(conn, store)
        if verified and (found is None or not found.verified):
            _, code = numbers.start(conn, store, secret=SECRET, now=NOON)
            numbers.confirm(conn, store, code, secret=SECRET, actor="test", now=NOON)


def rows(engine: Engine, store: UUID, channel: str = "whatsapp") -> list[Any]:
    with tenant_transaction(engine, store) as conn:
        return list(
            conn.execute(
                text(
                    "SELECT * FROM deliveries WHERE store_id = :s AND channel = :c "
                    "ORDER BY created_at"
                ),
                {"s": store, "c": channel},
            )
        )


def worker(engine: Engine, fake: FakeWhatsApp, now: datetime = NOON) -> DeliveryWorker:
    return DeliveryWorker(
        engine,
        RecordingSender(),
        "https://app.example",
        approval_secret=SECRET,
        clock=lambda: now,
        whatsapp=fake,
    )


def test_the_alert_goes_to_the_verified_number_with_its_buttons(
    app_engine: Engine, store: UUID
) -> None:
    with_whatsapp(app_engine, store)
    alerts = dispatch_alerts(app_engine, store, now=NOON)
    assert alerts
    pending = rows(app_engine, store)
    assert [(r.status, r.recipient) for r in pending] == [("pending", PHONE)] * len(alerts)
    fake = FakeWhatsApp()
    assert worker(app_engine, fake).run_once() == len(alerts)
    to, message, session = fake.sent[0]
    assert (to, session) == (PHONE, False)  # never written: the template
    assert message.template in ("profit_alert", "data_alert")
    sent = rows(app_engine, store)[0]
    assert (sent.status, sent.provider, sent.provider_message_id) == (
        "sent",
        "whatsapp:fake",
        "wamid.fake1",
    )
    with tenant_transaction(app_engine, store) as conn:
        audited = conn.execute(
            text(
                "SELECT count(*) FROM audit_log WHERE store_id = :s AND action = 'delivery.sent' "
                "AND payload->>'provider' = 'whatsapp:fake'"
            ),
            {"s": store},
        ).scalar_one()
    assert audited == len(alerts)


def test_inside_the_window_a_session_message_and_its_fallback(
    app_engine: Engine, store: UUID
) -> None:
    with tenant_transaction(app_engine, store) as conn:
        numbers.touch_inbound(conn, store, NOON)  # the owner wrote at noon
        decision = a_decision(app_engine, store)
        notify_whatsapp(conn, store, Subject.DECISION_STATUS, f"{decision}:executed", now=NOON)
        notify_whatsapp(conn, store, Subject.DECISION_STATUS, f"{decision}:failed", now=NOON)
    fake = FakeWhatsApp()
    fake.failures.append(WhatsAppError("re-engagement", retryable=False, code=131047))
    assert worker(app_engine, fake, NOON + timedelta(hours=1)).run_once() == 2
    sessions = [session for _, _, session in fake.sent]
    assert sessions == [False, True]  # the window closed meanwhile: the template at once
    later = NOON + timedelta(hours=25)  # past the 24 hours
    with tenant_transaction(app_engine, store) as conn:
        assert numbers.state(conn, store).window_open(later) is False  # type: ignore[union-attr]


def test_failures_are_retried_with_backoff_then_failed(app_engine: Engine, store: UUID) -> None:
    with tenant_transaction(app_engine, store) as conn:
        decision = a_decision(app_engine, store)
        notify_whatsapp(conn, store, Subject.DECISION_STATUS, f"{decision}:retry", now=NOON)
    fake = FakeWhatsApp(failures=[WhatsAppError("throughput", retryable=True, code=130429)])
    w = worker(app_engine, fake)
    w.run_once()
    row = next(r for r in rows(app_engine, store) if r.subject_id.endswith(":retry"))
    assert (row.status, row.attempts) == ("pending", 1)
    assert row.available_at > NOON + timedelta(seconds=29)  # backoff
    assert "throughput" in row.last_error
    fake.failures.append(WhatsAppError("not a WhatsApp number", retryable=False, code=131026))
    worker(app_engine, fake, NOON + timedelta(hours=2)).run_once()
    row = next(r for r in rows(app_engine, store) if r.subject_id.endswith(":retry"))
    assert row.status == "failed"


def test_the_whatsapp_circuit_is_its_own(app_engine: Engine, store: UUID) -> None:
    with tenant_transaction(app_engine, store) as conn:
        decision = a_decision(app_engine, store)
        notify_whatsapp(conn, store, Subject.DECISION_STATUS, f"{decision}:breaker", now=NOON)
    w = worker(app_engine, FakeWhatsApp())
    w.whatsapp_breaker.failure_threshold = 1
    w.whatsapp_breaker.record_failure()
    w.run_once()
    row = next(r for r in rows(app_engine, store) if r.subject_id.endswith(":breaker"))
    assert (row.status, "circuit whatsapp is open" in row.last_error) == ("pending", True)
    assert w.breaker.state.value == "closed"  # email is not affected


def test_without_a_verified_number_nothing_is_sent(app_engine: Engine, store: UUID) -> None:
    with tenant_transaction(app_engine, store) as conn:
        decision = a_decision(app_engine, store)
        notify_whatsapp(conn, store, Subject.DECISION_STATUS, f"{decision}:unverified", now=NOON)
        numbers.sync_number(conn, store, "+15557770002")  # changed: no longer verified
        notify_whatsapp(conn, store, Subject.DECISION_STATUS, f"{decision}:skipped", now=NOON)
    worker(app_engine, FakeWhatsApp()).run_once()
    by_id = {r.subject_id.split(":")[1]: r for r in rows(app_engine, store) if ":" in r.subject_id}
    assert (by_id["skipped"].status, by_id["skipped"].last_error) == ("skipped", NO_WHATSAPP)
    assert by_id["unverified"].status == "failed"  # queued while verified, sent to nobody
    with tenant_transaction(app_engine, store) as conn:
        repo = StoreSettingsRepository(conn)
        settings = repo.get_or_default(store)
        repo.save(settings.model_copy(update={"alert_channels": (AlertChannel.WEB,)}), actor="t")
        assert notify_whatsapp(conn, store, Subject.GOAL_PROGRESS, "x:y", now=NOON) == []


def test_a_worker_without_whatsapp_leaves_its_deliveries_waiting(
    app_engine: Engine, store: UUID
) -> None:
    with_whatsapp(app_engine, store)
    with tenant_transaction(app_engine, store) as conn:
        decision = a_decision(app_engine, store)
        notify_whatsapp(conn, store, Subject.DECISION_STATUS, f"{decision}:waiting", now=NOON)
    DeliveryWorker(
        app_engine, RecordingSender(), "https://app.example", clock=lambda: NOON
    ).run_once()
    row = next(r for r in rows(app_engine, store) if r.subject_id.endswith(":waiting"))
    assert (row.status, row.attempts) == ("pending", 0)


def test_what_cannot_be_said_fails_once(app_engine: Engine, store: UUID) -> None:
    with_whatsapp(app_engine, store)
    with tenant_transaction(app_engine, store) as conn:
        today = goals.data_end(conn, store)
        goal = goals.create(
            conn, store, "net_profit", Decimal(1000), today + timedelta(days=30), now=NOON
        )
        cases = [
            (Subject.BRIEFING, str(uuid4())),  # no such briefing
            (Subject.ALERT, str(uuid4())),  # no such alert
            (Subject.GOAL_PROGRESS, f"{goal.goal_id}:{today}"),  # nothing tracked yet
            (Subject.DECISION, str(uuid4())),  # no such decision
            (Subject.DECISION_STATUS, f"{uuid4()}:executed"),  # no such decision
        ]
        for subject, subject_id in cases:
            notify_whatsapp(conn, store, subject, subject_id, now=NOON)
    worker(app_engine, FakeWhatsApp()).run_once()
    states = {r.subject_id: r.status for r in rows(app_engine, store)}
    assert [states[subject_id] for _, subject_id in cases] == ["failed"] * len(cases)
