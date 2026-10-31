"""The demo store (Task 5 B7): the golden stockout store, with a history to show.

    uv run python -m bench.demo_seed             # make demo-seed: a fresh profit_demo database
    uv run python -m bench.demo_seed --record    # re-record the model exchanges (synthetic data)

1. The golden stockout store enters the simulator 28 days before its data end.
2. Two past decisions on campaigns that do not promote the product, proposed by the owner,
   approved and executed: a budget cut, then a raise a week later. Each is measured by
   synthetic control after its 7-day window (measured, or abstained when the fit is weak).
3. Fourteen days before the data end, detection raises the critical stockout alert (ads still
   spending on a product out of stock); the alert proposes its decision, left pending.
4. The alert is investigated; its step trace is kept.
5. The daily brief, the weekly report and the monthly review.
6. An owner and an API token (printed once, never written to the report).

Model calls replay the exchanges recorded under `backend/tests/cassettes/demo/` (no key, no
network), so the seed is the same on every machine; `--record` calls the model once and
rewrites them. `make demo` runs the Task 4 loop on this store (bench/demo.py).
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from app.agent.contracts import ActionFamily
from app.agent.llm.cassette import LLMMode
from app.agent.llm.factory import build_provider
from app.agent.llm.provider import LLMProvider
from app.agent.trace import steps_after
from app.api.stores import run_investigation
from app.auth.service import add_owner, create_api_token
from app.briefings.models import BriefingKind
from app.briefings.service import generate
from app.causal.outcome import WINDOW_DAYS, measure
from app.config import Settings, get_settings, repo_path
from app.db import make_engine, tenant_transaction
from app.decisions.options import Option, OptionKind, OptionSet, Reversibility
from app.decisions.store import Channel, Verdict, decide, propose
from app.delivery.alerts import dispatch_alerts
from app.detection.models import AlertLevel, Incident
from app.detection.pipeline import run_pipeline
from app.executor.simulator import SimulatorAdapter
from app.executor.worker import Executor
from app.facts.engine import FactEngine
from app.observability import configure_logging
from app.twin import Action, ActionKind, fit_twin
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR
from bench.scenarios.manifest import ScenarioManifest, load_suite
from bench.simulator import advance, register

SCENARIO = "golden-stockout_on_promoted"
DEMO_DB = "profit_demo"
CASSETTES = repo_path("backend/tests/cassettes/demo")
OWNER = "owner@example.com"
DAYS_BEFORE_END = 28
PAST = (("budget -30%", Decimal("-0.3")), ("budget +20%", Decimal("0.2")))
KINDS = (BriefingKind.DAILY, BriefingKind.WEEKLY, BriefingKind.MONTHLY)
COUNTED = (
    "incidents",
    "alerts",
    "decisions",
    "actions",
    "outcomes",
    "investigations",
    "investigation_steps",
    "briefings",
    "facts",
    "audit_log",
)


@dataclass(frozen=True)
class Past:
    label: str
    decision_id: UUID
    action_id: UUID
    outcome: dict[str, Any]


@dataclass(frozen=True)
class Seeded:
    store_id: UUID
    manifest: ScenarioManifest
    incident: Incident  # the critical stockout alert
    decision_id: UUID  # its decision, pending: the owner's to approve
    investigation_id: UUID
    past: list[Past]
    briefings: dict[str, UUID]
    api_token: str
    counts: dict[str, int]


def demo_manifest() -> ScenarioManifest:
    return next(m for m in load_suite("golden") if m.scenario_id == SCENARIO)


def _campaigns(engine: Engine, store: UUID, promoted: UUID) -> list[UUID]:
    """The store's other campaigns, largest spend first."""
    with tenant_transaction(engine, store) as conn:
        return list(
            conn.execute(
                text(
                    "SELECT campaign_id FROM ad_metrics_daily WHERE store_id = :s AND "
                    "campaign_id <> :c GROUP BY campaign_id ORDER BY sum(spend) DESC, campaign_id"
                ),
                {"s": store, "c": promoted},
            ).scalars()
        )


def owner_option(campaign: UUID, change: Decimal) -> OptionSet:
    kind = OptionKind.REDUCE_BUDGET if change < 0 else OptionKind.INCREASE_BUDGET
    family = (
        ActionFamily.PAUSE_OR_REDUCE_CAMPAIGN if change < 0 else ActionFamily.INCREASE_BUDGET_CAPPED
    )
    option = Option(
        f"owner:{kind.value}:{campaign}",
        kind,
        family,
        f"campaign:{campaign}",
        (Action(kind=ActionKind.CHANGE_BUDGET, entity=campaign, change=change),),
        Reversibility.REVERSIBLE,
        (),
        (),
    )
    return OptionSet(
        cause="owner",
        entity=f"campaign:{campaign}",
        options=(option,),
        recommended=option.option_id,
        reason="the owner's own change",
        floor=Decimal(100),
    )


def past_decision(
    engine: Engine, store: UUID, campaign: UUID, label: str, change: Decimal, seed: int
) -> Past:
    """Proposed, approved, executed, then measured once its window has passed."""
    with tenant_transaction(engine, store) as conn:
        model = fit_twin(conn, store)
        d = propose(
            conn, FactEngine(conn, store), model, owner_option(campaign, change), source="owner"
        )
        decide(
            conn,
            store,
            d.decision_id,
            d.recommended_option_id,
            Verdict.APPROVED,
            channel=Channel.API,
            actor=f"owner:{OWNER}",
        )
    Executor(engine, {"simulator": SimulatorAdapter(engine)}).run_once()
    advance(engine, store, WINDOW_DAYS)
    with tenant_transaction(engine, store) as conn:
        action_id: UUID = conn.execute(
            text(
                "SELECT action_id FROM actions WHERE store_id = :s AND decision_id = :d AND "
                "status = 'executed'"
            ),
            {"s": store, "d": d.decision_id},
        ).scalar_one()
        outcome = measure(conn, store, action_id, seed=seed)  # replayable
    return Past(label, d.decision_id, action_id, outcome)


def _local_today(engine: Engine, store: UUID) -> date:
    """The day after the last day of data: the store's today in the simulator."""
    with tenant_transaction(engine, store) as conn:
        today: date = conn.execute(
            text("SELECT max(ordered_at)::date + 1 FROM orders WHERE store_id = :s"), {"s": store}
        ).scalar_one()
    return today


def _counts(engine: Engine, store: UUID) -> dict[str, int]:
    with tenant_transaction(engine, store) as conn:
        return {
            table: int(
                conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE store_id = :s"),
                    {"s": store},
                ).scalar_one()
            )
            for table in COUNTED
        }


def seed(engine: Engine, provider: LLMProvider) -> Seeded:
    manifest = demo_manifest()
    label = manifest.labels[0]
    promoted = next(e.id for e in label.entities if e.kind.value == "campaign")
    assert promoted is not None
    store = register(engine, manifest, manifest.config.days - DAYS_BEFORE_END)
    others = _campaigns(engine, store, promoted)
    past = [
        past_decision(engine, store, campaign, name, change, seed)
        for seed, (campaign, (name, change)) in enumerate(zip(others, PAST, strict=False))
    ]
    detected = run_pipeline(engine, store)
    alert = next(
        a
        for a in dispatch_alerts(engine, store)
        if a.level is AlertLevel.CRITICAL and a.decision_id is not None
    )
    assert alert.decision_id is not None
    incident = next(i for i in detected.incidents if i.incident_id == alert.incident_id)
    investigation_id = uuid4()
    run_investigation(engine, provider, store, incident.incident_id, investigation_id, True)
    with tenant_transaction(engine, store) as conn:
        steps = steps_after(conn, store, investigation_id)
    if steps[-1].kind != "done" or steps[-1].detail.get("status") != "complete":
        stopped = [s.detail for s in steps if s.kind in ("stopped", "failed")]
        raise RuntimeError(f"the investigation is not complete: {stopped or steps[-1].detail}")
    local_today = _local_today(engine, store)
    briefings: dict[str, UUID] = {}
    for kind in KINDS:
        record = generate(engine, store, kind, provider, local_today=local_today, run_id="demo")
        if record.narration.narrative is None:
            raise RuntimeError(f"the {kind.value} briefing has no narrative")
        briefings[kind.value] = record.briefing_id
    owner = add_owner(engine, OWNER, store)
    _, api_token = create_api_token(engine, store, "demo", owner, datetime.now(UTC))
    return Seeded(
        store_id=store,
        manifest=manifest,
        incident=incident,
        decision_id=alert.decision_id,
        investigation_id=investigation_id,
        past=past,
        briefings=briefings,
        api_token=api_token,
        counts=_counts(engine, store),
    )


def demo_provider(settings: Settings, mode: LLMMode = LLMMode.REPLAY) -> LLMProvider:
    return build_provider(settings, mode=mode, cassette_dir=CASSETTES)


def markdown(s: Seeded, started: datetime) -> str:
    lines = [
        "# Demo store",
        "",
        f"Seeded {started.isoformat()} by `make demo-seed` from `{SCENARIO}` (simulator, "
        f"{DAYS_BEFORE_END} days before the data end, then two windows of {WINDOW_DAYS} days).",
        "",
        f"- Store `{s.store_id}`, owner `{OWNER}` with an API token (printed by the seed).",
        f"- Alert `{s.incident.incident_id}`, level **{s.incident.alert.value}** "
        f"({s.incident.category.value}); its decision `{s.decision_id}` is pending.",
        f"- Investigation `{s.investigation_id}`, with its step trace.",
        "- Briefings: " + ", ".join(f"{k} `{v}`" for k, v in s.briefings.items()) + ".",
        "",
        "Past decisions:",
        "",
        "| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in s.past:
        effect = p.outcome.get("effect") or {}
        lines.append(
            f"| `{str(p.decision_id)[:8]}` | {p.label} | {p.outcome['status']} "
            f"({p.outcome['reason']}) | {effect.get('p10', '-')} / {effect.get('p50', '-')} / "
            f"{effect.get('p90', '-')} | {p.outcome.get('relative_error')} |"
        )
    lines += ["", "Rows:", "", "| Table | Rows |", "| --- | --- |"]
    lines += [f"| {table} | {n} |" for table, n in s.counts.items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the demo store")
    parser.add_argument("--record", action="store_true", help="call the model and re-record")
    args = parser.parse_args(argv)
    configure_logging("WARNING")
    started = datetime.now(UTC).replace(microsecond=0)
    engine = make_engine(prepare_database(DEMO_DB))
    mode = LLMMode.RECORD if args.record else LLMMode.REPLAY
    seeded = seed(engine, demo_provider(get_settings(), mode))
    report = markdown(seeded, started)
    (REPORT_DIR / "demo-seed.md").write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(report)
    sys.stdout.write(f"\nAPI token for the demo store (shown once): {seeded.api_token}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
