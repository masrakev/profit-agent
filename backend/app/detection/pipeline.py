"""Deterministic detection pipeline: series -> detectors -> symptoms (backed by facts) ->
incidents (ranked root causes) with a profit attribution for the most severe one.

    uv run python -m app.detection.pipeline --store <store_id>
"""

import argparse
import contextlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

import numpy as np
from sqlalchemy import Engine

from app.causes.noise import DailyFigures, FloatArray, noise_band
from app.causes.profit import (
    AttributionUnavailableError,
    ProfitAttribution,
    attribute_profit_change,
)
from app.config import get_settings
from app.db import app_engine, tenant_transaction
from app.detection.config import DetectionConfig, default_config
from app.detection.detectors import Finding, run_detectors
from app.detection.incidents import EntityGraph, build_incidents
from app.detection.models import Incident, Severity, Symptom
from app.detection.series import StoreSeries, load_series
from app.domain.audit import append_audit
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.engine import FactEngine
from app.facts.model import Period
from app.observability import configure_logging, get_logger


@dataclass(frozen=True)
class DetectionResult:
    as_of: date  # exclusive end of the analysed data
    symptoms: list[Symptom]
    incidents: list[Incident]
    attribution: ProfitAttribution | None
    thresholds_version: int


def _day_period(series: StoreSeries, first: int, end: int) -> Period:
    def at(index: int) -> datetime:
        return datetime.combine(series.day(index), time(), tzinfo=UTC)

    return Period(start=at(first), end=at(end))


def _severity(score: float, cfg: DetectionConfig) -> Severity:
    if score >= cfg.severity.high:
        return Severity.HIGH
    if score >= cfg.severity.medium:
        return Severity.MEDIUM
    return Severity.LOW


def _symptom(
    finding: Finding, series: StoreSeries, engine: FactEngine, cfg: DetectionConfig
) -> Symptom:
    """Persist the facts behind a finding for its current window (ending on the confirmation
    day) and the baseline window just before it."""
    end = finding.episode.confirmed + 1
    if finding.change_point is not None:
        # The baseline must not contain the change: it ends where the change started.
        start = min(finding.change_point, end - 1)
    else:
        start = max(end - finding.window_days, 0)
    base_start = max(start - finding.baseline_days, 0)
    windows = {"current": _day_period(series, start, end)}
    if base_start < start:
        windows["baseline"] = _day_period(series, base_start, start)
    ids: dict[str, list[int]] = {"current": [], "baseline": []}
    for name, period in windows.items():
        for ref in finding.facts:
            fact = engine.persist(engine.fact(ref.formula_id, ref.scope, period))
            ids[name].append(fact.id or 0)
    return Symptom(
        detector_id=finding.detector_id,
        entity=finding.entity,
        metric=finding.metric,
        category=finding.category,
        severity=_severity(finding.score, cfg),
        score=round(finding.score, 6),
        first_seen=series.day(finding.episode.confirmed),
        last_seen=series.day(finding.episode.end),
        baseline_fact_ids=tuple(ids["baseline"]),
        current_fact_ids=tuple(ids["current"]),
        note=finding.note,
    )


def daily_figures(series: StoreSeries) -> DailyFigures:
    """Series as float arrays for the noise band (statistics, not facts)."""

    def rows(values: list[list[Decimal]], width: int) -> FloatArray:
        if not values:
            return np.zeros((0, width))
        return np.array([[float(x) for x in v] for v in values], dtype=np.float64)

    products = list(series.products.values())
    n = series.days
    return DailyFigures(
        revenue=rows([p.revenue for p in products], n),
        units=rows([p.units for p in products], n),
        cogs=rows([p.cogs for p in products], n),
        fees=rows([p.fees for p in products], n),
        refunds=rows([p.refunds for p in products], n),
        spend=rows([c.spend for c in series.campaigns.values()], n),
        fixed=np.array([float(x) for x in series.fixed_costs] or [0.0] * n, dtype=np.float64),
    )


def _seed(store_id: UUID, *parts: object) -> int:
    return int(sha256_hex(canonical_json([str(store_id), *map(str, parts)]))[:16], 16)


def attribution_windows(
    series: StoreSeries, first_seen: date | None, cfg: DetectionConfig
) -> tuple[Period, Period]:
    """Equal-length windows in whole weeks (seasonality cancels).

    With an incident: the baseline ends `pre_incident_gap_days` before it was first seen and the
    current window ends with the data, both as long as possible within [min, max] window days
    without the current window starting before the incident. Without one (or when the incident
    leaves too little room): the last two adjacent windows of `max_window_days`.
    """
    a = cfg.attribution
    end = series.days
    if first_seen is not None:
        seen = series.index(first_seen)
        cut = seen - a.pre_incident_gap_days
        length = min(a.max_window_days, (end - seen) // 7 * 7, cut // 7 * 7)
        if length >= a.min_window_days:
            return (
                _day_period(series, cut - length, cut),
                _day_period(series, end - length, end),
            )
    length = min(a.max_window_days, end // 2 // 7 * 7)
    return _day_period(series, end - 2 * length, end - length), _day_period(
        series, end - length, end
    )


def run_pipeline(
    engine: Engine, store_id: UUID, cfg: DetectionConfig | None = None
) -> DetectionResult:
    cfg = cfg or default_config()
    with tenant_transaction(engine, store_id) as conn:
        series = load_series(conn, store_id)
        facts = FactEngine(conn, store_id)
        symptoms = [_symptom(f, series, facts, cfg) for f in run_detectors(series, cfg)]
        graph = EntityGraph(
            {c.campaign_id: frozenset(c.promoted) for c in series.campaigns.values()}
        )
        attributions: list[ProfitAttribution] = []

        def attribution_for(group: list[Symptom]) -> ProfitAttribution | None:
            first_seen = min(s.first_seen for s in group)
            baseline, current = attribution_windows(series, first_seen, cfg)
            band = noise_band(
                daily_figures(series),
                length=(current.end - current.start).days,
                history_end=series.index(baseline.end.date()),
                rng=np.random.default_rng(_seed(store_id, "noise", first_seen)),
                resamples=cfg.noise_band.resamples,
                min_pairs=cfg.noise_band.min_pairs,
                quantiles=(cfg.noise_band.low_percentile, cfg.noise_band.high_percentile),
            )
            try:
                attributions.append(attribute_profit_change(facts, baseline, current, band))
            except AttributionUnavailableError:
                return None
            return attributions[0]

        incidents = build_incidents(symptoms, graph, cfg, attribution_for)
        if not attributions and series.days >= 4 * cfg.attribution.min_window_days:
            baseline, current = attribution_windows(series, None, cfg)
            with contextlib.suppress(AttributionUnavailableError):
                attributions.append(attribute_profit_change(facts, baseline, current))
        as_of = series.day(series.days) if series.days else date.min
        append_audit(
            conn,
            store_id,
            actor="system:detection",
            action="detection.ran",
            payload={
                "as_of": as_of,
                "thresholds_version": cfg.version,
                "symptoms": len(symptoms),
                "incidents": [i.incident_id for i in incidents],
            },
        )
    return DetectionResult(
        as_of, symptoms, incidents, attributions[0] if attributions else None, cfg.version
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run detection for a store")
    parser.add_argument("--store", required=True, type=UUID)
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    engine = app_engine()
    try:
        result = run_pipeline(engine, args.store)
    finally:
        engine.dispose()
    get_logger(__name__).info("detection.ran", incidents=len(result.incidents))
    summary = {
        "as_of": result.as_of.isoformat(),
        "incidents": [i.model_dump(mode="json") for i in result.incidents],
    }
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
