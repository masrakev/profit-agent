"""Persisted incidents: the latest detection run's view of each incident, read by agent tools."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.detection.models import Incident
from app.domain.schema import incidents


@dataclass(frozen=True)
class StoredIncident:
    incident: Incident
    as_of: date
    thresholds_version: int


class IncidentRepository:
    """Use inside the store's tenant transaction (row-level security)."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def save_all(
        self, store_id: UUID, items: list[Incident], *, as_of: date, thresholds_version: int
    ) -> None:
        """Insert or refresh incidents. Ids are content-derived (first seen + entities), so a
        later run updates the same incident rather than duplicating it."""
        for incident in items:
            values = {
                "store_id": store_id,
                "incident_id": incident.incident_id,
                "as_of": as_of,
                "thresholds_version": thresholds_version,
                "category": incident.category.value,
                "alert": incident.alert.value,
                "first_seen": incident.first_seen,
                "last_seen": incident.last_seen,
                "payload": incident.model_dump(mode="json"),
            }
            statement = pg_insert(incidents).values(**values)
            self.conn.execute(
                statement.on_conflict_do_update(
                    index_elements=["store_id", "incident_id"],
                    set_={
                        **{k: statement.excluded[k] for k in values if k != "incident_id"},
                        "updated_at": func.now(),
                    },
                )
            )

    def get(self, store_id: UUID, incident_id: str) -> StoredIncident | None:
        row = self.conn.execute(
            select(incidents).where(
                incidents.c.store_id == store_id, incidents.c.incident_id == incident_id
            )
        ).first()
        if row is None:
            return None
        return StoredIncident(
            Incident.model_validate(row.payload), row.as_of, row.thresholds_version
        )

    def list_ids(self, store_id: UUID) -> list[str]:
        return list(
            self.conn.execute(
                select(incidents.c.incident_id)
                .where(incidents.c.store_id == store_id)
                .order_by(incidents.c.incident_id)
            ).scalars()
        )
