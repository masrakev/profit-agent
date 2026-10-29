"""Run the golden question set against the golden scenarios and report the pass rate.

    uv run python -m bench.golden.runner                      # live, economy routing
    uv run python -m bench.golden.runner --routing production # realistic cost
    uv run python -m bench.golden.runner --only q01 q06

Each needed golden scenario is generated and loaded once into a dedicated database
(`profit_golden`), run through detection, then every non-pending question is asked through Ask.
Writes bench/reports/golden-<timestamp>.json and golden-latest.md.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from app.agent.ask import AskResult, ask
from app.agent.llm.cassette import LLMMode
from app.agent.llm.factory import build_provider
from app.agent.llm.provider import LLMProvider
from app.agent.stages import Routing
from app.config import get_settings
from app.db import make_engine, tenant_transaction
from app.detection.pipeline import run_pipeline
from app.facts.repository import get_facts
from app.observability import configure_logging
from bench.generator.load import load
from bench.golden.checks import (
    CheckResult,
    GoldenSet,
    Question,
    check_answer,
    cited_fact_ids,
    load_golden,
)
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR
from bench.scenarios.manifest import ScenarioManifest, load_suite

GOLDEN_DB = "profit_golden"


def _labels(manifest: ScenarioManifest) -> dict[str, str]:
    out: dict[str, str] = {}
    for label in manifest.labels:
        for entity in label.entities:
            out.setdefault(f"label.{entity.kind.value}", str(entity))
    for condition in manifest.condition_labels:
        for entity in condition.entities:
            out.setdefault(f"label.{entity.kind.value}", str(entity))
    return out


def _names(engine: Engine, store_id: UUID, labels: dict[str, str]) -> dict[str, str]:
    """What the owner would call each labelled entity: its name."""
    names = {}
    with tenant_transaction(engine, store_id) as conn:
        for placeholder, ref in labels.items():
            kind, _, ident = ref.partition(":")
            if kind not in ("product", "campaign"):
                continue  # the store is "my store" in the owner's words
            table = "products" if kind == "product" else "ad_campaigns"
            name = conn.execute(
                text(f"SELECT name FROM {table} WHERE store_id = :s AND id = :i"),
                {"s": store_id, "i": UUID(ident)},
            ).scalar()
            names[placeholder] = str(name)
    return names


def _question_text(q: Question, names: dict[str, str]) -> str:
    out = q.question
    for placeholder, name in names.items():
        out = out.replace("{" + placeholder + "}", name)
    return out


def run_question(
    q: Question,
    engine: Engine,
    store_id: UUID,
    labels: dict[str, str],
    names: dict[str, str],
    provider: LLMProvider,
    routing: Routing,
    run_id: str,
) -> dict[str, Any]:
    try:
        result: AskResult = ask(
            engine, store_id, _question_text(q, names), provider, routing=routing, run_id=run_id
        )
    except Exception as exc:
        return {"id": q.id, "type": q.type.value, "passed": False, "error": repr(exc)[:500]}
    with tenant_transaction(engine, store_id) as conn:
        facts = get_facts(conn, store_id, cited_fact_ids(result.answer))
    checks: list[CheckResult] = check_answer(q, result, facts, labels)
    usage = result.usage + result.classification_usage
    return {
        "id": q.id,
        "type": q.type.value,
        "scenario": q.scenario,
        "passed": all(c.passed for c in checks),
        "failed_checks": [f"{c.name} ({c.detail})" for c in checks if not c.passed],
        "status": result.status,
        "classified_as": result.question_type.value if result.question_type else None,
        "answer": result.answer.model_dump(mode="json"),
        "usage": usage.model_dump(mode="json"),
        "model": result.model,
        "regenerations": result.regenerations,
        "verifier_violations": result.verifier_violations,
    }


def summarize(golden: GoldenSet, rows: list[dict[str, Any]]) -> dict[str, Any]:
    active = [r for r in rows if not r.get("pending")]
    by_type: dict[str, list[bool]] = {}
    for r in active:
        by_type.setdefault(r["type"], []).append(bool(r["passed"]))
    cost = sum((Decimal(r["usage"]["cost_usd"]) for r in active if "usage" in r), Decimal(0))
    standard = sum(
        (Decimal(r["usage"]["standard_cost_usd"]) for r in active if "usage" in r), Decimal(0)
    )
    return {
        "questions": len(golden.questions),
        "active": len(active),
        "passed": sum(bool(r["passed"]) for r in active),
        "pass_rate": round(sum(bool(r["passed"]) for r in active) / len(active), 4)
        if active
        else None,
        "by_type": {t: {"n": len(v), "passed": sum(v)} for t, v in sorted(by_type.items())},
        "pending": [{"id": r["id"], "reason": r["pending"]} for r in rows if r.get("pending")],
        "cost_usd": str(cost),
        "standard_cost_usd": str(standard),
        "verifier_violations_in_answers": sum(
            1 for r in active for c in r.get("failed_checks", []) if c.startswith("unverified")
        ),
    }


def markdown(summary: dict[str, Any], rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines = [
        "# Golden questions",
        "",
        f"Run {meta['started']} - routing {meta['routing']} - mode {meta['mode']}.",
        "",
        "| Active questions | Passed | Pass rate | Cost USD | Cost at Standard prices USD |",
        "| --- | --- | --- | --- | --- |",
        f"| {summary['active']} | {summary['passed']} | "
        f"{summary['pass_rate'] * 100:.0f}% | {summary['cost_usd']} | "
        f"{summary['standard_cost_usd']} |"
        if summary["pass_rate"] is not None
        else "| 0 | - |",
        "",
        "| Type | Questions | Passed |",
        "| --- | --- | --- |",
        *(f"| {t} | {v['n']} | {v['passed']} |" for t, v in summary["by_type"].items()),
        "",
        "## Pending",
        "",
        *(f"- `{p['id']}`: {p['reason']}" for p in summary["pending"]),
        "",
        "## Failed",
        "",
        *(
            f"- `{r['id']}` ({r['type']}): "
            f"{'; '.join(r.get('failed_checks', [])) or r.get('error')}"
            for r in rows
            if not r.get("pending") and not r["passed"]
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the golden question set")
    parser.add_argument("--routing", choices=[r.value for r in Routing], default="economy")
    parser.add_argument("--mode", choices=[m.value for m in LLMMode], default="live")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    configure_logging("WARNING")
    golden = load_golden()
    routing = Routing(args.routing)
    questions = [q for q in golden.questions if not args.only or q.id in set(args.only)]
    started = datetime.now(UTC).replace(microsecond=0)
    run_id = f"golden-{started:%Y%m%dT%H%M%SZ}"
    engine = make_engine(prepare_database(GOLDEN_DB))
    provider = build_provider(get_settings(), mode=LLMMode(args.mode))
    manifests = {m.scenario_id: m for m in load_suite("golden")}
    rows: list[dict[str, Any]] = []
    stores: dict[str, tuple[UUID, dict[str, str], dict[str, str]]] = {}
    todo = []
    for q in questions:
        reason = golden.pending_reason(q)
        if reason is not None:
            rows.append({"id": q.id, "type": q.type.value, "passed": False, "pending": reason})
            continue
        if q.scenario not in stores:
            manifest = manifests[q.scenario]
            data = manifest.generate()
            load(engine, data, manifest.config)
            run_pipeline(engine, data.store.store_id)
            labels = _labels(manifest)
            stores[q.scenario] = (
                data.store.store_id,
                labels,
                _names(engine, data.store.store_id, labels),
            )
        todo.append(q)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(run_question, q, engine, *stores[q.scenario], provider, routing, run_id)
            for q in todo
        ]
        rows.extend(f.result() for f in futures)
    rows.sort(key=lambda r: r["id"])
    summary = summarize(golden, rows)
    meta = {"started": started.isoformat(), "routing": routing.value, "mode": args.mode}
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = f"{started:%Y%m%dT%H%M%SZ}"
    report = {"meta": meta, "summary": summary, "questions": rows}
    (args.out / f"golden-{stamp}-{routing.value}.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (args.out / f"golden-latest-{routing.value}.md").write_text(
        markdown(summary, rows, meta), encoding="utf-8"
    )
    sys.stdout.write(markdown(summary, rows, meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
