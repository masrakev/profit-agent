"""The agent arm of the benchmark: scoring, report section and audit proposals."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.detection.models import EntityRef
from bench.faults import CpaDrift
from bench.runner.agent import AgentView, HypothesisView
from bench.runner.proposals import render_proposals
from bench.runner.report import agent_section
from bench.runner.score import judge, summarize
from tests.test_bench_scoring import incident, outcome

CAMPAIGN = EntityRef.campaign(UUID(int=5))
STARTED = datetime(2026, 10, 29, tzinfo=UTC)


def agent(
    family: str,
    entity: str,
    confidence: str,
    *,
    escalated: bool = False,
    stable: bool = True,
    adjustments: tuple[str, ...] = (),
) -> AgentView:
    return AgentView(
        incident_id="inc-x",
        status="complete",
        hypotheses=(HypothesisView(family=family, entities=(entity,), confidence=confidence),),
        flags=(),
        audit_findings=("weak_evidence",),
        escalated=escalated,
        model="m",
        routing_reason="r",
        stable=stable,
        robustness_by="agent",
        adjustments=adjustments,
        calls=4,
        input_tokens=1000,
        cached_tokens=600,
        output_tokens=200,
        reasoning_tokens=100,
        cost_usd="0.0010",
        standard_cost_usd="0.0200",
        latency_s=50.0,
        tool_calls=6,
        memo_hits=1,
        regenerations=0,
        rejected_violations=1,
        final_violations=0,
        refused_tools=(),
        stop_reason=None,
    )


def scenarios() -> list[object]:
    label = CpaDrift(campaign_id=CAMPAIGN.id, start_day=60, magnitude=Decimal("0.5")).label()
    entity = str(CAMPAIGN)
    corrected = outcome(
        "dev-cpa_drift-01", (label,), (incident("data_quality", "tracking_break", entity, 62),)
    )
    corrected = corrected.model_copy(
        update={
            "agent": agent(
                "cpa_drift",
                entity,
                "medium",
                escalated=True,
                stable=False,
                adjustments=("x capped",),
            )
        }
    )
    confident_wrong = outcome(
        "dev-cpa_drift-02", (label,), (incident("profitability", "cpa_drift", entity, 61),)
    )
    confident_wrong = confident_wrong.model_copy(
        update={"agent": agent("mix_shift", "store", "high")}
    )
    healthy = outcome(
        "dev-healthy-01",
        (),
        (incident("profitability", "mix_shift", "store", 70, alert="watchlist"),),
    )
    healthy = healthy.model_copy(update={"agent": agent("mix_shift", "store", "low")})
    no_agent = outcome(
        "dev-cpa_drift-03", (label,), (incident("profitability", "cpa_drift", entity, 61),)
    )
    outcomes = [
        corrected,
        confident_wrong,
        healthy,
        no_agent.model_copy(update={"agent_error": "boom"}),
    ]
    return [o.model_copy(update={"agent_arm": True}) for o in outcomes]


def test_agent_scoring_and_summary() -> None:
    outcomes = scenarios()
    judgements = [judge(o) for o in outcomes]  # type: ignore[arg-type]
    first, second, healthy, failed = judgements
    assert (first.top1, first.agent_top1, first.agent_changed_top1) == (False, True, True)
    assert (second.top1, second.agent_top1, second.agent_confidence) == (True, False, "high")
    assert healthy.agent_top1 is None
    assert (failed.agent_status, failed.agent_error) == (None, True)
    # Not investigated: scored on the pipeline's ranking, like the baseline.
    assert (failed.agent_fallback, failed.agent_top1, failed.agent_top3) == (True, True, True)
    summary = summarize(judgements, outcomes)  # type: ignore[arg-type]
    a = summary["agent"]
    assert a is not None
    assert (a["investigations"], a["errors"]) == (3, 1)
    assert (a["top1"], a["top3"], a["confident_errors"]) == (0.6667, 0.6667, 0.5)
    assert (a["scored_without_investigation"], a["investigated_faulty"]) == (1, 2)
    assert (a["investigated_top1"], a["investigated_baseline_top1"]) == (0.5, 0.5)
    assert a["accuracy_by_confidence"]["high"] == {"n": 1, "accuracy": 0.0}
    assert a["accuracy_by_confidence"]["medium"] == {"n": 1, "accuracy": 1.0}
    assert (a["changed_top1"], a["changed_top1_helped"], a["changed_top1_hurt"]) == (2, 1, 1)
    assert (a["wrong"], a["wrong_downgraded"]) == (1, 0)
    assert a["unstable_share"] == round(1 / 3, 4)
    assert a["robustness_coverage"] == 1.0
    assert a["escalated_share"] == round(1 / 3, 4)
    assert Decimal(a["standard_cost_usd_mean"]) == Decimal("0.02")
    assert (a["final_violations"], a["rejected_violations"]) == (0, 3)
    stage = a["per_stage"]["escalation"]
    assert (stage["investigations"], stage["cache_hit_rate"]) == (1, 0.6)
    md = "\n".join(agent_section(summary))
    assert "| Deterministic baseline | 67% |" in md
    assert "| Deterministic + agent | 67% |" in md
    assert "On the 2 investigated faulty scenarios alone" in md
    assert "| escalation | 1 | 4 |" in md


def test_audit_proposals() -> None:
    outcomes = scenarios()
    judgements = [judge(o) for o in outcomes]  # type: ignore[arg-type]
    text = render_proposals(STARTED, judgements, outcomes)  # type: ignore[arg-type]
    assert "1 `cpa_drift` scenario(s) where the detectors ranked `tracking_break` first" in text
    assert "re-ranked to `mix_shift`" in text
    both_wrong = text.split("## Where the detectors and the investigation were both wrong")[1]
    assert both_wrong.split("##")[0].strip() == "None."
    assert "| cpa_drift | weak_evidence | 2 |" in text
    assert "| cpa_drift | 1 |" in text  # one unstable conclusion
    assert summarize([], [])["agent"] is None
