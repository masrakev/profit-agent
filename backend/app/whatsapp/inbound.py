"""Inbound WhatsApp messages, processed by a job after the webhook stored them (ADR 0027).

1. The sender is looked up among verified numbers (`whatsapp_store_for`). Any other sender gets
   one polite refusal, the first time only, and nothing else: only an HMAC of its number is kept.
2. The owner wrote: the 24-hour window opens, and the store is now known.
3. By kind:
   - a text is a question or a goal, never an approval: it goes to Ask exactly as typed on the
     web; a goal is restated with a "Confirm goal" button;
   - a voice note is downloaded (size capped), converted to WAV, transcribed and asked like a
     text (app.voice); the audio is never stored, only its transcript, duration and cost;
   - a button is checked as ours and this store's (app.whatsapp.buttons). "Approve" goes through
     the email links' own rules: the link is single use and 24 hours, an option beyond the
     spending caps is never decided from WhatsApp (a link to the web confirmation page instead),
     and the decision is decided once (`decide`, channel `whatsapp`); the executor then applies
     the policy engine as for any approval. "Confirm goal" confirms the goal (no money moves)
     and explains its feasibility. "See options" only replies;
   - anything else gets the help text.
4. The message's content and the sender's number are cleared once it is processed; a failure is
   retried twice by the sweep, then the owner gets an apology.
"""

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from app.agent.ask import ask, explain_goal
from app.agent.llm.provider import LLMProvider
from app.agent.llm.resilience import CircuitBreaker
from app.agent.llm.transcribe import Transcriber
from app.channels.whatsapp import WhatsAppError, WhatsAppMessage, WhatsAppSender
from app.db import tenant_transaction
from app.decisions.store import (
    Channel,
    DecisionError,
    Verdict,
    consume_link,
    decide,
    get,
    link_available,
)
from app.goals import service as goals
from app.observability import get_logger
from app.policies.engine import exceeds_caps
from app.voice.audio import MAX_BYTES, ClipRejected
from app.voice.convert import Converter, prepare_clip
from app.voice.service import answer_transcript, transcribe_question
from app.whatsapp import numbers
from app.whatsapp.buttons import ButtonError, approval_claims, consume_goal_link, parse
from app.whatsapp.formats import Formats, help_message, refusal_message

LEASE = timedelta(minutes=5)
MAX_ATTEMPTS = 3
SWEEP_AFTER = timedelta(minutes=1)  # a message the queue missed is picked up by the sweep
NOTHING_HEARD = "I heard nothing in your voice note: try again, a little closer."
APOLOGY = "Sorry, I could not answer that. Try again in a moment, or open Profit Agent."


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Row:
    message_id: str
    phone: str
    kind: str
    content: dict[str, Any]
    attempts: int


@dataclass
class Inbox:
    engine: Engine
    sender: WhatsAppSender
    provider: LLMProvider
    transcriber: Transcriber
    converter: Converter | None
    app_base_url: str
    approval_secret: str | None  # signs buttons; without it no button decides
    refusal_key: str  # keys the HMAC of refused numbers
    meta_links: dict[str, str] = field(default_factory=dict)
    clock: Callable[[], datetime] = _now
    breaker: CircuitBreaker = field(default_factory=lambda: CircuitBreaker(name="whatsapp-reply"))

    # --- the queue -------------------------------------------------------------------------

    def pending(self) -> list[str]:
        """Messages still pending a minute after they arrived (the sweep's work)."""
        with self.engine.connect() as conn:
            return list(
                conn.execute(
                    text(
                        "SELECT message_id FROM whatsapp.inbound WHERE status = 'pending' AND "
                        "received_at < :before AND (leased_until IS NULL OR leased_until < :now) "
                        "ORDER BY received_at LIMIT 100"
                    ),
                    {"before": self.clock() - SWEEP_AFTER, "now": self.clock()},
                ).scalars()
            )

    def _claim(self, message_id: str) -> Row | None:
        now = self.clock()
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    "UPDATE whatsapp.inbound SET attempts = attempts + 1, leased_until = :lease "
                    "WHERE message_id = :m AND status = 'pending' "
                    "AND (leased_until IS NULL OR leased_until < :now) "
                    "RETURNING message_id, phone, kind, content, attempts"
                ),
                {"m": message_id, "now": now, "lease": now + LEASE},
            ).first()
        return None if row is None else Row(*row)

    def _finish(self, row: Row, status: str, outcome: str, store_id: UUID | None) -> None:
        final = status != "pending"
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE whatsapp.inbound SET status = :st, outcome = :o, store_id = :s, "
                    "leased_until = NULL, processed_at = :now, "
                    "content = CASE WHEN :final THEN '{}'::jsonb ELSE content END, "
                    "phone = CASE WHEN :final THEN '' ELSE phone END "
                    "WHERE message_id = :m"
                ),
                {
                    "st": status,
                    "o": outcome[:200],
                    "s": store_id,
                    "now": self.clock(),
                    "final": final,
                    "m": row.message_id,
                },
            )

    def process(self, message_id: str) -> str | None:
        """Process one stored message; its outcome, or None when it is not ours to process."""
        row = self._claim(message_id)
        if row is None:
            return None
        log = get_logger(__name__)
        store_id = numbers.store_for(self.engine, row.phone)
        try:
            if store_id is None:
                outcome = self._refuse(row.phone)
                self._finish(row, "refused", outcome, None)
                return outcome
            with tenant_transaction(self.engine, store_id) as conn:
                numbers.touch_inbound(conn, store_id, self.clock())
            outcome = self._handle(store_id, row)
        except Exception as exc:  # retried by the sweep, then an apology
            log.warning("whatsapp.inbound_failed", error=type(exc).__name__, kind=row.kind)
            if row.attempts < MAX_ATTEMPTS:
                self._finish(row, "pending", f"retry: {type(exc).__name__}", store_id)
                return "retry"
            self._reply(row.phone, WhatsAppMessage(text=APOLOGY))
            self._finish(row, "failed", type(exc).__name__, store_id)
            return "failed"
        self._finish(row, "done", outcome, store_id)
        log.info("whatsapp.inbound", kind=row.kind, outcome=outcome)
        return outcome

    # --- replies ----------------------------------------------------------------------------

    def _reply(self, phone: str, message: WhatsAppMessage) -> bool:
        """A session reply (the sender just wrote); one retry when worth it."""
        for attempt in (1, 2):
            try:
                self.breaker.before_call()
                self.sender.send(phone, message, session=True)
            except WhatsAppError as exc:
                if exc.retryable:
                    self.breaker.record_failure()
                if exc.retryable and attempt == 1:
                    continue
                get_logger(__name__).warning("whatsapp.reply_failed", error=str(exc)[:200])
                return False
            except Exception as exc:  # the circuit is open
                get_logger(__name__).warning("whatsapp.reply_failed", error=type(exc).__name__)
                return False
            self.breaker.record_success()
            return True
        return False

    def _refuse(self, phone: str) -> str:
        digest = hmac.new(self.refusal_key.encode(), phone.encode(), hashlib.sha256).digest()
        with self.engine.begin() as conn:
            first = conn.execute(
                text(
                    "INSERT INTO whatsapp.refusals (phone_hash, refused_at) VALUES (:h, :now) "
                    "ON CONFLICT (phone_hash) DO NOTHING RETURNING phone_hash"
                ),
                {"h": digest, "now": self.clock()},
            ).scalar()
        if first is None:
            return "refused: again, silent"
        self._reply(phone, refusal_message())
        return "refused"

    # --- by kind ----------------------------------------------------------------------------

    def _formats(self) -> Formats:
        return Formats(self.app_base_url, self.approval_secret, self.clock())

    def _handle(self, store_id: UUID, row: Row) -> str:
        if row.kind == "text" and str(row.content.get("body", "")).strip():
            return self._ask(store_id, row.phone, str(row.content["body"]))
        if row.kind == "audio":
            return self._voice(store_id, row.phone, str(row.content.get("media_id", "")))
        if row.kind == "button":
            return self._button(store_id, row.phone, str(row.content.get("id", "")))
        self._reply(row.phone, help_message())
        return "help"

    def _ask(self, store_id: UUID, phone: str, question: str) -> str:
        result = ask(self.engine, store_id, question, self.provider)
        with tenant_transaction(self.engine, store_id) as conn:
            message = self._formats().answer(conn, store_id, result)
        self._reply(phone, message)
        return f"asked: {result.status}"

    def _voice(self, store_id: UUID, phone: str, media_id: str) -> str:
        try:
            recording = self.sender.download(media_id, max_bytes=MAX_BYTES)
            wav, _ = prepare_clip(recording, self.converter)
            del recording  # only the transcript is kept
            heard = transcribe_question(
                self.engine, store_id, wav, self.transcriber, channel="whatsapp"
            )
        except ClipRejected as exc:
            self._reply(phone, WhatsAppMessage(text=f"I could not use that voice note: {exc}."))
            return f"voice refused: {exc.code}"
        except WhatsAppError as exc:
            if exc.retryable:
                raise
            self._reply(
                phone, WhatsAppMessage(text="I could not get that voice note: send it again.")
            )
            return f"voice not downloaded: {exc.code}"
        if not heard.heard:
            self._reply(phone, WhatsAppMessage(text=NOTHING_HEARD))
            return "voice: no speech"
        result = answer_transcript(self.engine, store_id, heard, self.provider)
        assert result is not None
        with tenant_transaction(self.engine, store_id) as conn:
            message = self._formats().answer(conn, store_id, result, heard=heard.transcript)
        self._reply(phone, message)
        return f"voice asked: {result.status}"

    def _button(self, store_id: UUID, phone: str, button_id: str) -> str:
        formats = self._formats()
        if self.approval_secret is None:
            self._reply(phone, formats.stale_button())
            return "button: no secret"
        try:
            button = parse(button_id, store_id, secret=self.approval_secret)
        except ButtonError:
            self._reply(phone, formats.stale_button())
            return "button: not ours"
        if button.kind == "o":
            with tenant_transaction(self.engine, store_id) as conn:
                try:
                    decision = get(conn, store_id, button.ref)
                except LookupError:
                    message = formats.stale_button()
                else:
                    message = formats.options(conn, store_id, decision)
            self._reply(phone, message)
            return "button: options"
        if button.kind == "g":
            return self._confirm_goal(store_id, phone, button.ref)
        return self._approve(store_id, phone, button.ref)

    def _approve(self, store_id: UUID, phone: str, link_id: UUID) -> str:
        formats, now = self._formats(), self.clock()
        with tenant_transaction(self.engine, store_id) as conn:
            claims = approval_claims(conn, store_id, link_id)
            if claims is None or not link_available(conn, claims, now):
                message = formats.stale_button(claims.decision_id if claims else None)
                outcome = "button: stale"
            else:
                decision = get(conn, store_id, claims.decision_id)
                option = decision.option(claims.option_id)
                if claims.verdict is Verdict.APPROVED and exceeds_caps(
                    conn, store_id, option.actions
                ):  # never decided from here: the web, after a confirmation
                    message = formats.above_caps(claims.decision_id)
                    outcome = "button: above the caps"
                else:
                    try:
                        with conn.begin_nested():
                            consume_link(conn, claims, now)
                            decided = decide(
                                conn,
                                store_id,
                                claims.decision_id,
                                claims.option_id if claims.verdict is Verdict.APPROVED else None,
                                claims.verdict,
                                channel=Channel.WHATSAPP,
                                actor=f"owner:whatsapp:{phone[-4:]}",
                                now=now,
                                meta_links=self.meta_links,
                            )
                        message = formats.decision(conn, store_id, decided)
                        outcome = f"button: {decided.status.value}"
                    except DecisionError as exc:  # used, decided elsewhere, expired, superseded
                        current = get(conn, store_id, claims.decision_id)
                        message = formats.decision(conn, store_id, current)
                        outcome = f"button: {exc.code}"
        self._reply(phone, message)
        return outcome

    def _confirm_goal(self, store_id: UUID, phone: str, link_id: UUID) -> str:
        formats, now = self._formats(), self.clock()
        with tenant_transaction(self.engine, store_id) as conn:
            link = consume_goal_link(conn, store_id, link_id, now)
            if link is not None:
                goals.confirm(conn, store_id, link.goal_id, now=now)
        if link is None:
            self._reply(phone, formats.stale_button())
            return "goal button: stale"
        explained = explain_goal(
            self.engine, store_id, link.goal_id, self.provider, what="feasibility"
        )
        with tenant_transaction(self.engine, store_id) as conn:
            message = formats.goal_confirmed(conn, store_id, explained)
        self._reply(phone, message)
        return f"goal confirmed: {explained.status}"
