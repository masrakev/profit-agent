"""The delivery worker: sends pending email and WhatsApp deliveries (ADRs 0019, 0027).

Per row, as the outbox worker does for actions (ADR 0017):

1. claim it in a short tenant transaction (`FOR UPDATE SKIP LOCKED`, a 5-minute lease) and
   render the message there: briefings and alerts are rendered as they are now (an alert whose
   decision was approved meanwhile shows it), approval links are created for decisions still
   proposed;
2. send it outside any transaction, behind the channel's circuit breaker: email by SMTP;
   WhatsApp to the store's verified number, as a session message while the owner's 24-hour
   window is open, else as the approved template (and as the template at once when the window
   closed between rendering and sending);
3. record the outcome: sent with the provider's message id, retried with exponential backoff
   and jitter (30 s doubling, 5 attempts) when the error is transient, or failed; audited.

One delivery row per message and channel (unique), so a message is never queued twice. A crash
between sending and recording leaves the row leased; when the lease ends it is sent again:
neither SMTP nor the Cloud API has a read-back, so delivery is at least once, not exactly once.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from app.agent.llm.errors import CircuitOpenError
from app.agent.llm.resilience import CircuitBreaker
from app.briefings import store as briefings
from app.briefings.notices import alert_document, decision_document, notice_context
from app.channels.email import EmailError, EmailMessage, EmailSender
from app.channels.messages import Links, Rendered, load_inputs, render_briefing, render_document
from app.channels.whatsapp import WhatsAppError, WhatsAppMessage, WhatsAppSender
from app.db import tenant_transaction
from app.decisions.store import DecisionStatus, Verdict, create_link, get
from app.delivery.queue import Subject
from app.detection.repository import load_incident
from app.domain.audit import append_audit
from app.whatsapp.formats import Formats
from app.whatsapp.numbers import verified_number

MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=5)
BASE_DELAY_S = 30.0
MAX_DELAY_S = 3600.0


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Claimed:
    store_id: UUID
    delivery_id: UUID
    subject: Subject
    subject_id: str
    recipient: str
    attempts: int
    message: Rendered | WhatsAppMessage
    channel: str = "email"
    session: bool = False  # WhatsApp: the owner's 24-hour window is open


class UnrenderableError(LookupError):
    """The message's subject no longer exists (it cannot be sent, ever)."""


@dataclass
class DeliveryWorker:
    engine: Engine
    sender: EmailSender
    app_base_url: str
    approval_secret: str | None = None
    clock: Callable[[], datetime] = _now
    rng: random.Random = field(default_factory=lambda: random.Random(0))  # noqa: S311
    breaker: CircuitBreaker = field(default_factory=lambda: CircuitBreaker(name="email"))
    whatsapp: WhatsAppSender | None = None  # without it, WhatsApp deliveries wait
    whatsapp_breaker: CircuitBreaker = field(
        default_factory=lambda: CircuitBreaker(name="whatsapp")
    )

    @property
    def channels(self) -> list[str]:
        return ["email", *(["whatsapp"] if self.whatsapp is not None else [])]

    def run_once(self) -> int:
        """Process every due delivery once; returns how many were processed."""
        with self.engine.connect() as conn:
            stores = list(
                conn.execute(
                    text("SELECT deliveries_ready_stores(:at)"), {"at": self.clock()}
                ).scalars()
            )
        done = 0
        for store_id in stores:
            while (claimed := self._claim(store_id)) is not None:
                if claimed is not False:
                    self._send(claimed)
                done += 1
        return done

    # --- 1. claim and render ------------------------------------------------------------------

    def _links(self, conn: Connection, store_id: UUID, now: datetime) -> Links:
        secret = self.approval_secret
        if secret is None:
            return Links(self.app_base_url)

        def token(decision_id: str, option_id: str) -> str | None:
            decision = get(conn, store_id, UUID(decision_id))
            if decision.status is not DecisionStatus.PROPOSED:
                return None
            return create_link(
                conn,
                store_id,
                decision.decision_id,
                option_id,
                Verdict.APPROVED,
                secret=secret,
                now=now,
            )

        return Links(self.app_base_url, approval_token=token)

    def _render(
        self, conn: Connection, store_id: UUID, subject: Subject, subject_id: str, now: datetime
    ) -> Rendered:
        links = self._links(conn, store_id, now)
        if subject is Subject.BRIEFING:
            record = briefings.get(conn, store_id, UUID(subject_id))
            if record is None:
                raise UnrenderableError(f"briefing {subject_id} does not exist")
            inputs = load_inputs(conn, store_id, record.content)
            return render_briefing(record.content, record.narration.narrative, inputs, links)
        if subject is Subject.ALERT:
            incident_id = conn.execute(
                text("SELECT incident_id FROM alerts WHERE store_id = :s AND alert_id = :a"),
                {"s": store_id, "a": UUID(subject_id)},
            ).scalar()
            stored = load_incident(conn, store_id, incident_id) if incident_id else None
            if stored is None:
                raise UnrenderableError(f"alert {subject_id} or its incident does not exist")
            document = alert_document(notice_context(conn, store_id, now), stored.incident)
            return render_document(document, load_inputs(conn, store_id, document), links)
        try:
            decision = get(conn, store_id, UUID(subject_id))
        except LookupError as exc:
            raise UnrenderableError(str(exc)) from exc
        if decision.status is DecisionStatus.SUPERSEDED:  # never ask about a decision that lost
            raise UnrenderableError(f"decision {subject_id} was superseded")
        document = decision_document(notice_context(conn, store_id, now), decision)
        return render_document(document, load_inputs(conn, store_id, document), links)

    def _render_whatsapp(
        self, conn: Connection, store_id: UUID, subject: Subject, subject_id: str, now: datetime
    ) -> tuple[WhatsAppMessage, str, bool]:
        """The message, the verified number it goes to, and whether the window is open."""
        number = verified_number(conn, store_id)
        if number is None:
            raise UnrenderableError("the store has no verified WhatsApp number any more")
        formats = Formats(self.app_base_url, self.approval_secret, now)
        message: WhatsAppMessage | None
        if subject is Subject.BRIEFING:
            record = briefings.get(conn, store_id, UUID(subject_id))
            if record is None:
                raise UnrenderableError(f"briefing {subject_id} does not exist")
            message = formats.brief(conn, store_id, record.content, record.briefing_id)
        elif subject is Subject.ALERT:
            incident_id = conn.execute(
                text("SELECT incident_id FROM alerts WHERE store_id = :s AND alert_id = :a"),
                {"s": store_id, "a": UUID(subject_id)},
            ).scalar()
            stored = load_incident(conn, store_id, incident_id) if incident_id else None
            if stored is None:
                raise UnrenderableError(f"alert {subject_id} or its incident does not exist")
            message = formats.alert(conn, store_id, stored.incident)
        elif subject is Subject.GOAL_PROGRESS:
            message = formats.goal(conn, store_id, UUID(subject_id.split(":", 1)[0]))
        else:  # a decision proposed, or its status
            try:
                decision = get(conn, store_id, UUID(subject_id.split(":", 1)[0]))
            except LookupError as exc:
                raise UnrenderableError(str(exc)) from exc
            if subject is Subject.DECISION and decision.status is DecisionStatus.SUPERSEDED:
                raise UnrenderableError(f"decision {subject_id} was superseded")
            message = formats.decision(conn, store_id, decision)
        if message is None:
            raise UnrenderableError(f"nothing to say yet about {subject.value} {subject_id}")
        return message, number.phone, number.window_open(now)

    def _claim(self, store_id: UUID) -> Claimed | Literal[False] | None:
        """The next due row: claimed, failed as unrenderable (False), or none (None)."""
        now = self.clock()
        with tenant_transaction(self.engine, store_id) as conn:
            row = conn.execute(
                text(
                    "SELECT delivery_id, subject, subject_id, channel, recipient, attempts "
                    "FROM deliveries WHERE store_id = :s AND status = 'pending' AND "
                    "channel = ANY(:channels) AND available_at <= :now "
                    "ORDER BY available_at, delivery_id FOR UPDATE SKIP LOCKED LIMIT 1"
                ),
                {"s": store_id, "now": now, "channels": self.channels},
            ).first()
            if row is None:
                return None
            conn.execute(
                text(
                    "UPDATE deliveries SET attempts = attempts + 1, available_at = :lease "
                    "WHERE store_id = :s AND delivery_id = :d"
                ),
                {"lease": now + LEASE, "s": store_id, "d": row.delivery_id},
            )
            subject = Subject(row.subject)
            recipient, session = row.recipient, False
            try:
                message: Rendered | WhatsAppMessage
                if row.channel == "whatsapp":
                    message, recipient, session = self._render_whatsapp(
                        conn, store_id, subject, row.subject_id, now
                    )
                else:
                    message = self._render(conn, store_id, subject, row.subject_id, now)
            except UnrenderableError as exc:
                self._fail(conn, store_id, row.delivery_id, str(exc), now)
                return False
        return Claimed(
            store_id=store_id,
            delivery_id=row.delivery_id,
            subject=subject,
            subject_id=row.subject_id,
            recipient=recipient,
            attempts=row.attempts + 1,
            message=message,
            channel=row.channel,
            session=session,
        )

    # --- 2. send, 3. record ------------------------------------------------------------------

    def _dispatch(self, job: Claimed) -> tuple[str, str]:
        """Send on the job's channel: (provider, the provider's message id)."""
        if isinstance(job.message, WhatsAppMessage):
            assert self.whatsapp is not None
            try:
                sent = self.whatsapp.send(job.recipient, job.message, session=job.session)
            except WhatsAppError as exc:
                if not (job.session and exc.window_closed):
                    raise
                sent = self.whatsapp.send(job.recipient, job.message, session=False)
            return self.whatsapp.provider, sent
        return self.sender.provider, self.sender.send(
            EmailMessage(
                to=job.recipient,
                subject=job.message.subject,
                text=job.message.text,
                html=job.message.html,
            )
        )

    def _send(self, job: Claimed) -> None:
        breaker = self.whatsapp_breaker if job.channel == "whatsapp" else self.breaker
        try:
            breaker.before_call()
            provider, message_id = self._dispatch(job)
        except CircuitOpenError as exc:
            self._retry_or_fail(job, str(exc), retryable=True)
            return
        except (EmailError, WhatsAppError) as exc:
            if exc.retryable:
                breaker.record_failure()
            self._retry_or_fail(job, str(exc), retryable=exc.retryable)
            return
        breaker.record_success()
        now = self.clock()
        with tenant_transaction(self.engine, job.store_id) as conn:
            conn.execute(
                text(
                    "UPDATE deliveries SET status = 'sent', provider = :p, "
                    "provider_message_id = :m, sent_at = :now, last_error = NULL "
                    "WHERE store_id = :s AND delivery_id = :d"
                ),
                {
                    "p": provider,
                    "m": message_id,
                    "now": now,
                    "s": job.store_id,
                    "d": job.delivery_id,
                },
            )
            append_audit(
                conn,
                job.store_id,
                actor="system:delivery",
                action="delivery.sent",
                payload={
                    "delivery_id": str(job.delivery_id),
                    "subject": job.subject.value,
                    "subject_id": job.subject_id,
                    "provider": provider,
                    "attempt": job.attempts,
                },
                occurred_at=now,
            )

    def _retry_or_fail(self, job: Claimed, error: str, *, retryable: bool) -> None:
        now = self.clock()
        with tenant_transaction(self.engine, job.store_id) as conn:
            if not retryable or job.attempts >= MAX_ATTEMPTS:
                self._fail(conn, job.store_id, job.delivery_id, error, now)
                return
            delay = min(BASE_DELAY_S * 2 ** (job.attempts - 1), MAX_DELAY_S)
            delay += self.rng.uniform(0, delay / 4)
            conn.execute(
                text(
                    "UPDATE deliveries SET available_at = :at, last_error = :e "
                    "WHERE store_id = :s AND delivery_id = :d"
                ),
                {
                    "at": now + timedelta(seconds=delay),
                    "e": error[:500],
                    "s": job.store_id,
                    "d": job.delivery_id,
                },
            )
            append_audit(
                conn,
                job.store_id,
                actor="system:delivery",
                action="delivery.retry_scheduled",
                payload={
                    "delivery_id": str(job.delivery_id),
                    "attempt": job.attempts,
                    "retry_in_s": int(delay),
                    "error": error[:300],
                },
                occurred_at=now,
            )

    @staticmethod
    def _fail(
        conn: Connection, store_id: UUID, delivery_id: UUID, error: str, now: datetime
    ) -> None:
        conn.execute(
            text(
                "UPDATE deliveries SET status = 'failed', last_error = :e "
                "WHERE store_id = :s AND delivery_id = :d"
            ),
            {"e": error[:500], "s": store_id, "d": delivery_id},
        )
        append_audit(
            conn,
            store_id,
            actor="system:delivery",
            action="delivery.failed",
            payload={"delivery_id": str(delivery_id), "error": error[:300]},
            occurred_at=now,
        )
