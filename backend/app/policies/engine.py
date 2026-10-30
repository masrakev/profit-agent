"""Policy engine: every action is evaluated before it executes (Task 4 B2, ADR 0016).

Rules, in order; the first that refuses decides, and every evaluation is written to the audit
log with that rule and the policy version:

1. global kill switch (control.global_switches, name "actions");
2. the store's kill switch (store_controls);
3. executable action: only pause, resume and daily-budget changes execute (others are prepared);
4. autonomy for the action type (store settings): observe refuses; recommend needs an approved
   decision; execute-capped and above may run without one, inside the caps;
5. budget cap: a budget change at most +-30% (store setting) of the current budget;
6. change frequency: at most one change per campaign per 24 hours (store setting); a rollback
   (restoring the state before an action) is exempt, so an owner can always undo;
7. reversibility: only actions with a known inverse (pause <-> resume, budget restored).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Connection, text

from app.domain.audit import append_audit
from app.settings.models import ActionType, AutonomyLevel
from app.settings.repository import StoreSettingsRepository

POLICY_VERSION = 1
GLOBAL_SWITCH = "actions"
ACTION_TYPES = {
    "pause_campaign": ActionType.PAUSE_CAMPAIGN,
    "resume_campaign": ActionType.RESUME_CAMPAIGN,
    "change_budget": ActionType.CHANGE_BUDGET,
}
INVERSES = {
    "pause_campaign": "resume_campaign",
    "resume_campaign": "pause_campaign",
    "change_budget": "change_budget",
}


class Rule(StrEnum):
    GLOBAL_KILL_SWITCH = "global_kill_switch"
    STORE_KILL_SWITCH = "store_kill_switch"
    EXECUTABLE_ACTION = "executable_action"
    AUTONOMY = "autonomy"
    APPROVAL = "approval"
    BUDGET_CAP = "budget_cap"
    CHANGE_FREQUENCY = "change_frequency"
    REVERSIBILITY = "reversibility"
    ALLOWED = "allowed"


@dataclass(frozen=True)
class ActionRequest:
    store_id: UUID
    kind: str
    campaign_id: UUID
    approved: bool  # the action belongs to an approved decision
    change: Decimal | None = None  # budget changes: relative to the current budget
    rollback_of: UUID | None = None
    action_id: UUID | None = None  # None for a preview


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    rule: Rule
    reason: str
    version: int = POLICY_VERSION


def global_switch_on(conn: Connection) -> bool:
    return bool(
        conn.execute(
            text("SELECT enabled FROM control.global_switches WHERE name = :n"),
            {"n": GLOBAL_SWITCH},
        ).scalar()
    )


def store_switch_on(conn: Connection, store_id: UUID) -> bool:
    return bool(
        conn.execute(
            text("SELECT kill_switch FROM store_controls WHERE store_id = :s"), {"s": store_id}
        ).scalar()
    )


def set_store_switch(
    conn: Connection, store_id: UUID, enabled: bool, *, actor: str, reason: str | None = None
) -> None:
    conn.execute(
        text(
            "INSERT INTO store_controls (store_id, kill_switch, reason, updated_by) VALUES "
            "(:s, :on, :reason, :actor) ON CONFLICT (store_id) DO UPDATE SET kill_switch = :on, "
            "reason = :reason, updated_by = :actor, updated_at = now()"
        ),
        {"s": store_id, "on": enabled, "reason": reason, "actor": actor},
    )
    append_audit(
        conn,
        store_id,
        actor=actor,
        action="control.store_kill_switch",
        payload={"enabled": enabled, "reason": reason},
    )


def set_global_switch(
    owner_conn: Connection, enabled: bool, *, actor: str, reason: str | None = None
) -> None:
    """Admin only: the application role can read the switch, never write it."""
    owner_conn.execute(
        text(
            "INSERT INTO control.global_switches (name, enabled, reason, updated_by) VALUES "
            "(:n, :on, :reason, :actor) ON CONFLICT (name) DO UPDATE SET enabled = :on, "
            "reason = :reason, updated_by = :actor, updated_at = now()"
        ),
        {"n": GLOBAL_SWITCH, "on": enabled, "reason": reason, "actor": actor},
    )


def _recent_changes(conn: Connection, request: ActionRequest, now: datetime) -> int:
    return int(
        conn.execute(
            text(
                "SELECT count(*) FROM actions WHERE store_id = :s AND campaign_id = :c "
                "AND status = 'executed' AND executed_at > :since"
            ),
            {"s": request.store_id, "c": request.campaign_id, "since": now - timedelta(hours=24)},
        ).scalar_one()
    )


def _decide(conn: Connection, request: ActionRequest, now: datetime) -> PolicyResult:
    if global_switch_on(conn):
        return PolicyResult(False, Rule.GLOBAL_KILL_SWITCH, "all actions are stopped")
    if store_switch_on(conn, request.store_id):
        return PolicyResult(False, Rule.STORE_KILL_SWITCH, "actions are stopped for this store")
    action_type = ACTION_TYPES.get(request.kind)
    if action_type is None:
        return PolicyResult(False, Rule.EXECUTABLE_ACTION, f"{request.kind} is prepared, not run")
    settings = StoreSettingsRepository(conn).get_or_default(request.store_id)
    level = settings.autonomy[action_type]
    if level is AutonomyLevel.OBSERVE:
        return PolicyResult(False, Rule.AUTONOMY, f"{action_type.value} is set to observe only")
    if level is AutonomyLevel.RECOMMEND and not request.approved:
        return PolicyResult(False, Rule.APPROVAL, "the owner has not approved this action")
    caps = settings.spending_caps
    out_of_cap = request.change is None or abs(request.change) > caps.max_budget_change_ratio
    if request.kind == "change_budget" and out_of_cap:
        return PolicyResult(
            False,
            Rule.BUDGET_CAP,
            f"a budget change beyond {caps.max_budget_change_ratio} of the current budget",
        )
    if request.rollback_of is None:
        limit = caps.max_budget_changes_per_campaign_per_day
        if _recent_changes(conn, request, now) >= limit:
            return PolicyResult(
                False, Rule.CHANGE_FREQUENCY, f"at most {limit} change per campaign per 24 hours"
            )
    if request.kind not in INVERSES:
        return PolicyResult(False, Rule.REVERSIBILITY, "no known way to undo it")
    return PolicyResult(True, Rule.ALLOWED, "every rule passed")


def evaluate(
    conn: Connection, request: ActionRequest, *, now: datetime, actor: str = "system:policy"
) -> PolicyResult:
    """Evaluate and audit (previews included: the audit says which)."""
    result = _decide(conn, request, now)
    append_audit(
        conn,
        request.store_id,
        actor=actor,
        action="policy.evaluated",
        payload={
            "policy_version": result.version,
            "action_id": str(request.action_id) if request.action_id else None,
            "preview": request.action_id is None,
            "kind": request.kind,
            "campaign_id": str(request.campaign_id),
            "change": str(request.change) if request.change is not None else None,
            "rollback_of": str(request.rollback_of) if request.rollback_of else None,
            "allowed": result.allowed,
            "rule": result.rule.value,
            "reason": result.reason,
        },
        occurred_at=now,
    )
    return result


def exceeds_caps(conn: Connection, store_id: UUID, actions: list[dict[str, object]]) -> bool:
    """Whether an option's budget changes go beyond the store's per-action cap."""
    cap = StoreSettingsRepository(conn).get_or_default(store_id).spending_caps
    return any(
        a.get("kind") == "change_budget"
        and abs(Decimal(str(a.get("change") or 0))) > cap.max_budget_change_ratio
        for a in actions
    )
