"""Where a store's data comes from, read from the store row (never asserted by a caller).

Only synthetic benchmark stores may be sent to a Contributor-mode model (ADR 0009).
"""

from uuid import UUID

from sqlalchemy import Connection, select

from app.agent.llm.models import DataOrigin
from app.domain.schema import stores


def data_origin(conn: Connection, store_id: UUID) -> DataOrigin:
    synthetic = conn.execute(
        select(stores.c.synthetic).where(stores.c.store_id == store_id)
    ).scalar_one_or_none()
    if synthetic is None:
        raise LookupError(f"store {store_id} does not exist or is not visible to this tenant")
    return DataOrigin.SYNTHETIC if synthetic else DataOrigin.REAL
