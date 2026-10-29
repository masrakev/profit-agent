"""Run one scenario: generate, load through the app repositories, run the detection pipeline."""

import time
import traceback
from decimal import Decimal
from functools import lru_cache
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, text

from app.causes.profit import ProfitAttribution
from app.db import make_engine, tenant_transaction
from app.detection.models import Incident, SymptomCategory
from app.detection.pipeline import DetectionResult, run_pipeline
from app.facts.model import Fact
from app.facts.repository import get_facts
from app.observability import configure_logging
from bench.faults import FaultLabel
from bench.generator.load import load
from bench.runner.agent import AgentSettings, AgentView, investigate_primary
from bench.scenarios.manifest import ScenarioManifest

TOP_CANDIDATES = 5


class CandidateView(BaseModel):
    model_config = ConfigDict(frozen=True)

    family: str
    entity: str
    score: float
    evidence: tuple[str, ...]


class SymptomView(BaseModel):
    model_config = ConfigDict(frozen=True)

    detector_id: str
    entity: str
    category: str
    first_seen_day: int
    score: float


class IncidentView(BaseModel):
    model_config = ConfigDict(frozen=True)

    incident_id: str
    category: str
    severity_score: float
    first_seen_day: int
    last_seen_day: int
    entities: tuple[str, ...]
    detectors: tuple[str, ...]
    symptoms: tuple[SymptomView, ...]
    candidates: tuple[CandidateView, ...]
    alert: str = "watchlist"
    material: bool = False
    impact: tuple[str, str, str] | None = None  # expected monthly impact P10, P50, P90


class AttributionView(BaseModel):
    model_config = ConfigDict(frozen=True)

    baseline: tuple[int, int]  # day indexes, half-open
    current: tuple[int, int]
    delta: str
    level1: dict[str, str]
    largest_negative: str | None
    significant: dict[str, bool | None] = {}
    # Level 2 within the attributed incident's scope (its entities and promoted products).
    largest_negative_in_scope: str | None = None


class ScenarioOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    description: str
    labels: tuple[FaultLabel, ...]
    store_id: str
    runtime_s: float
    days: int = 0  # length of the generated history
    incidents: tuple[IncidentView, ...] = ()
    attribution: AttributionView | None = None
    error: str | None = None
    agent: AgentView | None = None
    agent_error: str | None = None


@lru_cache(maxsize=1)
def _engine(url: str) -> Engine:
    return make_engine(url)


def _incident_view(
    incident: Incident, manifest: ScenarioManifest, impacts: dict[int, Fact]
) -> IncidentView:
    start = manifest.config.start_date
    fact = impacts.get(incident.monthly_impact_fact_id or -1)
    impact = (
        None
        if fact is None or None in (fact.p10, fact.p50, fact.p90)
        else (format(fact.p10, "f"), format(fact.p50, "f"), format(fact.p90, "f"))
    )
    return IncidentView(
        incident_id=incident.incident_id,
        category=incident.category.value,
        severity_score=incident.severity_score,
        first_seen_day=(incident.first_seen - start).days,
        last_seen_day=(incident.last_seen - start).days,
        entities=tuple(str(e) for e in incident.entities),
        detectors=tuple(sorted({s.detector_id for s in incident.symptoms})),
        symptoms=tuple(
            SymptomView(
                detector_id=s.detector_id,
                entity=str(s.entity),
                category=s.category.value,
                first_seen_day=(s.first_seen - start).days,
                score=s.score,
            )
            for s in incident.symptoms
        ),
        candidates=tuple(
            CandidateView(
                family=c.family.value, entity=str(c.entity), score=c.score, evidence=c.evidence
            )
            for c in incident.candidates[:TOP_CANDIDATES]
        ),
        alert=incident.alert.value,
        material=incident.material,
        impact=impact,
    )


def _largest_in_scope(a: ProfitAttribution, scope: set[str]) -> str | None:
    """Driver of the most negative level-2 contribution of an entity in `scope`."""
    worst: tuple[Decimal, str] | None = None
    for driver, contributions in a.level2.items():
        for c in contributions:
            in_scope = f"{c.scope.kind.value}:{c.scope.id}" in scope
            if in_scope and c.value < 0 and (worst is None or c.value < worst[0]):
                worst = (c.value, driver.value)
    return None if worst is None else worst[1]


def _incident_scope(engine: Engine, store_id: UUID, incident: Incident) -> set[str]:
    entities = {str(e) for e in incident.entities}
    campaigns = [e.id for e in incident.entities if e.kind.value == "campaign" and e.id]
    if campaigns:
        with tenant_transaction(engine, store_id) as conn:
            rows = conn.execute(
                text(
                    "SELECT product_id FROM ad_campaign_products WHERE store_id = :s "
                    "AND campaign_id = ANY(:c)"
                ),
                {"s": store_id, "c": campaigns},
            ).scalars()
            entities |= {f"product:{p}" for p in rows}
    return entities


def _attribution_view(
    result: DetectionResult, manifest: ScenarioManifest, scope: set[str] | None = None
) -> AttributionView | None:
    a = result.attribution
    if a is None:
        return None
    start = manifest.config.start_date

    def days(period_start: object, period_end: object) -> tuple[int, int]:
        return ((period_start.date() - start).days, (period_end.date() - start).days)  # type: ignore[attr-defined]

    largest = a.largest_negative()
    return AttributionView(
        baseline=days(a.baseline.start, a.baseline.end),
        current=days(a.current.start, a.current.end),
        delta=format(a.delta, "f"),
        level1={d.value: format(c.value, "f") for d, c in a.level1.items()},
        largest_negative=None if largest is None else largest.value,
        significant={d.value: c.significant for d, c in a.level1.items()},
        largest_negative_in_scope=_largest_in_scope(a, scope) if scope else None,
    )


def run_scenario(
    manifest: ScenarioManifest, app_url: str, agent: AgentSettings | None = None
) -> ScenarioOutcome:
    began = time.perf_counter()
    data = manifest.generate()
    store_id = data.store.store_id
    try:
        engine = _engine(app_url)
        load(engine, data, manifest.config)
        result = run_pipeline(engine, store_id)
        ids = [i.monthly_impact_fact_id for i in result.incidents if i.monthly_impact_fact_id]
        with tenant_transaction(engine, store_id) as conn:
            impacts = get_facts(conn, store_id, [i for i in ids if i is not None])
        attributed = next(
            (i for i in result.incidents if i.category is SymptomCategory.PROFITABILITY), None
        )
        scope = _incident_scope(engine, store_id, attributed) if attributed else None
    except Exception:
        return ScenarioOutcome(
            scenario_id=manifest.scenario_id,
            description=manifest.description,
            labels=manifest.labels,
            store_id=str(store_id),
            runtime_s=round(time.perf_counter() - began, 3),
            error=traceback.format_exc(limit=5),
        )
    agent_view: AgentView | None = None
    agent_error: str | None = None
    if agent is not None and result.incidents:
        try:
            agent_view = investigate_primary(
                engine, store_id, result.incidents[0].incident_id, agent
            )
        except Exception:
            agent_error = traceback.format_exc(limit=5)
    return ScenarioOutcome(
        scenario_id=manifest.scenario_id,
        description=manifest.description,
        labels=manifest.labels,
        store_id=str(store_id),
        runtime_s=round(time.perf_counter() - began, 3),
        days=manifest.config.days,
        incidents=tuple(_incident_view(i, manifest, impacts) for i in result.incidents),
        attribution=_attribution_view(result, manifest, scope),
        agent=agent_view,
        agent_error=agent_error,
    )


def worker_init() -> None:
    """Process-pool initializer (module-level so spawned workers can import it)."""
    configure_logging("WARNING")


def run_job(job: tuple[ScenarioManifest, str, AgentSettings | None]) -> ScenarioOutcome:
    return run_scenario(*job)
