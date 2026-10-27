"""Benchmark scoring rules and reports."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from app.causes.drivers import Driver
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
    category: str, family: str, entity: str, day: int, detectors: tuple[str, ...] = ("d",)
) -> IncidentView:
    return IncidentView(
        incident_id=f"inc-{family}-{day}",
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
    )


def outcome(
    scenario_id: str,
    labels: tuple[object, ...],
    incidents: tuple[IncidentView, ...],
    driver: str | None = None,
    error: str | None = None,
) -> ScenarioOutcome:
    return ScenarioOutcome(
        scenario_id=scenario_id,
        description="d",
        labels=labels,  # type: ignore[arg-type]
        store_id="s",
        runtime_s=1.0,
        incidents=incidents,
        attribution=AttributionView(
            baseline=(0, 28), current=(90, 118), delta="-1", level1={}, largest_negative=driver
        ),
        error=error,
    )


def test_judging_and_reports(tmp_path: Path) -> None:
    drift = CpaDrift(campaign_id=UUID(int=5), start_day=60, magnitude=Decimal("0.5")).label()
    track = TrackingBreak(campaign_id=UUID(int=5), start_day=60, magnitude=Decimal(1)).label()
    outcomes = [
        outcome(
            "ok",
            (drift,),
            (incident("profitability", "cpa_drift", str(CAMPAIGN), 66),),
            driver="volume",
        ),
        outcome("early", (drift,), (incident("profitability", "cpa_drift", str(CAMPAIGN), 40),)),
        outcome("dq", (track,), (incident("data_quality", "tracking_break", str(CAMPAIGN), 62),)),
        outcome("dq-wrong", (track,), (incident("profitability", "cpa_drift", str(CAMPAIGN), 62),)),
        outcome("healthy", (), (incident("data_quality", "tracking_break", str(CAMPAIGN), 10),)),
        outcome("alarm", (), (incident("profitability", "mix_shift", "store", 10),)),
        outcome("broken", (drift,), (), error="Traceback"),
    ]
    j = {x.scenario_id: x for x in map(judge, outcomes)}
    assert (j["ok"].detected, j["ok"].delay_days, j["ok"].top1, j["ok"].attribution_ok) == (
        True,
        6,
        True,
        True,
    )
    assert j["early"].detected is False
    assert j["early"].top1 is True
    assert j["dq"].tracking_classified_dq is True
    assert j["dq-wrong"].tracking_classified_dq is False
    assert j["healthy"].false_alert is False
    assert j["alarm"].false_alert is True
    assert j["broken"].error
    assert j["broken"].fault_type == FaultFamily.CPA_DRIFT.value
    summary = summarize(list(j.values()), outcomes)
    overall = summary["overall"]
    assert isinstance(overall, dict)
    assert overall["errors"] == 1
    assert overall["false_alert_rate"] == 0.5
    started = datetime(2026, 10, 27, tzinfo=UTC)
    md = render_markdown("test", started, summary, list(j.values()), outcomes, 12.5, 1)
    assert "| cpa_drift |" in md
    assert "`alarm`" in md
    assert "false alert" in md
    json_path, md_path = write_reports(
        "dev", started, summary, list(j.values()), outcomes, 12.5, 1, tmp_path
    )
    assert json_path.name == "20261027T000000Z-dev.json"
    assert md_path.name == "latest-dev.md"
    assert Driver.VOLUME.value == "volume"
