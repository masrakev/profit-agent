"""A decision for an alert: the options of the incident's top cause, simulated by the twin.

Not for data-quality incidents (their next step is fixing the data, not a decision), nor when
the cause's only option is to keep watching. One proposed decision per incident at a time.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, text

from app.decisions.options import OptionKind, build_options
from app.decisions.store import DecisionView, get, propose
from app.detection.models import AlertLevel, Incident
from app.facts.engine import FactEngine
from app.settings.repository import StoreSettingsRepository
from app.twin import fit_twin


def pending_for(conn: Connection, store_id: UUID, incident_id: str, now: datetime) -> UUID | None:
    found: UUID | None = conn.execute(
        text(
            "SELECT decision_id FROM decisions WHERE store_id = :s AND incident_id = :i AND "
            "status = 'proposed' AND expires_at > :now ORDER BY created_at DESC LIMIT 1"
        ),
        {"s": store_id, "i": incident_id, "now": now},
    ).scalar()
    return found


def propose_for_incident(
    conn: Connection, store_id: UUID, incident: Incident, *, now: datetime
) -> DecisionView | None:
    """The incident's pending decision, a new one, or None (no decision for this incident)."""
    if incident.alert is AlertLevel.DATA_QUALITY or not incident.candidates:
        return None
    existing = pending_for(conn, store_id, incident.incident_id, now)
    if existing is not None:
        return get(conn, store_id, existing)
    top = incident.candidates[0]
    entity = "store" if top.entity.id is None else str(top.entity)
    try:
        model = fit_twin(conn, store_id)
    except ValueError:  # too little history to simulate anything
        return None
    floor = StoreSettingsRepository(conn).get_or_default(store_id).materiality.absolute
    options = build_options(model, top.family.value, entity, floor_monthly=floor)
    if all(o.kind is OptionKind.MONITOR for o in options.options):
        return None
    return propose(
        conn,
        FactEngine(conn, store_id),
        model,
        options,
        source="incident",
        incident_id=incident.incident_id,
        now=now,
    )
