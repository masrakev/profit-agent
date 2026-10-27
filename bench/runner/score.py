"""Scoring rules (see docs/adr/0007-benchmark-protocol.md).

- Primary incident: the most severe incident of the scenario (any category).
- Correct root cause: candidate family == label fault type AND candidate entity is one of the
  label's entities. Top-1 / top-3 are read on the primary incident's ranked candidates.
- Detected: some symptom on a label entity (for store-level faults: a store-level symptom)
  first seen no earlier than `start_day - DETECTION_GRACE_DAYS`. Delay = that symptom's first
  seen day - start day (0 if earlier, within the grace).
- False alert (healthy scenarios): any profitability incident.
- Tracking break correctly classified: a data-quality incident on the campaign and no
  profitability incident involving it.
- Attribution check: the label's expected driver is the largest negative level-1 contributor.
"""

from statistics import mean, median

from pydantic import BaseModel, ConfigDict

from app.detection.models import FaultFamily, SymptomCategory
from bench.faults import FaultLabel
from bench.runner.run import IncidentView, ScenarioOutcome

DETECTION_GRACE_DAYS = 3
HEALTHY = "healthy"


class Judgement(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    fault_type: str
    detected: bool | None = None
    delay_days: int | None = None
    top1: bool | None = None
    top3: bool | None = None
    false_alert: bool | None = None
    tracking_classified_dq: bool | None = None
    attribution_ok: bool | None = None
    error: bool = False
    primary: str | None = None  # "family entity" of the primary incident's top candidate


def _matches(family: str, entity: str, label: FaultLabel) -> bool:
    return family == label.fault_type.value and entity in {str(e) for e in label.entities}


def _relevant(incident: IncidentView, label: FaultLabel) -> bool:
    entities = {str(e) for e in label.entities}
    return bool(entities & set(incident.entities))


def judge(outcome: ScenarioOutcome) -> Judgement:
    if outcome.error is not None:
        fault = outcome.labels[0].fault_type.value if outcome.labels else HEALTHY
        return Judgement(scenario_id=outcome.scenario_id, fault_type=fault, error=True)
    incidents = list(outcome.incidents)
    primary = incidents[0] if incidents else None
    top = primary.candidates[0] if primary and primary.candidates else None
    shown = None if top is None else f"{top.family} {top.entity}"
    if not outcome.labels:
        return Judgement(
            scenario_id=outcome.scenario_id,
            fault_type=HEALTHY,
            false_alert=any(i.category == SymptomCategory.PROFITABILITY.value for i in incidents),
            primary=shown,
        )
    label = outcome.labels[0]
    entities = {str(e) for e in label.entities}
    seen = [
        s.first_seen_day
        for i in incidents
        for s in i.symptoms
        if s.entity in entities and s.first_seen_day >= label.start_day - DETECTION_GRACE_DAYS
    ]
    first = min(seen) if seen else None
    ranked = list(primary.candidates) if primary else []
    attribution = outcome.attribution
    tracking: bool | None = None
    if label.fault_type is FaultFamily.TRACKING_BREAK:
        tracking = any(
            i.category == SymptomCategory.DATA_QUALITY.value and _relevant(i, label)
            for i in incidents
        ) and not any(
            i.category == SymptomCategory.PROFITABILITY.value and _relevant(i, label)
            for i in incidents
        )
    return Judgement(
        scenario_id=outcome.scenario_id,
        fault_type=label.fault_type.value,
        detected=first is not None,
        delay_days=None if first is None else max(0, first - label.start_day),
        top1=bool(ranked) and _matches(ranked[0].family, ranked[0].entity, label),
        top3=any(_matches(c.family, c.entity, label) for c in ranked[:3]),
        tracking_classified_dq=tracking,
        attribution_ok=(
            None
            if label.expected_driver is None
            else attribution is not None
            and attribution.largest_negative == label.expected_driver.value
        ),
        primary=shown,
    )


def _rate(values: list[bool | None]) -> float | None:
    known = [v for v in values if v is not None]
    return round(sum(known) / len(known), 4) if known else None


def summarize(judgements: list[Judgement], outcomes: list[ScenarioOutcome]) -> dict[str, object]:
    by_type: dict[str, list[Judgement]] = {}
    for j in judgements:
        by_type.setdefault(j.fault_type, []).append(j)
    per_type: dict[str, dict[str, object]] = {}
    for fault_type, items in sorted(by_type.items()):
        delays = [j.delay_days for j in items if j.delay_days is not None]
        per_type[fault_type] = {
            "scenarios": len(items),
            "errors": sum(j.error for j in items),
            "detection_rate": _rate([j.detected for j in items]),
            "mean_delay_days": round(mean(delays), 2) if delays else None,
            "median_delay_days": median(delays) if delays else None,
            "top1": _rate([j.top1 for j in items]),
            "top3": _rate([j.top3 for j in items]),
            "attribution_check": _rate([j.attribution_ok for j in items]),
            "false_alert_rate": _rate([j.false_alert for j in items]),
            "tracking_classified_dq": _rate([j.tracking_classified_dq for j in items]),
        }
    faulty = [j for j in judgements if j.fault_type != HEALTHY]
    delays = [j.delay_days for j in faulty if j.delay_days is not None]
    runtimes = [o.runtime_s for o in outcomes]
    return {
        "overall": {
            "scenarios": len(judgements),
            "faulty_scenarios": len(faulty),
            "errors": sum(j.error for j in judgements),
            "top1": _rate([j.top1 for j in faulty]),
            "top3": _rate([j.top3 for j in faulty]),
            "detection_rate": _rate([j.detected for j in faulty]),
            "mean_delay_days": round(mean(delays), 2) if delays else None,
            "false_alert_rate": _rate([j.false_alert for j in judgements]),
            "tracking_classified_dq": _rate([j.tracking_classified_dq for j in judgements]),
            "attribution_check": _rate([j.attribution_ok for j in judgements]),
            "runtime_per_scenario_s": {
                "mean": round(mean(runtimes), 2) if runtimes else None,
                "max": max(runtimes) if runtimes else None,
            },
        },
        "per_fault_type": per_type,
    }
