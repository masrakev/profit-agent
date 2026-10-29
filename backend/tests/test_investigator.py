"""Investigator agent on the golden stockout store, with a scripted model (fake transport)."""

import dataclasses
import json
import re
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine

from app.agent.contracts import Flag
from app.agent.guard import check_output
from app.agent.investigator import (
    AuditKind,
    Confidence,
    Hypothesis,
    InvestigationReport,
    apply_audit_rules,
    deterministic_report,
    investigate,
    load_investigation,
    routing_decision,
)
from app.agent.llm import ModelId
from app.agent.llm import fake as f
from app.agent.prompts import load_prompt
from app.agent.stages import Routing, Stage, load_stages
from app.db import tenant_transaction
from app.detection.models import (
    Candidate,
    EntityRef,
    FaultFamily,
    Incident,
    Severity,
    Symptom,
    SymptomCategory,
)
from tests.llm_helpers import Harness

pytestmark = pytest.mark.db
REF = re.compile(r"\{\{E:(?:store|(?:product|campaign):[0-9a-f-]{36})\}\}")


def incident_text(body: dict[str, Any]) -> str:
    return str(body["input"][1]["content"][0]["text"])


def fact_ids(body: dict[str, Any]) -> list[int]:
    # Facts appear in tool outputs and in the incident message (JSON inside text, so escaped).
    return [int(x) for x in re.findall(r'fact_id\\?":\s*(\d+)', json.dumps(body["input"]))]


def call_sensitivity(body: dict[str, Any]) -> f.Reply:
    incident = re.search(r"inc-[0-9a-f]{12}", incident_text(body))
    assert incident is not None
    return f.ok([f.function_call("run_sensitivity", {"incident_id": incident.group(0)})])


def answer(
    body: dict[str, Any], *, confidence: str = "high", narrative: str | None = None
) -> f.Reply:
    entity = REF.findall(incident_text(body))[0]
    fid = fact_ids(body)[0]
    report = {
        "hypotheses": [
            {
                "cause_family": "stockout_on_promoted",
                "entities": [entity],
                "confidence": confidence,
                "evidence": [fid],
                "tests_performed": ["checked stock cover and promoting spend"],
                "counter_evidence": [],
            }
        ],
        "narrative": narrative or f"Promoting {entity} while out of stock; see {{{{F{fid}}}}}.",
        "flags": [],
        "open_questions": [],
        "audit_findings": [],
    }
    return f.structured(report)


def run(app_engine: Engine, store: dict[str, Any], steps: list[Any], **kwargs: Any) -> Any:
    h = Harness(steps)
    kwargs.setdefault("use_cache", False)
    inv = investigate(app_engine, store["id"], store["incident"], h.provider, **kwargs)
    return inv, h


def test_a_verified_investigation(app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    inv, h = run(app_engine, golden_stockout, [call_sensitivity, answer])
    assert inv.status == "complete"
    assert inv.robustness.called_by == "agent"
    top = inv.report.hypotheses[0]
    assert top.cause_family is FaultFamily.STOCKOUT_ON_PROMOTED
    if inv.robustness.stable:
        assert top.confidence is Confidence.HIGH
        assert inv.adjustments == []
    else:
        assert top.confidence is Confidence.MEDIUM
        assert Flag.LOW_EVIDENCE in inv.report.flags
    assert inv.tool_calls == 1
    assert (inv.usage.calls, inv.regenerations, inv.verifier_violations) == (2, 0, 0)
    assert inv.usage.cost_usd > 0
    assert inv.usage.standard_cost_usd == inv.usage.cost_usd  # Spark Standard already
    # Cache-friendly layout: system prompt and tools, then store context, then the incident;
    # the first two input items never change between turns.
    first, second = h.transport.requests
    assert first["instructions"] == second["instructions"] == load_prompt("investigator").text
    assert first["tools"] == second["tools"]
    assert first["input"][:2] == second["input"][:2]
    assert first["input"][0]["content"][0]["text"].startswith("Store context")
    assert "Investigate incident" in incident_text(first)
    assert first["text"]["format"]["name"] == "InvestigationReport"
    assert first["prompt_cache_key"] == f"muse-spark-1.3:{inv.routing.stage}:{inv.prompt_version}"
    with tenant_transaction(app_engine, golden_stockout["id"]) as conn:
        stored = load_investigation(conn, golden_stockout["id"], inv.investigation_id)
        assert stored == inv
        assert load_investigation(conn, golden_stockout["id"], UUID(int=1)) is None


def test_identical_investigations_come_from_the_cache(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    first, _ = run(app_engine, golden_stockout, [call_sensitivity, answer], use_cache=True)
    again, h = run(app_engine, golden_stockout, [], use_cache=True)
    assert again.cache_hit
    assert again.investigation_id == first.investigation_id
    assert again.usage.calls == 0
    assert h.transport.requests == []


def test_skipping_the_robustness_check_is_reminded_then_invalid(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    inv, h = run(app_engine, golden_stockout, [answer, answer])
    reminder = h.transport.requests[1]["input"][-1]
    assert reminder["role"] == "developer"
    assert "run_sensitivity" in reminder["content"][0]["text"]
    assert inv.status == "invalid"
    assert inv.robustness.called_by == "code"  # the check still exists: 100% coverage


def test_unverifiable_output_falls_back_to_the_deterministic_ranking(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    def bad(body: dict[str, Any]) -> f.Reply:
        return answer(body, narrative="Profit fell by $12,345 this month.")

    inv, _ = run(app_engine, golden_stockout, [call_sensitivity, bad, bad, bad])
    assert inv.status == "fallback"
    assert (inv.regenerations, inv.verifier_violations) == (3, 3)
    assert inv.report.flags[0] is Flag.ABSTAIN_INSUFFICIENT_EVIDENCE
    assert all(h.confidence is Confidence.LOW for h in inv.report.hypotheses)


def test_budgets_stop_cleanly(app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    stages = load_stages()
    tiny = dataclasses.replace(
        stages,
        stages={
            **stages.stages,
            **{
                s: dataclasses.replace(stages[s], max_input_tokens=50, max_tool_calls=1)
                for s in (Stage.INVESTIGATION, Stage.ESCALATION)
            },
        },
    )
    partial, _ = run(app_engine, golden_stockout, [call_sensitivity], stages=tiny)
    assert partial.status == "partial"
    assert partial.stop_reason == "input token budget reached"
    assert partial.robustness.called_by == "agent"
    one_tool = dataclasses.replace(
        stages,
        stages={
            **stages.stages,
            **{
                s: dataclasses.replace(stages[s], max_tool_calls=1)
                for s in (Stage.INVESTIGATION, Stage.ESCALATION)
            },
        },
    )

    def two_calls(body: dict[str, Any]) -> f.Reply:
        sens = call_sensitivity(body).body["output"][0]
        return f.ok([sens, f.function_call("get_data_quality", {})])

    inv, h = run(app_engine, golden_stockout, [two_calls, answer], stages=one_tool)
    assert inv.status == "complete"
    assert inv.tool_calls == 1
    sent = h.transport.requests[1]["input"]
    refused = json.loads(sent[-2]["output"])
    assert refused["error_code"] == "tool_budget"
    assert "budget" in sent[-1]["content"][0]["text"]


def test_provider_failure_gives_a_partial_investigation(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    inv, _ = run(
        app_engine,
        golden_stockout,
        [f.error(401, "authentication_error", "bad key", code="invalid_api_key")],
    )
    assert inv.status == "partial"
    assert "AuthenticationFailedError" in (inv.stop_reason or "")
    assert inv.robustness.called_by == "code"
    refusal, _ = run(app_engine, golden_stockout, [call_sensitivity, f.ok([f.refusal("no")])])
    assert refusal.status == "fallback"


def test_economy_routing_uses_the_contributor_model(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    inv, h = run(app_engine, golden_stockout, [call_sensitivity, answer], routing=Routing.ECONOMY)
    assert inv.routing.model == ModelId.SPARK_CONTRIBUTOR.value
    assert {b["model"] for b in h.transport.requests} == {"muse-spark-1.3-contributor"}
    assert inv.usage.standard_cost_usd > inv.usage.cost_usd  # repriced at Standard
    with pytest.raises(LookupError):
        investigate(app_engine, golden_stockout["id"], "inc-000000000000", h.provider)


# --- pure rules ----------------------------------------------------------------------------


def _incident(
    candidates: list[tuple[FaultFamily, float, tuple[str, ...]]],
    category: SymptomCategory = SymptomCategory.PROFITABILITY,
    detectors: tuple[str, ...] = ("a",),
) -> Incident:
    symptoms = tuple(
        Symptom(
            detector_id=d,
            entity=EntityRef.store(),
            metric="m",
            category=category,
            severity=Severity.MEDIUM,
            score=1.0,
            first_seen=date(2026, 8, 1),
            last_seen=date(2026, 8, 3),
            baseline_fact_ids=(1,),
            current_fact_ids=(2,),
        )
        for d in detectors
    )
    return Incident(
        incident_id="inc-000000000001",
        category=category,
        severity_score=1.0,
        first_seen=date(2026, 8, 1),
        last_seen=date(2026, 8, 3),
        entities=(EntityRef.store(),),
        symptoms=symptoms,
        candidates=tuple(
            Candidate(family=fam, entity=EntityRef.store(), score=score, evidence=ev)
            for fam, score, ev in candidates
        ),
    )


def test_routing_decision() -> None:
    mix, cost = FaultFamily.MIX_SHIFT, FaultFamily.SUPPLIER_COST_INCREASE
    assert routing_decision(_incident([(mix, 3.0, ("a",)), (cost, 1.0, ("a",))])) == (
        False,
        "clear deterministic ranking",
    )
    assert routing_decision(_incident([(mix, 3.0, ("a",)), (cost, 2.5, ("a",))])) == (
        True,
        "close deterministic scores",
    )
    assert routing_decision(
        _incident([(mix, 3.0, ("a",))], category=SymptomCategory.DATA_QUALITY)
    ) == (True, "data-quality doubt")
    assert routing_decision(_incident([(mix, 3.0, ("a",))], detectors=("a", "b", "c"))) == (
        True,
        "conflicting symptoms",
    )


def test_audit_rules_cap_confidence_when_unstable() -> None:
    report = InvestigationReport(
        hypotheses=[
            Hypothesis(
                cause_family=FaultFamily.CPA_DRIFT,
                entities=["{{E:store}}"],
                confidence=Confidence.HIGH,
                evidence=[5],
                tests_performed=[],
                counter_evidence=[],
            )
        ],
        narrative="ok",
        flags=[],
        open_questions=[],
        audit_findings=[],
    )
    same, notes = apply_audit_rules(report, {"stable": True})
    assert (same, notes) == (report, [])
    sensitivity = {
        "stable": False,
        "variants": [
            {"expected_monthly_impact": {"fact_id": 9}},
            {"expected_monthly_impact": None},
        ],
    }
    capped, notes = apply_audit_rules(report, sensitivity)
    assert capped.hypotheses[0].confidence is Confidence.MEDIUM
    assert Flag.LOW_EVIDENCE in capped.flags
    finding = capped.audit_findings[0]
    assert (finding.kind, finding.evidence) == (AuditKind.UNSTABLE_CONCLUSION, [9])
    assert notes == [
        "confidence of cpa_drift capped at medium",
        "low_evidence added",
        "unstable_conclusion finding added by code",
    ]
    assert check_output(capped, known_facts={5, 9}, known_entities={"store"}) == []


def test_deterministic_report_is_verifiable() -> None:
    incident = _incident([(FaultFamily.MIX_SHIFT, 3.0, ("a",))])
    report = deterministic_report(incident, {1, 2}, "the model was unavailable")
    assert report.hypotheses[0].evidence == [1, 2]
    assert check_output(report, known_facts={1, 2}, known_entities={"store"}) == []
    empty = deterministic_report(_incident([]), set(), "x")
    assert empty.hypotheses[0].confidence is Confidence.LOW


def test_schema_errors_are_fed_back(app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    broken = f.ok([f.message("this is not the schema")])
    inv, h = run(app_engine, golden_stockout, [call_sensitivity, broken, answer])
    assert (inv.status, inv.regenerations) == ("complete", 1)
    assert h.transport.requests[2]["input"][-1]["role"] == "developer"
    worse, _ = run(app_engine, golden_stockout, [call_sensitivity, broken, broken, broken])
    assert (worse.status, worse.stop_reason) == ("fallback", "output did not match the schema")
