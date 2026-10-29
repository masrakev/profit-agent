"""Benchmark scoring rules (protocol v2) and reports."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from app.detection.models import EntityRef, FaultFamily
from bench.faults import CpaDrift, TrackingBreak
from bench.runner.report import render_markdown, write_reports
from bench.runner.run import (
    AttributionView,
    CandidateView,
    IncidentView,
    ScenarioOutcome,
    SymptomView,
)
from bench.runner.score import judge, summarize

CAMPAIGN = EntityRef.campaign(UUID(int=5))


def incident(
    category: str,
    family: str,
    entity: str,
    day: int,
    alert: str | None = None,
    detectors: tuple[str, ...] = ("d",),
) -> IncidentView:
    level = alert or ("data_quality" if category == "data_quality" else "normal")
    return IncidentView(
        incident_id=f"inc-{family}-{day}-{level}",
        category=category,
        severity_score=2.0,
        first_seen_day=day,
        last_seen_day=day + 5,
        entities=(entity,),
        detectors=detectors,
        symptoms=(
            SymptomView(
                detector_id=detectors[0],
                entity=entity,
                category=category,
                first_seen_day=day,
                score=2.0,
            ),
        ),
        candidates=(CandidateView(family=family, entity=entity, score=3.0, evidence=detectors),),
        alert=level,
        material=level in {"critical", "high", "normal"},
        impact=("-500", "-300", "-100"),
    )


def outcome(
    scenario_id: str,
    labels: tuple[object, ...],
    incidents: tuple[IncidentView, ...],
    driver: str | None = None,
    significant: bool | None = None,
    error: str | None = None,
) -> ScenarioOutcome:
    return ScenarioOutcome(
        scenario_id=scenario_id,
        description="d",
        labels=labels,  # type: ignore[arg-type]
        store_id="s",
        runtime_s=1.0,
        days=120,
        incidents=incidents,
        attribution=AttributionView(
            baseline=(0, 28),
            current=(90, 118),
            delta="-1",
            level1={},
            largest_negative=driver,
            significant={} if driver is None else {driver: significant},
        ),
        error=error,
    )


def test_judging_and_reports(tmp_path: Path) -> None:
    drift = CpaDrift(campaign_id=UUID(int=5), start_day=60, magnitude=Decimal("0.5")).label()
    track = TrackingBreak(campaign_id=UUID(int=5), start_day=60, magnitude=Decimal(1)).label()
    c = str(CAMPAIGN)
    outcomes = [
        outcome(
            "ok",
            (drift,),
            (incident("profitability", "cpa_drift", c, 66, "high"),),
            driver="volume",
            significant=True,
        ),
        outcome("early", (drift,), (incident("profitability", "cpa_drift", c, 40),)),
        outcome("dq", (track,), (incident("data_quality", "tracking_break", c, 62),)),
        outcome("dq-wrong", (track,), (incident("profitability", "cpa_drift", c, 62),)),
        # A watchlisted profitability incident on the campaign does not spoil the DQ verdict.
        outcome(
            "dq-watch",
            (track,),
            (
                incident("data_quality", "tracking_break", c, 62),
                incident("profitability", "cpa_drift", c, 62, "watchlist"),
            ),
        ),
        outcome("healthy", (), (incident("data_quality", "tracking_break", c, 10),)),
        outcome("alarm", (), (incident("profitability", "mix_shift", "store", 10, "critical"),)),
        outcome("quiet", (), (incident("profitability", "mix_shift", "store", 10, "watchlist"),)),
        outcome("broken", (drift,), (), error="Traceback"),
    ]
    j = {x.scenario_id: x for x in map(judge, outcomes)}
    assert (j["ok"].detected, j["ok"].delay_days, j["ok"].top1, j["ok"].attribution_ok) == (
        True,
        6,
        True,
        True,
    )
    assert j["ok"].attribution_significant is True
    assert (j["ok"].alerts, j["ok"].correct_alerts) == (1, 1)
    assert j["early"].detected is False
    assert j["early"].top1 is True
    assert (j["early"].alerts, j["early"].correct_alerts) == (1, 0)  # pre-fault alert
    assert j["dq"].tracking_classified_dq is True
    assert j["dq-wrong"].tracking_classified_dq is False
    assert j["dq-watch"].tracking_classified_dq is True
    assert j["healthy"].false_alert is False  # data quality is not a profit alert
    assert j["alarm"].false_alert is True
    assert j["quiet"].false_alert is False
    assert j["quiet"].gated == 1
    assert j["broken"].error
    assert j["broken"].fault_type == FaultFamily.CPA_DRIFT.value

    summary = summarize(list(j.values()), outcomes)
    overall = summary["overall"]
    assert isinstance(overall, dict)
    assert overall["errors"] == 1
    assert (overall["false_alerts"], overall["healthy_scenarios"]) == (1, 3)
    # Alerts: ok, early, dq, dq-wrong, dq-watch (DQ), healthy (DQ), alarm = 7; correct: ok, dq,
    # dq-wrong (involves the campaign after the start), dq-watch.
    assert overall["alerts"] == 7
    assert overall["alert_precision"] == round(4 / 7, 4)
    assert overall["profit_alerts_per_healthy_store_month"] == round(1 / 12, 4)  # 3 stores x 4
    assert overall["severity_distribution"] == {
        "critical": 1,
        "data_quality": 3,
        "high": 1,
        "normal": 2,
        "watchlist": 2,
    }
    started = datetime(2026, 10, 27, tzinfo=UTC)
    md = render_markdown("test_v3", started, summary, list(j.values()), outcomes, 12.5, 1)
    assert "| cpa_drift |" in md
    assert "`alarm`" in md
    assert "## Alerting" in md
    assert "| 1 / 3 |" in md
    json_path, md_path = write_reports(
        "test_v3", started, summary, list(j.values()), outcomes, 12.5, 1, tmp_path
    )
    assert json_path.name == "20261027T000000Z-test_v3.json"
    assert md_path.name == "latest.md"
    _, dev_md = write_reports("dev", started, summary, list(j.values()), outcomes, 1, 1, tmp_path)
    assert dev_md.name == "latest-dev.md"
