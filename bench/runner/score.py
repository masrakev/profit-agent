"""Scoring rules, protocol v2 (see docs/adr/0007-benchmark-protocol.md).

- Alerts: profitability incidents at level critical, high or normal, and data-quality incidents.
  Profitability incidents below materiality are on the watchlist and are not alerts.
- Primary incident: the first incident as the owner sees them (alert level, then impact).
- Correct root cause: candidate family == label fault type AND candidate entity is one of the
  label's entities. Top-1 / top-3 are read on the primary incident's ranked candidates.
- Detected: some symptom on a label entity (for store-level faults: a store-level symptom)
  first seen no earlier than `start_day - DETECTION_GRACE_DAYS`. Delay = that symptom's first
  seen day - start day (0 if earlier, within the grace).
- False alert (healthy scenarios): any profitability alert.
- Tracking break correctly classified: a data-quality incident on the campaign and no
  profitability alert involving it.
- Attribution check: the label's expected driver is the largest negative level-1 contributor;
  attribution significance: that driver's contribution is outside its noise band.
- Alert precision: share of alerts that point at the real fault (involve a label entity, first
  seen no earlier than the grace before the fault start). Every alert on a healthy store is wrong.
- Alerts per healthy store per month: profitability alerts / (healthy stores x days / 30).
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
    attribution_significant: bool | None = None
    error: bool = False
    primary: str | None = None  # "family entity" of the primary incident's top candidate
    alerts: int = 0
    correct_alerts: int = 0
    profit_alerts: int = 0
    gated: int = 0  # profitability incidents kept on the watchlist by materiality
    levels: dict[str, int] = {}
    months: float = 0.0


def _matches(family: str, entity: str, label: FaultLabel) -> bool:
    return family == label.fault_type.value and entity in {str(e) for e in label.entities}


def _relevant(incident: IncidentView, label: FaultLabel) -> bool:
    entities = {str(e) for e in label.entities}
    return bool(entities & set(incident.entities))


PROFIT_ALERT_LEVELS = frozenset({"critical", "high", "normal"})


def _is_profit_alert(i: IncidentView) -> bool:
    return i.category == SymptomCategory.PROFITABILITY.value and i.alert in PROFIT_ALERT_LEVELS


def _is_alert(i: IncidentView) -> bool:
    return _is_profit_alert(i) or i.alert == "data_quality"


def _alert_counts(outcome: ScenarioOutcome, label: FaultLabel | None) -> dict[str, object]:
    incidents = list(outcome.incidents)
    alerts = [i for i in incidents if _is_alert(i)]
    correct = (
        0
        if label is None
        else sum(
            1
            for i in alerts
            if _relevant(i, label) and i.first_seen_day >= label.start_day - DETECTION_GRACE_DAYS
        )
    )
    levels: dict[str, int] = {}
    for i in incidents:
        levels[i.alert] = levels.get(i.alert, 0) + 1
    return {
        "alerts": len(alerts),
        "correct_alerts": correct,
        "profit_alerts": sum(_is_profit_alert(i) for i in incidents),
        "gated": sum(
            1
            for i in incidents
            if i.category == SymptomCategory.PROFITABILITY.value and i.alert == "watchlist"
        ),
        "levels": levels,
        "months": outcome.days / 30,
    }


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
            false_alert=any(_is_profit_alert(i) for i in incidents),
            primary=shown,
            **_alert_counts(outcome, None),
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
        ) and not any(_is_profit_alert(i) and _relevant(i, label) for i in incidents)
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
        attribution_significant=(
            None
            if label.expected_driver is None
            else attribution is not None
            and attribution.significant.get(label.expected_driver.value) is True
        ),
        primary=shown,
        **_alert_counts(outcome, label),
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
            "attribution_significant": _rate([j.attribution_significant for j in items]),
            "false_alert_rate": _rate([j.false_alert for j in items]),
            "false_alerts": sum(bool(j.false_alert) for j in items),
            "tracking_classified_dq": _rate([j.tracking_classified_dq for j in items]),
        }
    faulty = [j for j in judgements if j.fault_type != HEALTHY]
    delays = [j.delay_days for j in faulty if j.delay_days is not None]
    runtimes = [o.runtime_s for o in outcomes]
    healthy = [j for j in judgements if j.fault_type == HEALTHY]
    alerts = sum(j.alerts for j in judgements)
    levels: dict[str, int] = {}
    for j in judgements:
        for level, count in j.levels.items():
            levels[level] = levels.get(level, 0) + count
    healthy_months = sum(j.months for j in healthy)
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
            "attribution_significant": _rate([j.attribution_significant for j in judgements]),
            "false_alerts": sum(bool(j.false_alert) for j in healthy),
            "healthy_scenarios": len(healthy),
            "alerts": alerts,
            "alert_precision": (
                round(sum(j.correct_alerts for j in judgements) / alerts, 4) if alerts else None
            ),
            "profit_alerts_per_healthy_store_month": (
                round(sum(j.profit_alerts for j in healthy) / healthy_months, 4)
                if healthy_months
                else None
            ),
            "severity_distribution": dict(sorted(levels.items())),
            "gated_incidents_per_scenario": (
                round(mean(j.gated for j in judgements), 2) if judgements else None
            ),
            "runtime_per_scenario_s": {
                "mean": round(mean(runtimes), 2) if runtimes else None,
                "max": max(runtimes) if runtimes else None,
            },
        },
        "per_fault_type": per_type,
    }
