"""The agent arm of the benchmark: investigate each scenario's primary incident.

Each worker process builds one provider (live mode, spend recorded in the shared ledger) and
investigates the scenario's first incident (the most urgent, as the owner sees them) with the
requested routing. The investigation never changes alerts: false alerts stay the pipeline's.
"""

from functools import cache
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.agent.investigator import Investigation, investigate
from app.agent.llm.cassette import LLMMode
from app.agent.llm.factory import build_provider
from app.agent.llm.provider import LLMProvider
from app.agent.stages import Routing
from app.config import get_settings
from app.verifier import entity_references, verify


class AgentSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    routing: Routing
    run_id: str
    mode: LLMMode = LLMMode.LIVE


class HypothesisView(BaseModel):
    model_config = ConfigDict(frozen=True)

    family: str
    entities: tuple[str, ...]  # "store", "product:<uuid>", "campaign:<uuid>"
    confidence: str


class AgentView(BaseModel):
    model_config = ConfigDict(frozen=True)

    incident_id: str
    status: str
    hypotheses: tuple[HypothesisView, ...]
    flags: tuple[str, ...]
    audit_findings: tuple[str, ...]  # kinds
    escalated: bool
    model: str
    routing_reason: str
    stable: bool
    robustness_by: str
    adjustments: tuple[str, ...]
    calls: int
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cost_usd: str
    standard_cost_usd: str
    latency_s: float
    tool_calls: int
    memo_hits: int
    regenerations: int
    rejected_violations: int  # literal numbers in rejected (regenerated) outputs
    final_violations: int  # literal numbers in the final report (must be 0)
    refused_tools: tuple[str, ...]
    stop_reason: str | None
    error: str | None = None


@cache
def provider_for(mode: LLMMode) -> LLMProvider:
    return build_provider(get_settings(), mode=mode)


def _strings(value: Any) -> list[str]:
    if isinstance(value, BaseModel):
        return [s for name in type(value).model_fields for s in _strings(getattr(value, name))]
    if isinstance(value, list | tuple):
        return [s for v in value for s in _strings(v)]
    return [value] if isinstance(value, str) else []


def agent_view(inv: Investigation) -> AgentView:
    report = inv.report
    usage = inv.usage
    return AgentView(
        incident_id=inv.incident_id,
        status=inv.status,
        hypotheses=tuple(
            HypothesisView(
                family=h.cause_family.value,
                entities=tuple(sorted(set().union(*(entity_references(e) for e in h.entities)))),
                confidence=h.confidence.value,
            )
            for h in report.hypotheses
        ),
        flags=tuple(f.value for f in report.flags),
        audit_findings=tuple(a.kind.value for a in report.audit_findings),
        escalated=inv.routing.escalated,
        model=inv.routing.model,
        routing_reason=inv.routing.reason,
        stable=inv.robustness.stable,
        robustness_by=inv.robustness.called_by,
        adjustments=tuple(inv.adjustments),
        calls=usage.calls,
        input_tokens=usage.input_tokens,
        cached_tokens=usage.cached_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cost_usd=format(usage.cost_usd, "f"),
        standard_cost_usd=format(usage.standard_cost_usd, "f"),
        latency_s=round(usage.latency_ms / 1000, 2),
        tool_calls=inv.tool_calls,
        memo_hits=inv.memo_hits,
        regenerations=inv.regenerations,
        rejected_violations=inv.verifier_violations,
        final_violations=sum(len(verify(s)) for s in _strings(report)),
        refused_tools=tuple(inv.refused_tools),
        stop_reason=inv.stop_reason,
    )


def investigate_primary(
    engine: Engine, store_id: UUID, incident_id: str, settings: AgentSettings
) -> AgentView:
    inv = investigate(
        engine,
        store_id,
        incident_id,
        provider_for(settings.mode),
        routing=settings.routing,
        use_cache=False,
        run_id=settings.run_id,
    )
    return agent_view(inv)
