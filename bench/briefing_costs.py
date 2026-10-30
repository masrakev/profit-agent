"""Measure what briefings cost (Task 5 A4): every golden scenario's daily brief, weekly report
and monthly review, generated live with production routing (Spark, low effort), after a
detection run and its alerts (so briefings show real incidents and decisions).

    uv run python -m bench.briefing_costs        # writes bench/reports/briefing-costs.md

The tokens and cost of each narrative are what the store pays per briefing; the unit economics
(docs/launch-readiness.md, section 7) take their means from here.
"""

import argparse
import json
import statistics
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from app.agent.llm.cassette import LLMMode
from app.agent.llm.factory import build_provider
from app.agent.stages import Routing
from app.briefings.models import BriefingKind
from app.briefings.service import generate
from app.config import get_settings, repo_path
from app.db import make_engine, tenant_transaction
from app.delivery.alerts import dispatch_alerts
from app.detection.pipeline import run_pipeline
from app.observability import configure_logging
from bench.generator.load import load
from bench.golden.decisions import RECIPES, set_up
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR
from bench.scenarios.manifest import load_suite

COSTS_DB = "profit_briefing_costs"
COSTS_DECISIONS_DB = "profit_briefing_costs_decisions"
KINDS = (BriefingKind.DAILY, BriefingKind.WEEKLY, BriefingKind.MONTHLY)


def _data_end(engine: Engine, store_id: UUID) -> date:
    with tenant_transaction(engine, store_id) as conn:
        end: date = conn.execute(
            text("SELECT max(ordered_at)::date + 1 FROM orders WHERE store_id = :s"),
            {"s": store_id},
        ).scalar_one()
    return end


def run(mode: LLMMode, only: list[str] | None) -> tuple[str, list[dict[str, Any]]]:
    started = datetime.now(UTC).replace(microsecond=0)
    run_id = f"briefing-costs-{started:%Y%m%dT%H%M%SZ}"
    engine = make_engine(prepare_database(COSTS_DB))
    decisions = make_engine(prepare_database(COSTS_DECISIONS_DB))
    provider = build_provider(get_settings(), mode=mode)
    rows: list[dict[str, Any]] = []
    for manifest in load_suite("golden"):
        if only and manifest.scenario_id not in only:
            continue
        if manifest.scenario_id in RECIPES:
            where, store_id = decisions, set_up(decisions, manifest)
        else:
            where = engine
            data = manifest.generate()
            load(where, data, manifest.config)
            store_id = data.store.store_id
        run_pipeline(where, store_id)
        dispatch_alerts(where, store_id)
        local_today = _data_end(where, store_id)
        for kind in KINDS:
            record = generate(
                where,
                store_id,
                kind,
                provider,
                local_today=local_today,
                routing=Routing.PRODUCTION,
                run_id=run_id,
            )
            n = record.narration
            rows.append(
                {
                    "scenario": manifest.scenario_id,
                    "kind": kind.value,
                    "status": record.status,
                    "model": n.model,
                    "attempts": n.attempts,
                    "input_tokens": n.input_tokens,
                    "output_tokens": n.output_tokens,
                    "cost_usd": str(n.cost_usd),
                    "facts": len(record.content.fact_ids),
                    "sections": len(record.content.sections),
                    "fallback_reason": n.fallback_reason,
                }
            )
    return run_id, rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for kind in KINDS:
        mine = [r for r in rows if r["kind"] == kind.value]
        if not mine:
            continue
        costs = [Decimal(r["cost_usd"]) for r in mine]
        out[kind.value] = {
            "briefings": len(mine),
            "narrated": sum(r["status"] == "narrated" for r in mine),
            "mean_cost_usd": str((sum(costs, Decimal(0)) / len(costs)).quantize(Decimal("1e-6"))),
            "max_cost_usd": str(max(costs)),
            "mean_input_tokens": round(statistics.mean(r["input_tokens"] for r in mine)),
            "mean_output_tokens": round(statistics.mean(r["output_tokens"] for r in mine)),
            "mean_attempts": round(statistics.mean(r["attempts"] for r in mine), 2),
        }
    return out


def ledger_spend(run_id: str) -> Decimal:
    """What the spend ledger recorded for the run: every call, failed ones included."""
    path = repo_path(get_settings().llm_spend_ledger)
    if not path.exists():
        return Decimal(0)
    total = Decimal(0)
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("run_id") == run_id:
            total += Decimal(entry["amount"])
    return total


def markdown(
    run_id: str,
    rows: list[dict[str, Any]],
    summary: dict[str, dict[str, Any]],
    ledger: Decimal | None = None,
) -> str:
    total = sum((Decimal(r["cost_usd"]) for r in rows), Decimal(0))
    lines = [
        "# Briefing costs",
        "",
        f"Run `{run_id}`: every golden scenario's daily brief, weekly report and monthly "
        "review, after detection and its alerts, generated live with production routing "
        "(Spark, low effort). The model writes only the narrative; sections and numbers come "
        "from facts, so a briefing whose narrative fails is still complete (facts only).",
        "",
        "| Type | Briefings | Narrated | Mean cost USD | Max cost USD | Mean input tokens | "
        "Mean output tokens | Mean attempts |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for kind, s in summary.items():
        lines.append(
            f"| {kind} | {s['briefings']} | {s['narrated']} | {s['mean_cost_usd']} | "
            f"{s['max_cost_usd']} | {s['mean_input_tokens']} | {s['mean_output_tokens']} | "
            f"{s['mean_attempts']} |"
        )
    lines += [
        "",
        f"Total cost of the run: USD {total}"
        + (
            f" (the spend ledger, failed calls included: USD {ledger.quantize(Decimal('1e-6'))})."
            if ledger is not None
            else "."
        ),
        "",
        "| Scenario | Type | Status | Attempts | Input tokens | Output tokens | Cost USD | Facts |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['scenario']} | {r['kind']} | {r['status']} | {r['attempts']} | "
            f"{r['input_tokens']} | {r['output_tokens']} | {r['cost_usd']} | {r['facts']} |"
        )
    failed = [r for r in rows if r["status"] != "narrated"]
    if failed:
        lines += ["", "Briefings sent from facts only:", ""]
        lines += [f"- {r['scenario']} {r['kind']}: {r['fallback_reason']}" for r in failed]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure briefing costs on the golden scenarios")
    parser.add_argument("--mode", choices=[m.value for m in LLMMode], default="live")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    configure_logging("WARNING")
    run_id, rows = run(LLMMode(args.mode), args.only)
    summary = summarize(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = run_id.removeprefix("briefing-costs-")
    (args.out / f"briefing-costs-{stamp}.json").write_text(
        json.dumps({"run_id": run_id, "summary": summary, "rows": rows}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report = markdown(run_id, rows, summary, ledger_spend(run_id))
    (args.out / "briefing-costs.md").write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
