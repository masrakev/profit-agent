"""Outbox worker: claims queued actions and executes them safely (Task 4 B3, ADR 0017).

Per outbox row:

1. claim (one short transaction): `SELECT ... FOR UPDATE SKIP LOCKED` inside the store's tenant
   transaction (the stores with ready rows come from `outbox_ready_stores()`, ids only), the
   policy engine's verdict (audited), and a lease: the row stays pending but invisible until the
   lease ends, the action is marked executing, the decision moves to executing;
2. on the platform, outside any transaction: read the state before, the dry run, the change,
   the state after (it must match the target);
3. finish (one transaction): the action executed with its before and after states, the outbox
   row done, the audit entry, the decision executed when all its actions are.

If the worker dies between 2 and 3, the lease ends and the row is claimed again: the platform's
state already matches the target, so nothing is executed twice, and the audit is written then.
Retryable failures (timeouts, rate limits, 5xx) are retried with exponential backoff and jitter;
the rest, or the last attempt, fail the action and its decision, and are audited. Each provider
has a circuit breaker.
"""

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from app.agent.llm.errors import CircuitOpenError
from app.agent.llm.resilience import CircuitBreaker
from app.agent.tools.base import data_end
from app.db import tenant_transaction
from app.decisions.store import DecisionStatus, transition
from app.domain.audit import append_audit
from app.executor.adapters import Adapter, AdapterError, CampaignRef, CampaignState, Change
from app.policies.engine import ActionRequest, evaluate

MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=5)
BASE_DELAY_S = 30.0
MAX_DELAY_S = 3600.0


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Claimed:
    outbox_id: int
    attempts: int
    action_id: UUID
    decision_id: UUID
    kind: str
    campaign: CampaignRef
    provider: str
    params: dict[str, Any]
    key: str
    rollback_of: UUID | None
    synthetic: bool


@dataclass
class Executor:
    engine: Engine
    adapters: dict[str, Adapter]
    meta_links: dict[str, str] = field(default_factory=dict)  # our campaign id -> Meta id
    clock: Callable[[], datetime] = _now
    rng: random.Random = field(default_factory=lambda: random.Random(0))  # noqa: S311
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)
    # Test hook: called after the platform change, before the finish transaction.
    after_apply: Callable[[UUID], None] | None = None

    def breaker(self, provider: str) -> CircuitBreaker:
        return self.breakers.setdefault(provider, CircuitBreaker(name=f"executor-{provider}"))

    def run_once(self) -> int:
        """Process every ready row once; returns how many were processed."""
        with self.engine.connect() as conn:
            stores = list(
                conn.execute(
                    text("SELECT outbox_ready_stores(:at)"), {"at": self.clock()}
                ).scalars()
            )
        done = 0
        for store_id in stores:
            while (claimed := self._claim(store_id)) is not None:
                if claimed is not False:
                    self._execute(claimed)
                done += 1
        return done

    # --- 1. claim -------------------------------------------------------------------------

    def _claim(self, store_id: UUID) -> Claimed | Literal[False] | None:
        """The next ready row: claimed, refused by the policy (False), or none (None)."""
        now = self.clock()
        with tenant_transaction(self.engine, store_id) as conn:
            row = conn.execute(
                text(
                    "SELECT o.outbox_id, o.attempts, a.action_id, a.decision_id, a.kind, "
                    "a.campaign_id, a.provider, a.params, a.idempotency_key, a.rollback_of, "
                    "a.status AS action_status, d.status AS decision_status, c.external_id, "
                    "c.currency, s.synthetic FROM outbox o "
                    "JOIN actions a ON a.store_id = o.store_id AND a.action_id = o.action_id "
                    "JOIN decisions d ON d.store_id = a.store_id AND d.decision_id = a.decision_id "
                    "JOIN ad_campaigns c ON c.store_id = a.store_id AND c.id = a.campaign_id "
                    "JOIN stores s ON s.store_id = a.store_id "
                    "WHERE o.store_id = :s AND o.status = 'pending' AND o.available_at <= :now "
                    "ORDER BY o.outbox_id LIMIT 1 FOR UPDATE OF o SKIP LOCKED"
                ),
                {"s": store_id, "now": now},
            ).first()
            if row is None:
                return None
            params = dict(row.params)
            change = params.get("change")
            decision_ok = row.decision_status in ("approved", "executing", "executed", "measured")
            verdict = evaluate(
                conn,
                ActionRequest(
                    store_id=store_id,
                    kind=row.kind,
                    campaign_id=row.campaign_id,
                    approved=decision_ok,
                    change=Decimal(str(change)) if change is not None else None,
                    rollback_of=row.rollback_of,
                    action_id=row.action_id,
                ),
                now=now,
                actor="system:executor",
            )
            if not verdict.allowed:
                self._finish_failed(
                    conn, row, f"policy {verdict.rule.value}: {verdict.reason}", "blocked", now
                )
                return False
            conn.execute(
                text(
                    "UPDATE outbox SET attempts = attempts + 1, available_at = :lease "
                    "WHERE outbox_id = :o"
                ),
                {"lease": now + LEASE, "o": row.outbox_id},
            )
            conn.execute(
                text(
                    "UPDATE actions SET status = 'executing', attempts = attempts + 1 "
                    "WHERE store_id = :s AND action_id = :a"
                ),
                {"s": store_id, "a": row.action_id},
            )
            if row.decision_status == "approved" and row.rollback_of is None:
                transition(conn, store_id, row.decision_id, DecisionStatus.EXECUTING)
            external = self.meta_links.get(str(row.campaign_id), row.external_id)
            return Claimed(
                outbox_id=row.outbox_id,
                attempts=int(row.attempts) + 1,
                action_id=row.action_id,
                decision_id=row.decision_id,
                kind=row.kind,
                campaign=CampaignRef(store_id, row.campaign_id, external, row.currency.strip()),
                provider=row.provider,
                params=params,
                key=row.idempotency_key,
                rollback_of=row.rollback_of,
                synthetic=bool(row.synthetic),
            )

    # --- 2. execute -------------------------------------------------------------------------

    @staticmethod
    def target(kind: str, params: dict[str, Any], before: CampaignState) -> Change:
        if kind == "pause_campaign":
            return Change(status="PAUSED")
        if kind == "resume_campaign":
            return Change(status="ACTIVE")
        if params.get("daily_budget_minor") is not None:  # a rollback restores the budget
            return Change(daily_budget_minor=int(params["daily_budget_minor"]))
        if before.daily_budget_minor is None:
            raise AdapterError("the campaign has no daily budget to change", retryable=False)
        ratio = Decimal(1) + Decimal(str(params["change"]))
        return Change(
            daily_budget_minor=int((before.daily_budget_minor * ratio).to_integral_value())
        )

    def _execute(self, job: Claimed) -> None:
        adapter = self.adapters[job.provider]
        breaker = self.breaker(job.provider)
        try:
            breaker.before_call()
            before = adapter.read(job.campaign)
            change = self.target(job.kind, job.params, before)
            already = change.satisfied_by(before)
            if not already:
                adapter.validate(job.campaign, change)
                adapter.apply(job.campaign, change)
            after = adapter.read(job.campaign)
            if not change.satisfied_by(after):
                raise AdapterError("the platform's state does not match the change", retryable=True)
            if job.provider != "simulator" and job.synthetic and "simulator" in self.adapters:
                # A synthetic store linked to a sandbox campaign: the simulator mirrors the change
                # so the outcome can be measured.
                mirror = self.adapters["simulator"]
                if not change.satisfied_by(mirror.read(job.campaign)):
                    mirror.apply(job.campaign, change)
            breaker.record_success()
        except CircuitOpenError as exc:
            self._retry_or_fail(job, str(exc), retryable=True)
            return
        except AdapterError as exc:
            if exc.retryable:
                breaker.record_failure()
            self._retry_or_fail(job, str(exc), retryable=exc.retryable)
            return
        if self.after_apply is not None:
            self.after_apply(job.action_id)
        self._finish_executed(job, before, after, change, already)

    # --- 3. finish --------------------------------------------------------------------------

    def _finish_executed(
        self,
        job: Claimed,
        before: CampaignState,
        after: CampaignState,
        change: Change,
        already: bool,
    ) -> None:
        now = self.clock()
        store = job.campaign.store_id
        with tenant_transaction(self.engine, store) as conn:
            conn.execute(
                text(
                    "UPDATE actions SET status = 'executed', executed_at = :now, "
                    "last_error = NULL, before_state = CAST(:b AS jsonb), "
                    "after_state = CAST(:a AS jsonb) "
                    "WHERE store_id = :s AND action_id = :id"
                ),
                {
                    "now": now,
                    "b": json.dumps(before.__dict__),
                    # The first day without data: where the outcome window starts.
                    "a": json.dumps(
                        {**after.__dict__, "effective_date": data_end(conn, store).isoformat()}
                    ),
                    "s": store,
                    "id": job.action_id,
                },
            )
            conn.execute(
                text("UPDATE outbox SET status = 'done', processed_at = :now WHERE outbox_id = :o"),
                {"now": now, "o": job.outbox_id},
            )
            append_audit(
                conn,
                store,
                actor="system:executor",
                action="action.executed",
                payload={
                    "action_id": str(job.action_id),
                    "decision_id": str(job.decision_id),
                    "idempotency_key": job.key,
                    "provider": job.provider,
                    "kind": job.kind,
                    "campaign_id": str(job.campaign.campaign_id),
                    "before": before.__dict__,
                    "after": after.__dict__,
                    "target": change.__dict__,
                    "already_applied": already,
                    "attempt": job.attempts,
                    "rollback_of": str(job.rollback_of) if job.rollback_of else None,
                },
                occurred_at=now,
            )
            if job.rollback_of is None:
                left = conn.execute(
                    text(
                        "SELECT count(*) FROM actions WHERE store_id = :s AND decision_id = :d "
                        "AND rollback_of IS NULL AND status <> 'executed'"
                    ),
                    {"s": store, "d": job.decision_id},
                ).scalar_one()
                status = conn.execute(
                    text("SELECT status FROM decisions WHERE store_id = :s AND decision_id = :d"),
                    {"s": store, "d": job.decision_id},
                ).scalar_one()
                if left == 0 and status == "executing":
                    transition(conn, store, job.decision_id, DecisionStatus.EXECUTED)

    def _retry_or_fail(self, job: Claimed, error: str, *, retryable: bool) -> None:
        now = self.clock()
        store = job.campaign.store_id
        with tenant_transaction(self.engine, store) as conn:
            if retryable and job.attempts < MAX_ATTEMPTS:
                delay = min(BASE_DELAY_S * 2 ** (job.attempts - 1), MAX_DELAY_S)
                delay += self.rng.uniform(0, delay / 4)
                conn.execute(
                    text(
                        "UPDATE outbox SET available_at = :at, last_error = :e WHERE outbox_id = :o"
                    ),
                    {"at": now + timedelta(seconds=delay), "e": error[:500], "o": job.outbox_id},
                )
                conn.execute(
                    text(
                        "UPDATE actions SET status = 'pending', last_error = :e "
                        "WHERE store_id = :s AND action_id = :a"
                    ),
                    {"e": error[:500], "s": store, "a": job.action_id},
                )
                append_audit(
                    conn,
                    store,
                    actor="system:executor",
                    action="action.retry_scheduled",
                    payload={
                        "action_id": str(job.action_id),
                        "attempt": job.attempts,
                        "error": error[:500],
                        "retry_in_s": int(delay),
                    },
                    occurred_at=now,
                )
                return
            row = conn.execute(
                text(
                    "SELECT o.outbox_id, a.action_id, a.decision_id, a.rollback_of, d.status AS "
                    "decision_status FROM outbox o JOIN actions a ON a.store_id = o.store_id AND "
                    "a.action_id = o.action_id JOIN decisions d ON d.store_id = a.store_id AND "
                    "d.decision_id = a.decision_id WHERE o.outbox_id = :o"
                ),
                {"o": job.outbox_id},
            ).one()
            self._finish_failed(conn, row, error, "failed", now)

    def _finish_failed(
        self, conn: Connection, row: Any, error: str, status: str, now: datetime
    ) -> None:
        store = conn.execute(
            text("SELECT NULLIF(current_setting('app.store_id', true), '')")
        ).scalar()
        store_id = UUID(str(store))
        conn.execute(
            text(
                "UPDATE actions SET status = :st, last_error = :e WHERE store_id = :s "
                "AND action_id = :a"
            ),
            {"st": status, "e": error[:500], "s": store_id, "a": row.action_id},
        )
        conn.execute(
            text(
                "UPDATE outbox SET status = 'failed', processed_at = :now, last_error = :e "
                "WHERE outbox_id = :o"
            ),
            {"now": now, "e": error[:500], "o": row.outbox_id},
        )
        if row.rollback_of is None:
            if row.decision_status == "approved":
                transition(conn, store_id, row.decision_id, DecisionStatus.EXECUTING)
            if row.decision_status in ("approved", "executing"):
                transition(conn, store_id, row.decision_id, DecisionStatus.FAILED)
        append_audit(
            conn,
            store_id,
            actor="system:executor",
            action=f"action.{status}",
            payload={"action_id": str(row.action_id), "error": error[:500]},
            occurred_at=now,
        )


def request_rollback(
    conn: Connection,
    store_id: UUID,
    action_id: UUID,
    *,
    actor: str,
    now: datetime | None = None,
) -> UUID:
    """Queue the inverse of an executed action: pause <-> resume, budget restored to its value
    before the action. The owner's request is the approval; the policy still applies (kill
    switches, autonomy), except the one-change-per-day rule."""
    from app.decisions.store import enqueue

    now = now or _now()
    row = conn.execute(
        text(
            "SELECT decision_id, option_id, kind, campaign_id, provider, status, before_state, "
            "idempotency_key FROM actions WHERE store_id = :s AND action_id = :a FOR UPDATE"
        ),
        {"s": store_id, "a": action_id},
    ).first()
    if row is None:
        raise LookupError(f"action {action_id} does not exist or is not visible")
    if row.status != "executed":
        raise ValueError("only an executed action can be rolled back")
    inverse = {"pause_campaign": "resume_campaign", "resume_campaign": "pause_campaign"}.get(
        row.kind, "change_budget"
    )
    params: dict[str, Any] = {}
    if row.kind == "change_budget":
        params["daily_budget_minor"] = (row.before_state or {}).get("daily_budget_minor")
    new = enqueue(
        conn,
        store_id,
        row.decision_id,
        row.option_id,
        0,
        inverse,
        row.campaign_id,
        params,
        provider=row.provider,
        key=f"rollback:{row.idempotency_key}",
        now=now,
        rollback_of=action_id,
    )
    append_audit(
        conn,
        store_id,
        actor=actor,
        action="action.rollback_requested",
        payload={"action_id": str(action_id), "rollback_action_id": str(new), "kind": inverse},
        occurred_at=now,
    )
    return new
