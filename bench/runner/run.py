"""Run one scenario: generate, load through the app repositories, run the detection pipeline."""

import time
import traceback
from functools import lru_cache

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.db import make_engine
from app.detection.models import Incident
from app.detection.pipeline import DetectionResult, run_pipeline
from app.observability import configure_logging
from bench.faults import FaultLabel
from bench.generator.load import load
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


class AttributionView(BaseModel):
    model_config = ConfigDict(frozen=True)

    baseline: tuple[int, int]  # day indexes, half-open
    current: tuple[int, int]
    delta: str
    level1: dict[str, str]
    largest_negative: str | None


class ScenarioOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    description: str
    labels: tuple[FaultLabel, ...]
    store_id: str
    runtime_s: float
    incidents: tuple[IncidentView, ...] = ()
    attribution: AttributionView | None = None
    error: str | None = None


@lru_cache(maxsize=1)
def _engine(url: str) -> Engine:
    return make_engine(url)


def _incident_view(incident: Incident, manifest: ScenarioManifest) -> IncidentView:
    start = manifest.config.start_date
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
    )


def _attribution_view(
    result: DetectionResult, manifest: ScenarioManifest
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
    )


def run_scenario(manifest: ScenarioManifest, app_url: str) -> ScenarioOutcome:
    began = time.perf_counter()
    data = manifest.generate()
    store_id = data.store.store_id
    try:
        engine = _engine(app_url)
        load(engine, data, manifest.config)
        result = run_pipeline(engine, store_id)
    except Exception:
        return ScenarioOutcome(
            scenario_id=manifest.scenario_id,
            description=manifest.description,
            labels=manifest.labels,
            store_id=str(store_id),
            runtime_s=round(time.perf_counter() - began, 3),
            error=traceback.format_exc(limit=5),
        )
    return ScenarioOutcome(
        scenario_id=manifest.scenario_id,
        description=manifest.description,
        labels=manifest.labels,
        store_id=str(store_id),
        runtime_s=round(time.perf_counter() - began, 3),
        incidents=tuple(_incident_view(i, manifest) for i in result.incidents),
        attribution=_attribution_view(result, manifest),
    )


def worker_init() -> None:
    """Process-pool initializer (module-level so spawned workers can import it)."""
    configure_logging("WARNING")


def run_job(job: tuple[ScenarioManifest, str]) -> ScenarioOutcome:
    return run_scenario(*job)
