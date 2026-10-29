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

from decimal import Decimal
from statistics import mean, median

from pydantic import BaseModel, ConfigDict

from app.detection.models import FaultFamily, SymptomCategory
from bench.faults import FaultLabel
from bench.runner.agent import HypothesisView
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
    attribution_scope_ok: bool | None = None  # level 2, within the incident's scope
    # The agent arm (investigation of the primary incident), when it ran.
    agent_status: str | None = None
    agent_top1: bool | None = None
    agent_top3: bool | None = None
    agent_confidence: str | None = None
    agent_tracking_dq: bool | None = None
    agent_changed_top1: bool | None = None
    agent_escalated: bool | None = None
    agent_stable: bool | None = None
    agent_downgraded: bool | None = None  # code capped a confidence (unstable conclusion)
    agent_robustness_by: str | None = None
    agent_stage: str | None = None
    agent_calls: int = 0
    agent_input_tokens: int = 0
    agent_cached_tokens: int = 0
    agent_output_tokens: int = 0
    agent_reasoning_tokens: int = 0
    agent_cost_usd: str | None = None
    agent_standard_cost_usd: str | None = None
    agent_latency_s: float | None = None
    agent_tool_calls: int = 0
    agent_final_violations: int = 0
    agent_rejected_violations: int = 0
    agent_error: bool = False


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


def _agent_fields(
    outcome: ScenarioOutcome, label: FaultLabel | None, det_top1: bool | None
) -> dict[str, object]:
    a = outcome.agent
    if a is None:
        return {"agent_error": outcome.agent_error is not None}
    ranked = list(a.hypotheses)
    top = ranked[0] if ranked else None

    def hit(h: HypothesisView) -> bool:
        assert label is not None
        return h.family == label.fault_type.value and bool(
            set(h.entities) & {str(e) for e in label.entities}
        )

    fields: dict[str, object] = {
        "agent_status": a.status,
        "agent_confidence": top.confidence if top else None,
        "agent_escalated": a.escalated,
        "agent_stable": a.stable,
        "agent_downgraded": any("capped" in x for x in a.adjustments),
        "agent_robustness_by": a.robustness_by,
        "agent_stage": "escalation" if a.escalated else "investigation",
        "agent_calls": a.calls,
        "agent_input_tokens": a.input_tokens,
        "agent_cached_tokens": a.cached_tokens,
        "agent_output_tokens": a.output_tokens,
        "agent_reasoning_tokens": a.reasoning_tokens,
        "agent_cost_usd": a.cost_usd,
        "agent_standard_cost_usd": a.standard_cost_usd,
        "agent_latency_s": a.latency_s,
        "agent_tool_calls": a.tool_calls,
        "agent_final_violations": a.final_violations,
        "agent_rejected_violations": a.rejected_violations,
    }
    if label is not None:
        top1 = top is not None and hit(top)
        fields["agent_top1"] = top1
        fields["agent_top3"] = any(hit(h) for h in ranked[:3])
        fields["agent_changed_top1"] = None if det_top1 is None else top1 != det_top1
        if label.fault_type is FaultFamily.TRACKING_BREAK:
            fields["agent_tracking_dq"] = top is not None and top.family == "tracking_break"
    return fields


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
            **_agent_fields(outcome, None, None),
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
    det_top1 = bool(ranked) and _matches(ranked[0].family, ranked[0].entity, label)
    return Judgement(
        scenario_id=outcome.scenario_id,
        fault_type=label.fault_type.value,
        detected=first is not None,
        delay_days=None if first is None else max(0, first - label.start_day),
        top1=det_top1,
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
        attribution_scope_ok=(
            None
            if label.expected_driver is None
            else attribution is not None
            and attribution.largest_negative_in_scope == label.expected_driver.value
        ),
        primary=shown,
        **_alert_counts(outcome, label),
        **_agent_fields(outcome, label, det_top1),
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
            "attribution_scope_check": _rate([j.attribution_scope_ok for j in items]),
            "agent_top1": _rate([j.agent_top1 for j in items]),
            "agent_top3": _rate([j.agent_top3 for j in items]),
            "agent_tracking_classified_dq": _rate([j.agent_tracking_dq for j in items]),
            "agent_standard_cost_usd_mean": _mean_decimal(
                [j.agent_standard_cost_usd for j in items]
            ),
            "agent_latency_s_mean": _mean([j.agent_latency_s for j in items]),
            "agent_escalated_share": _rate([j.agent_escalated for j in items]),
            "agent_final_violations": sum(j.agent_final_violations for j in items),
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
            "attribution_scope_check": _rate([j.attribution_scope_ok for j in judgements]),
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
        "agent": _agent_summary(judgements),
    }


def _mean(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return round(mean(known), 2) if known else None


def _mean_decimal(values: list[str | None]) -> str | None:
    known = [Decimal(v) for v in values if v is not None]
    return format(sum(known, Decimal(0)) / len(known), "f") if known else None


def _sum_decimal(values: list[str | None]) -> str:
    return format(sum((Decimal(v) for v in values if v is not None), Decimal(0)), "f")


def _stage_summary(group: list[Judgement]) -> dict[str, object]:
    inputs = sum(j.agent_input_tokens for j in group)
    cached = sum(j.agent_cached_tokens for j in group)
    return {
        "investigations": len(group),
        "calls": sum(j.agent_calls for j in group),
        "input_tokens": inputs,
        "cached_tokens": cached,
        "output_tokens": sum(j.agent_output_tokens for j in group),
        "reasoning_tokens": sum(j.agent_reasoning_tokens for j in group),
        "cost_usd": _sum_decimal([j.agent_cost_usd for j in group]),
        "standard_cost_usd": _sum_decimal([j.agent_standard_cost_usd for j in group]),
        "latency_s_mean": _mean([j.agent_latency_s for j in group]),
        "cache_hit_rate": round(cached / inputs, 4) if inputs else None,
    }


def _agent_summary(judgements: list[Judgement]) -> dict[str, object] | None:
    ran = [j for j in judgements if j.agent_status is not None]
    if not ran:
        return None
    faulty = [j for j in ran if j.fault_type != HEALTHY]
    by_confidence = {
        level: {
            "n": sum(j.agent_confidence == level for j in faulty),
            "accuracy": _rate([j.agent_top1 for j in faulty if j.agent_confidence == level]),
        }
        for level in ("high", "medium", "low")
    }
    wrong = [j for j in faulty if j.agent_top1 is False]
    changed = [j for j in faulty if j.agent_changed_top1]
    confident_wrong = sum(1 for j in wrong if j.agent_confidence == "high")
    return {
        "investigations": len(ran),
        "errors": sum(j.agent_error for j in judgements),
        "statuses": {
            s: sum(j.agent_status == s for j in ran)
            for s in sorted({j.agent_status for j in ran if j.agent_status})
        },
        "top1": _rate([j.agent_top1 for j in faulty]),
        "top3": _rate([j.agent_top3 for j in faulty]),
        "tracking_classified_dq": _rate([j.agent_tracking_dq for j in faulty]),
        "confident_errors": round(confident_wrong / len(faulty), 4) if faulty else None,
        "accuracy_by_confidence": by_confidence,
        "unstable_share": _rate([j.agent_stable is False for j in ran]),
        "robustness_coverage": _rate([j.agent_robustness_by is not None for j in ran]),
        "robustness_by_agent": _rate([j.agent_robustness_by == "agent" for j in ran]),
        "wrong": len(wrong),
        "wrong_downgraded": sum(1 for j in wrong if j.agent_downgraded),
        "changed_top1": len(changed),
        "changed_top1_helped": sum(1 for j in changed if j.agent_top1),
        "changed_top1_hurt": sum(1 for j in changed if not j.agent_top1),
        "escalated_share": _rate([j.agent_escalated for j in ran]),
        "cost_usd_mean": _mean_decimal([j.agent_cost_usd for j in ran]),
        "standard_cost_usd_mean": _mean_decimal([j.agent_standard_cost_usd for j in ran]),
        "latency_s_mean": _mean([j.agent_latency_s for j in ran]),
        "tool_calls_mean": _mean([float(j.agent_tool_calls) for j in ran]),
        "final_violations": sum(j.agent_final_violations for j in ran),
        "rejected_violations": sum(j.agent_rejected_violations for j in ran),
        "per_stage": {
            stage: _stage_summary([j for j in ran if j.agent_stage == stage])
            for stage in ("investigation", "escalation")
            if any(j.agent_stage == stage for j in ran)
        },
    }
