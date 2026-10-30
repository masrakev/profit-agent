"""Generate a briefing: assemble it from facts, add the narrative, store it once.

The model call happens between two transactions, never inside one: the content (and its facts)
is committed first, the narrative is written, then the briefing is stored. A briefing that
already exists for the store, kind and local day is returned as it is, without a model call.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Engine

from app.agent.llm.provider import LLMProvider
from app.agent.origin import data_origin
from app.agent.stages import Routing, StagesConfig, load_stages
from app.briefings.content import build, utc_now
from app.briefings.models import BriefingKind
from app.briefings.narrative import narrate
from app.briefings.store import BriefingRecord, find, get, save
from app.db import tenant_transaction
from app.delivery.alerts import mark_briefed
from app.delivery.queue import Subject, notify
from app.facts.repository import get_facts


def generate(
    engine: Engine,
    store_id: UUID,
    kind: BriefingKind,
    provider: LLMProvider,
    *,
    local_today: date,
    now: datetime | None = None,
    routing: Routing = Routing.PRODUCTION,
    stages: StagesConfig | None = None,
    run_id: str = "briefing",
) -> BriefingRecord:
    """The store's `kind` briefing for its local day `local_today`."""
    now = now or utc_now()
    stages = stages or load_stages()
    with tenant_transaction(engine, store_id) as conn:
        found = find(conn, store_id, kind, local_today)
    if found is None:
        with tenant_transaction(engine, store_id) as conn:
            content = build(conn, store_id, kind, local_today=local_today, now=now)
            facts = get_facts(conn, store_id, content.fact_ids)
            origin = data_origin(conn, store_id)
        narration, _ = narrate(
            provider,
            content,
            facts,
            origin=origin,
            routing=routing,
            stages=stages,
            run_id=run_id,
            store_id=store_id,
        )
        with tenant_transaction(engine, store_id) as conn:
            found, created = save(conn, store_id, content, narration, local_date=local_today)
            if created:
                notify(conn, store_id, Subject.BRIEFING, str(found), available_at=now, now=now)
                mark_briefed(conn, store_id, content.incident_ids, found)
    with tenant_transaction(engine, store_id) as conn:
        record = get(conn, store_id, found)
    assert record is not None
    return record
