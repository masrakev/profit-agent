"""What the web platform reads about a store (ADR 0020): overview, incidents and their
investigations (the agent's trace streamed while it runs), facts with their formula and lineage
(the "clickable number"), the profit bridge, briefings, Ask streamed, settings.

Streams are server-sent events (`text/event-stream`): `event: step` for each step of the agent,
then `event: answer` (Ask) and `event: done`, or `event: failed`.
"""

import json
import queue
import threading
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Engine, text

from app.agent.ask import AskResult, ask
from app.agent.investigator import investigate, load_investigation
from app.agent.llm.provider import LLMProvider
from app.agent.steps import Step, recording
from app.agent.trace import FINAL, recorder, steps_after
from app.api.auth import PrincipalDep, StoreDep
from app.api.deps import EngineDep, ProviderDep
from app.api.pagination import Cursor, Limit, Page, paginate
from app.api.views import Cited, DocumentOut, FactOut, cited, document_out, fact_out
from app.briefings import periods
from app.briefings.content import build, context, open_incidents, profit_bridge
from app.briefings.models import BriefingKind
from app.briefings.store import get as get_briefing
from app.briefings.store import list_briefings
from app.db import tenant_transaction
from app.detection.repository import load_incident
from app.facts.formulas import REGISTRY
from app.facts.registry import UnknownFormulaError
from app.facts.repository import get_facts
from app.policies.engine import store_switch_on
from app.settings.models import StoreSettings
from app.settings.repository import StoreSettingsRepository

router = APIRouter(prefix="/api/v1/stores/{store_id}")
IncidentId = Annotated[str, Path(pattern=r"^inc-[0-9a-f]{12}$")]
STREAM_TIMEOUT_S = 600.0
POLL_S = 0.25
SSE = "text/event-stream"


def _now() -> datetime:
    return datetime.now(UTC)


def _local_today(settings: StoreSettings) -> date:
    return _now().astimezone(ZoneInfo(settings.timezone)).date()


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "not_found", "message": what})


def _event(kind: str, data: Any, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"


# --- overview --------------------------------------------------------------------------------


@router.get("/overview", response_model=DocumentOut, tags=["overview"])
def get_overview(store_id: StoreDep, engine: EngineDep) -> DocumentOut:
    """Today's daily brief, assembled now from facts: health line, money at stake, top items,
    pending decisions, data notice (no narrative)."""
    with tenant_transaction(engine, store_id) as conn:
        settings = StoreSettingsRepository(conn).get_or_default(store_id)
        content = build(
            conn, store_id, BriefingKind.DAILY, local_today=_local_today(settings), now=_now()
        )
        return document_out(conn, store_id, content)


# --- incidents and investigations -------------------------------------------------------------


class IncidentOut(BaseModel):
    incident_id: str
    category: str
    alert: str
    material: bool
    first_seen: date
    last_seen: date
    entity: str  # the top cause's entity reference
    cause: str | None  # the top cause's family
    monthly_impact: FactOut | None = None


class IncidentDetail(Cited):
    incident: dict[str, Any]  # the full incident: symptoms with their fact ids, candidates
    investigation_ids: list[UUID]
    decision_ids: list[UUID]


def _incident_out(incident: Any, impact: FactOut | None) -> IncidentOut:
    top = incident.candidates[0] if incident.candidates else None
    entity = "store" if top is None or top.entity.id is None else str(top.entity)
    return IncidentOut(
        incident_id=incident.incident_id,
        category=incident.category.value,
        alert=incident.alert.value,
        material=incident.material,
        first_seen=incident.first_seen,
        last_seen=incident.last_seen,
        entity=entity,
        cause=top.family.value if top else None,
        monthly_impact=impact,
    )


@router.get("/incidents", response_model=Page[IncidentOut], tags=["incidents"])
def get_incidents(
    store_id: StoreDep, engine: EngineDep, limit: Limit = 50, cursor: Cursor = None
) -> Page[IncidentOut]:
    """The latest detection run's incidents, most urgent first."""
    with tenant_transaction(engine, store_id) as conn:
        incidents = open_incidents(conn, store_id)
        wanted = [i.monthly_impact_fact_id for i in incidents if i.monthly_impact_fact_id]
        impacts = get_facts(conn, store_id, wanted)
    ranked = [
        (
            f"{rank:06d}",
            _incident_out(
                i,
                fact_out(impacts[i.monthly_impact_fact_id])
                if i.monthly_impact_fact_id in impacts
                else None,
            ),
        )
        for rank, i in enumerate(incidents)
    ]
    page = paginate(ranked, key=lambda r: (r[0],), limit=limit, cursor=cursor, descending=False)
    return Page[IncidentOut](items=[r[1] for r in page.items], next_cursor=page.next_cursor)


@router.get("/incidents/{incident_id}", response_model=IncidentDetail, tags=["incidents"])
def get_incident(store_id: StoreDep, incident_id: IncidentId, engine: EngineDep) -> IncidentDetail:
    with tenant_transaction(engine, store_id) as conn:
        stored = load_incident(conn, store_id, incident_id)
        if stored is None:
            raise _not_found("no such incident")
        incident = stored.incident
        ids = {incident.monthly_impact_fact_id} if incident.monthly_impact_fact_id else set()
        for s in incident.symptoms:
            ids |= {*s.current_fact_ids, *s.baseline_fact_ids}
        refs = [f"{{{{F{i}}}}}" for i in ids] + [
            f"{{{{E:{'store' if e.id is None else e}}}}}" for e in incident.entities
        ]
        found = cited(conn, store_id, refs)
        investigations = conn.execute(
            text(
                "SELECT investigation_id FROM investigations WHERE store_id = :s AND "
                "incident_id = :i ORDER BY created_at DESC"
            ),
            {"s": store_id, "i": incident_id},
        ).scalars()
        decisions = conn.execute(
            text(
                "SELECT decision_id FROM decisions WHERE store_id = :s AND incident_id = :i "
                "ORDER BY created_at DESC"
            ),
            {"s": store_id, "i": incident_id},
        ).scalars()
        return IncidentDetail(
            incident=incident.model_dump(mode="json"),
            investigation_ids=list(investigations),
            decision_ids=list(decisions),
            facts=found.facts,
            names=found.names,
        )


class Started(BaseModel):
    investigation_id: UUID
    events: str  # the server-sent events stream of its steps
    result: str  # the investigation, once done


def run_investigation(
    engine: Engine,
    provider: LLMProvider,
    store_id: UUID,
    incident_id: str,
    investigation_id: UUID,
    use_cache: bool,
) -> None:
    sink = recorder(engine, store_id, investigation_id)
    with recording(sink):
        sink(Step("started", None, {"incident_id": incident_id}))
        try:
            done = investigate(
                engine,
                store_id,
                incident_id,
                provider,
                use_cache=use_cache,
                investigation_id=investigation_id,
            )
        except Exception as exc:  # the stream must end, whatever happened
            sink(Step("failed", None, {"error": type(exc).__name__}))
            return
        sink(
            Step(
                "done",
                None,
                {"investigation_id": str(done.investigation_id), "status": done.status},
            )
        )


@router.post(
    "/incidents/{incident_id}/investigations",
    status_code=202,
    response_model=Started,
    tags=["investigations"],
)
def post_investigation(
    store_id: StoreDep,
    incident_id: IncidentId,
    engine: EngineDep,
    provider: ProviderDep,
    background: BackgroundTasks,
    refresh: bool = False,
) -> Started:
    """Start an investigation; follow its steps on `events`, read it at `result` when done
    (a cached identical investigation ends at once, its id in the `done` event)."""
    with tenant_transaction(engine, store_id) as conn:
        if load_incident(conn, store_id, incident_id) is None:
            raise _not_found("no such incident")
    investigation_id = uuid4()
    background.add_task(
        run_investigation, engine, provider, store_id, incident_id, investigation_id, not refresh
    )
    base = f"/api/v1/stores/{store_id}/investigations/{investigation_id}"
    return Started(investigation_id=investigation_id, events=f"{base}/events", result=base)


class StepOut(BaseModel):
    seq: int
    kind: str
    name: str | None
    detail: dict[str, Any]
    created_at: datetime


@router.get(
    "/investigations/{investigation_id}/steps",
    response_model=list[StepOut],
    tags=["investigations"],
)
def get_steps(store_id: StoreDep, investigation_id: UUID, engine: EngineDep) -> list[StepOut]:
    """The agent's step trace (kept 30 days)."""
    with tenant_transaction(engine, store_id) as conn:
        steps = steps_after(conn, store_id, investigation_id)
    return [StepOut(**s.__dict__) for s in steps]


@router.get(
    "/investigations/{investigation_id}/events",
    tags=["investigations"],
    response_class=StreamingResponse,
    responses={200: {"content": {SSE: {}}, "description": "server-sent events"}},
)
def get_events(
    store_id: StoreDep,
    investigation_id: UUID,
    engine: EngineDep,
    last_event_id: Annotated[int, Header(alias="Last-Event-ID", ge=0)] = 0,
) -> StreamingResponse:
    """The investigation's steps as server-sent events, until it is done (`event: done`) or
    failed; a reconnecting client resumes after Last-Event-ID."""
    with tenant_transaction(engine, store_id) as conn:
        known = steps_after(conn, store_id, investigation_id) or load_investigation(
            conn, store_id, investigation_id
        )
    if not known:
        raise _not_found("no such investigation")

    def stream() -> Iterator[str]:
        seen, deadline = last_event_id, time.monotonic() + STREAM_TIMEOUT_S
        while time.monotonic() < deadline:
            with tenant_transaction(engine, store_id) as conn:
                new = steps_after(conn, store_id, investigation_id, seen)
                finished = load_investigation(conn, store_id, investigation_id)
            for step in new:
                seen = step.seq
                kind = step.kind if step.kind in FINAL else "step"
                yield _event(kind, StepOut(**step.__dict__).model_dump(mode="json"), step.seq)
                if step.kind in FINAL:
                    return
            if not new and finished is not None and seen == 0:
                yield _event("done", {"investigation_id": str(investigation_id)})
                return
            time.sleep(POLL_S)
        yield _event("failed", {"error": "timeout"})

    return StreamingResponse(stream(), media_type=SSE, headers={"X-Accel-Buffering": "no"})


# --- facts and the profit bridge --------------------------------------------------------------


class Formula(BaseModel):
    formula_id: str
    version: int
    description: str
    inputs: list[str]


class Parent(BaseModel):
    role: str
    fact: FactOut


class Source(BaseModel):
    table: str
    count: int
    ids: list[UUID]  # the first ones


class FactDetail(BaseModel):
    fact: FactOut
    formula: Formula | None  # None for derived facts (Shapley, twin, derived)
    parents: list[Parent]
    sources: list[Source]


MAX_SOURCE_IDS = 50


@router.get("/facts/{fact_id}", response_model=FactDetail, tags=["facts"])
def get_fact(
    store_id: StoreDep, fact_id: Annotated[int, Path(ge=1)], engine: EngineDep
) -> FactDetail:
    """A number and how it was made: its formula, the facts it came from, the source rows."""
    with tenant_transaction(engine, store_id) as conn:
        found = get_facts(conn, store_id, [fact_id])
        if fact_id not in found:
            raise _not_found("no such fact")
        rows = conn.execute(
            text(
                "SELECT role, source_table, source_ids, parent_fact_id FROM fact_lineage "
                "WHERE store_id = :s AND fact_id = :f ORDER BY id"
            ),
            {"s": store_id, "f": fact_id},
        ).all()
        parents = get_facts(conn, store_id, [r.parent_fact_id for r in rows if r.parent_fact_id])
    fact = found[fact_id]
    try:
        f = REGISTRY.get(fact.formula_id)
        formula = Formula(
            formula_id=f.formula_id,
            version=f.version,
            description=f.description,
            inputs=list(f.inputs),
        )
    except UnknownFormulaError:
        formula = None
    return FactDetail(
        fact=fact_out(fact),
        formula=formula,
        parents=[
            Parent(role=r.role, fact=fact_out(parents[r.parent_fact_id]))
            for r in rows
            if r.parent_fact_id in parents
        ],
        sources=[
            Source(
                table=r.source_table,
                count=len(r.source_ids or []),
                ids=list(r.source_ids or [])[:MAX_SOURCE_IDS],
            )
            for r in rows
            if r.source_table is not None
        ],
    )


class Contribution(BaseModel):
    driver: str
    fact: FactOut
    significant: bool | None


class Bridge(BaseModel):
    period_start: date
    period_end: date
    baseline_start: date
    baseline_end: date
    change: FactOut | None
    drivers: list[Contribution]


@router.get("/profit-bridge", response_model=Bridge, tags=["facts"])
def get_profit_bridge(
    store_id: StoreDep,
    engine: EngineDep,
    period: Annotated[Literal["week", "month"], Query()] = "week",
) -> Bridge:
    """The change in net profit, last complete week (or month) against the one before, split
    by driver (Shapley), drivers inside their noise band marked not significant."""
    with tenant_transaction(engine, store_id) as conn:
        settings = StoreSettingsRepository(conn).get_or_default(store_id)
        ctx = context(conn, store_id, local_today=_local_today(settings), now=_now())
        span = periods.week_period(ctx.day) if period == "week" else periods.month_period(ctx.day)
        before = periods.previous(span, monthly=period == "month")
        _, attribution = profit_bridge(ctx, span, before)
        if attribution is None:
            return Bridge(
                period_start=span[0],
                period_end=span[1],
                baseline_start=before[0],
                baseline_end=before[1],
                change=None,
                drivers=[],
            )
        ids = [attribution.delta_fact_id, *(c.fact_id for c in attribution.level1.values())]
        facts = get_facts(conn, store_id, ids)
    return Bridge(
        period_start=span[0],
        period_end=span[1],
        baseline_start=before[0],
        baseline_end=before[1],
        change=fact_out(facts[attribution.delta_fact_id]),
        drivers=[
            Contribution(driver=d.value, fact=fact_out(facts[c.fact_id]), significant=c.significant)
            for d, c in attribution.level1.items()
        ],
    )


# --- briefings -------------------------------------------------------------------------------


class BriefingSummary(BaseModel):
    briefing_id: UUID
    kind: str
    local_date: date
    period_start: date
    period_end: date
    status: str
    headline: str
    created_at: datetime


class BriefingOut(DocumentOut):
    briefing_id: UUID
    kind: str
    local_date: date
    period_start: date
    period_end: date
    status: str
    nothing_material: bool
    model: str | None
    prompt_version: str | None
    cost_usd: str
    created_at: datetime


@router.get("/briefings", response_model=Page[BriefingSummary], tags=["briefings"])
def get_briefings(
    store_id: StoreDep,
    engine: EngineDep,
    kind: BriefingKind | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> Page[BriefingSummary]:
    """The store's briefings, newest first."""
    with tenant_transaction(engine, store_id) as conn:
        records = list_briefings(conn, store_id, kind=kind, limit=10_000)
    summaries = [
        BriefingSummary(
            briefing_id=r.briefing_id,
            kind=r.kind.value,
            local_date=r.local_date,
            period_start=r.content.period_start,
            period_end=r.content.period_end,
            status=r.status,
            headline=r.content.headline,
            created_at=r.created_at,
        )
        for r in records
    ]
    return paginate(
        summaries,
        key=lambda b: (b.created_at.isoformat(), str(b.briefing_id)),
        limit=limit,
        cursor=cursor,
    )


@router.get("/briefings/{briefing_id}", response_model=BriefingOut, tags=["briefings"])
def get_briefing_detail(store_id: StoreDep, briefing_id: UUID, engine: EngineDep) -> BriefingOut:
    """A briefing as sent: its sections and narrative, the facts and names they cite."""
    with tenant_transaction(engine, store_id) as conn:
        record = get_briefing(conn, store_id, briefing_id)
        if record is None:
            raise _not_found("no such briefing")
        doc = document_out(conn, store_id, record.content, record.narration.narrative)
    return BriefingOut(
        **doc.model_dump(),
        briefing_id=record.briefing_id,
        kind=record.kind.value,
        local_date=record.local_date,
        period_start=record.content.period_start,
        period_end=record.content.period_end,
        status=record.status,
        nothing_material=record.content.nothing_material,
        model=record.narration.model,
        prompt_version=record.narration.prompt_version,
        cost_usd=str(record.narration.cost_usd),
        created_at=record.created_at,
    )


# --- Ask, streamed ---------------------------------------------------------------------------


class Question(BaseModel):
    question: str


@router.post(
    "/ask/stream",
    tags=["ask"],
    response_class=StreamingResponse,
    responses={200: {"content": {SSE: {}}, "description": "server-sent events"}},
)
def post_ask_stream(
    store_id: StoreDep, body: Question, engine: EngineDep, provider: ProviderDep
) -> StreamingResponse:
    """Ask, with the agent's steps as server-sent events while it works, then
    `event: answer` (the answer contract) and `event: done`."""
    if not 1 <= len(body.question) <= 2000:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_request", "message": "a question of 1 to 2000 characters"},
        )
    events: queue.Queue[tuple[str, Any]] = queue.Queue()

    def work() -> None:
        with recording(lambda s: events.put(("step", s.__dict__))):
            try:
                result: AskResult = ask(engine, store_id, body.question, provider)
            except Exception as exc:  # the stream must end, whatever happened
                events.put(("failed", {"error": type(exc).__name__}))
                return
        events.put(("answer", result.model_dump(mode="json")))
        events.put(("done", {}))

    def stream() -> Iterator[str]:
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        seq, deadline = 0, time.monotonic() + STREAM_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                kind, data = events.get(timeout=1.0)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            seq += 1
            yield _event(kind, data, seq)
            if kind in ("done", "failed"):
                return
        yield _event("failed", {"error": "timeout"})

    return StreamingResponse(stream(), media_type=SSE, headers={"X-Accel-Buffering": "no"})


# --- settings and the kill switch -------------------------------------------------------------


@router.get("/settings", response_model=StoreSettings, tags=["settings"])
def get_store_settings(store_id: StoreDep, engine: EngineDep) -> StoreSettings:
    with tenant_transaction(engine, store_id) as conn:
        return StoreSettingsRepository(conn).get_or_default(store_id)


@router.put("/settings", response_model=StoreSettings, tags=["settings"])
def put_store_settings(
    store_id: StoreDep, body: StoreSettings, engine: EngineDep, principal: PrincipalDep
) -> StoreSettings:
    """Replace the store's settings (validated; every change audited)."""
    if body.store_id != store_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_request", "message": "store_id must be the path's store"},
        )
    with tenant_transaction(engine, store_id) as conn:
        return StoreSettingsRepository(conn).save(body, actor=principal.label)


class SwitchState(BaseModel):
    enabled: bool


@router.get("/kill-switch", response_model=SwitchState, tags=["policy"])
def get_store_switch(store_id: StoreDep, engine: EngineDep) -> SwitchState:
    """Whether the store's kill switch stops every action."""
    with tenant_transaction(engine, store_id) as conn:
        return SwitchState(enabled=store_switch_on(conn, store_id))
