"""Detector improvement proposals from the agent's audits (SPEC section 15).

Written only from `dev` runs, to bench/reports/audit_proposals.md, for human review: nothing is
applied automatically. A proposal names a pattern where investigations overturned the
deterministic ranking and were right; any detector change must then be tuned on `dev` and
evaluated on a new hold-out suite.
"""

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from bench.runner.run import ScenarioOutcome
from bench.runner.score import Judgement


def render_proposals(
    started: datetime, judgements: list[Judgement], outcomes: list[ScenarioOutcome]
) -> str:
    by_id = {o.scenario_id: o for o in outcomes}
    helped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    hurt: dict[tuple[str, str], list[str]] = defaultdict(list)
    findings: Counter[tuple[str, str]] = Counter()
    unstable: Counter[str] = Counter()
    for j in judgements:
        o = by_id[j.scenario_id]
        if o.agent is None:
            continue
        for kind in o.agent.audit_findings:
            findings[(j.fault_type, kind)] += 1
        if j.agent_stable is False:
            unstable[j.fault_type] += 1
        primary = o.incidents[0] if o.incidents else None
        det = primary.candidates[0].family if primary and primary.candidates else "none"
        detectors = ", ".join(primary.detectors) if primary else "none"
        if j.agent_changed_top1 and j.agent_top1:
            helped[(j.fault_type, det, detectors)].append(j.scenario_id)
        elif j.agent_changed_top1 and not j.agent_top1:
            agent_top = o.agent.hypotheses[0].family if o.agent.hypotheses else "none"
            hurt[(j.fault_type, agent_top)].append(j.scenario_id)
    lines = [
        "# Audit proposals (for human review)",
        "",
        f"Generated from the `dev` agent run of {started.isoformat()}. Nothing here is applied "
        "automatically: a detector change is tuned on `dev`, then evaluated on a new hold-out.",
        "",
        "## Where the investigation corrected the detectors",
        "",
    ]
    if not helped:
        lines.append("None.")
    for (fault, det, detectors), ids in sorted(helped.items(), key=lambda kv: -len(kv[1])):
        lines.append(
            f"- {len(ids)} `{fault}` scenario(s) where the detectors ranked `{det}` first "
            f"(primary incident from {detectors}) and the investigation found `{fault}`. "
            f"Proposal: review how these detectors separate `{det}` from `{fault}`. "
            f"Scenarios: {', '.join(f'`{i}`' for i in ids)}."
        )
    lines += ["", "## Where the investigation overturned a correct ranking (agent issues)", ""]
    if not hurt:
        lines.append("None.")
    for (fault, agent_top), ids in sorted(hurt.items(), key=lambda kv: -len(kv[1])):
        lines.append(
            f"- {len(ids)} `{fault}` scenario(s) re-ranked to `{agent_top}`: review the "
            f"investigator prompt or routing. Scenarios: {', '.join(f'`{i}`' for i in ids)}."
        )
    lines += [
        "",
        "## Audit findings by fault type",
        "",
        "| Fault type | Finding | Count |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {f} | {k} | {n} |" for (f, k), n in sorted(findings.items())]
    lines += [
        "",
        "## Unstable conclusions by fault type",
        "",
        "| Fault type | Count |",
        "| --- | --- |",
    ]
    lines += [f"| {f} | {n} |" for f, n in sorted(unstable.items())]
    return "\n".join(lines) + "\n"


def write_proposals(
    started: datetime, judgements: list[Judgement], outcomes: list[ScenarioOutcome], out: Path
) -> Path:
    path = out / "audit_proposals.md"
    path.write_text(render_proposals(started, judgements, outcomes), encoding="utf-8")
    return path
