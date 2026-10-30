"""From incidents to alerts (SPEC section 6): severity, quiet hours, the daily budget and
deduplication, decided by code after each detection run.

- An incident alerts once per level: the same incident at the same or a lower level again is
  not a new alert; an escalation (normal to high, high to critical) is.
- `critical` is delivered at once, even in quiet hours, and is outside the budget.
- Other alerts (high, normal, data quality) are held until quiet hours end, and count against
  the store's daily alert budget on the day they are delivered; over the budget an alert is
  deferred: the next daily brief shows it (its top items are the open incidents).
- A profitability alert comes with a decision: the cause's options simulated by the twin.
- Data quality stays its own category: its message says it is not a profit problem.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, text

from app.briefings.content import open_incidents
from app.db import tenant_transaction
from app.decisions.proposals import propose_for_incident
from app.delivery.queue import Subject, notify
from app.detection.models import ALERT_RANK, AlertLevel, Incident
from app.domain.audit import append_audit
from app.settings.models import QuietHours, StoreSettings
from app.settings.repository import StoreSettingsRepository

OVER_BUDGET = "over the daily alert budget: shown in the next briefing"
QUIET = "quiet hours: delivered when they end"


@dataclass(frozen=True)
class Plan:
    status: str  # sent | held | deferred
    deliver_at: datetime  # UTC
    local_date: date  # the store-local day it is delivered (or deferred) on
    reason: str | None


def quiet_end(local: datetime, quiet: QuietHours) -> datetime:
    """The next end of quiet hours after `local` (store-local, aware)."""
    tz = local.tzinfo
    end = datetime.combine(local.date(), quiet.end, tzinfo=tz)
    return (
        end
        if end > local
        else datetime.combine(local.date() + timedelta(days=1), quiet.end, tzinfo=tz)
    )


def plan(
    level: AlertLevel,
    *,
    now: datetime,
    settings: StoreSettings,
    delivered_on: Callable[[date], int],
) -> Plan:
    """`delivered_on(day)`: non-critical alerts already sent or held for that local day."""
    local = now.astimezone(ZoneInfo(settings.timezone))
    if level is AlertLevel.CRITICAL:
        return Plan("sent", now, local.date(), None)
    held = settings.quiet_hours.contains(local.time())
    deliver = quiet_end(local, settings.quiet_hours) if held else local
    if delivered_on(deliver.date()) >= settings.alert_budget_per_day:
        return Plan("deferred", deliver.astimezone(UTC), deliver.date(), OVER_BUDGET)
    return Plan(
        "held" if held else "sent", deliver.astimezone(UTC), deliver.date(), QUIET if held else None
    )


@dataclass(frozen=True)
class AlertOutcome:
    alert_id: UUID
    incident_id: str
    level: AlertLevel
    status: str
    reason: str | None
    decision_id: UUID | None


def _alerted(conn: Connection, store_id: UUID, incident: Incident) -> bool:
    """An alert at this level or a more severe one already exists for the incident."""
    levels = conn.execute(
        text("SELECT level FROM alerts WHERE store_id = :s AND incident_id = :i"),
        {"s": store_id, "i": incident.incident_id},
    ).scalars()
    return any(ALERT_RANK[AlertLevel(x)] <= ALERT_RANK[incident.alert] for x in levels)


def _delivered_on(conn: Connection, store_id: UUID) -> Callable[[date], int]:
    def count(day: date) -> int:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM alerts WHERE store_id = :s AND local_date = :d AND "
                    "level <> 'critical' AND status IN ('sent', 'held')"
                ),
                {"s": store_id, "d": day},
            ).scalar_one()
        )

    return count


def dispatch_alerts(
    engine: Engine, store_id: UUID, *, now: datetime | None = None
) -> list[AlertOutcome]:
    """Alerts for the latest detection run's incidents, with their deliveries."""
    now = now or datetime.now(UTC)
    out: list[AlertOutcome] = []
    with tenant_transaction(engine, store_id) as conn:
        settings = StoreSettingsRepository(conn).get_or_default(store_id)
        for incident in open_incidents(conn, store_id):
            if not incident.is_alert or _alerted(conn, store_id, incident):
                continue
            decision = propose_for_incident(conn, store_id, incident, now=now)
            p = plan(
                incident.alert,
                now=now,
                settings=settings,
                delivered_on=_delivered_on(conn, store_id),
            )
            alert_id = uuid4()
            conn.execute(
                text(
                    "INSERT INTO alerts (alert_id, store_id, incident_id, level, status, reason, "
                    "decision_id, local_date, deliver_at, created_at) VALUES (:a, :s, :i, :l, "
                    ":st, :r, :d, :day, :at, :now)"
                ),
                {
                    "a": alert_id,
                    "s": store_id,
                    "i": incident.incident_id,
                    "l": incident.alert.value,
                    "st": p.status,
                    "r": p.reason,
                    "d": decision.decision_id if decision else None,
                    "day": p.local_date,
                    "at": p.deliver_at,
                    "now": now,
                },
            )
            if p.status != "deferred":
                notify(
                    conn, store_id, Subject.ALERT, str(alert_id), available_at=p.deliver_at, now=now
                )
            append_audit(
                conn,
                store_id,
                actor="system:alerts",
                action=f"alert.{p.status}",
                payload={
                    "alert_id": str(alert_id),
                    "incident_id": incident.incident_id,
                    "level": incident.alert.value,
                    "reason": p.reason,
                    "decision_id": str(decision.decision_id) if decision else None,
                },
                occurred_at=now,
            )
            out.append(
                AlertOutcome(
                    alert_id,
                    incident.incident_id,
                    incident.alert,
                    p.status,
                    p.reason,
                    decision.decision_id if decision else None,
                )
            )
    return out


def mark_briefed(
    conn: Connection, store_id: UUID, incident_ids: tuple[str, ...], briefing_id: UUID
) -> int:
    """Deferred alerts the daily brief now shows."""
    if not incident_ids:
        return 0
    return conn.execute(
        text(
            "UPDATE alerts SET status = 'briefed', briefing_id = :b WHERE store_id = :s AND "
            "status = 'deferred' AND incident_id = ANY(:ids)"
        ),
        {"b": briefing_id, "s": store_id, "ids": list(incident_ids)},
    ).rowcount
