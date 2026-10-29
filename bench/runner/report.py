"""Benchmark reports: a full JSON report per run and a `latest.md` summary."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from bench.runner.run import ScenarioOutcome
from bench.runner.score import Judgement

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"


def _pct(value: object) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.0f}%"  # type: ignore[arg-type]


def _num(value: object) -> str:
    return "n/a" if value is None else str(value)


def render_markdown(
    suite: str,
    started: datetime,
    summary: dict[str, object],
    judgements: list[Judgement],
    outcomes: list[ScenarioOutcome],
    total_runtime_s: float,
    thresholds_version: int,
) -> str:
    overall = summary["overall"]
    per_type = summary["per_fault_type"]
    assert isinstance(overall, dict)
    assert isinstance(per_type, dict)
    lines = [
        f"# Benchmark report: `{suite}` suite",
        "",
        f"Run {started.isoformat()} - thresholds v{thresholds_version} - "
        f"{overall['scenarios']} scenarios - total runtime {total_runtime_s:.1f} s "
        f"(mean {overall['runtime_per_scenario_s']['mean']} s, "
        f"max {overall['runtime_per_scenario_s']['max']} s per scenario).",
        "",
        "## Overall (faulty scenarios)",
        "",
        "| Top-1 | Top-3 | Detection | Mean delay (days) | Attribution: largest negative | "
        "Attribution: significant | Tracking breaks as data quality | Errors |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| {_pct(overall['top1'])} | {_pct(overall['top3'])} | "
        f"{_pct(overall['detection_rate'])} | {_num(overall['mean_delay_days'])} | "
        f"{_pct(overall['attribution_check'])} | {_pct(overall['attribution_significant'])} | "
        f"{_pct(overall['tracking_classified_dq'])} | {overall['errors']} |",
        "",
        "## Alerting",
        "",
        "| False profit alerts (healthy) | Alert precision | Profit alerts per healthy store-month "
        "| Alerts | Materiality-gated incidents per scenario | Incidents by level |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {overall['false_alerts']} / {overall['healthy_scenarios']} | "
        f"{_pct(overall['alert_precision'])} | "
        f"{_num(overall['profit_alerts_per_healthy_store_month'])} | {overall['alerts']} | "
        f"{_num(overall['gated_incidents_per_scenario'])} | "
        + ", ".join(f"{k} {v}" for k, v in overall["severity_distribution"].items())
        + " |",
        "",
        "## Per fault type",
        "",
        "| Fault type | n | Top-1 | Top-3 | Detection | Median delay | Attribution check | Other |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for fault_type, m in per_type.items():
        assert isinstance(m, dict)
        other = ""
        if fault_type == "healthy":
            other = f"false profit alerts {m['false_alerts']} / {m['scenarios']}"
        elif fault_type == "tracking_break":
            other = f"classified as data quality {_pct(m['tracking_classified_dq'])}"
        if fault_type == "healthy":
            lines.append(f"| healthy | {m['scenarios']} | - | - | - | - | - | {other} |")
            continue
        lines.append(
            f"| {fault_type} | {m['scenarios']} | {_pct(m['top1'])} | {_pct(m['top3'])} | "
            f"{_pct(m['detection_rate'])} | {_num(m['median_delay_days'])} | "
            f"{_pct(m['attribution_check'])} | {other} |"
        )
    lines += agent_section(summary)
    lines += ["", "## Scenarios that failed", ""]
    outcome_by_id = {o.scenario_id: o for o in outcomes}
    failed = [
        j
        for j in judgements
        if j.error
        or j.false_alert
        or j.top1 is False
        or j.detected is False
        or j.tracking_classified_dq is False
        or j.attribution_ok is False
    ]
    if not failed:
        lines.append("None.")
    for j in failed:
        o = outcome_by_id[j.scenario_id]
        problems = [
            name
            for name, bad in (
                ("error", j.error),
                ("false alert", j.false_alert),
                ("not detected", j.detected is False),
                ("wrong top-1", j.top1 is False),
                ("not top-3", j.top3 is False),
                ("tracking break not data quality", j.tracking_classified_dq is False),
                ("attribution driver", j.attribution_ok is False),
            )
            if bad
        ]
        driver = o.attribution.largest_negative if o.attribution else None
        expected = o.labels[0].expected_driver if o.labels else None
        lines.append(
            f"- `{j.scenario_id}` ({o.description}): {', '.join(problems)}. "
            f"Primary: {j.primary or 'no incident'}; largest negative driver: {driver}"
            + (f" (expected {expected.value})" if expected else "")
            + "."
        )
    return "\n".join(lines) + "\n"


def agent_section(summary: dict[str, Any]) -> list[str]:
    """Baseline vs agent, side by side (Task 3 B4)."""
    agent = summary.get("agent")
    if not agent:
        return []
    o = summary["overall"]
    lines = [
        "",
        "## Agent (investigation of each primary incident)",
        "",
        "| | Top-1 | Top-3 | Tracking breaks as data quality | False profit alerts | Level-2 "
        "attribution in scope |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| Deterministic baseline | {_pct(o['top1'])} | {_pct(o['top3'])} | "
        f"{_pct(o['tracking_classified_dq'])} | {o['false_alerts']} / {o['healthy_scenarios']} | "
        f"{_pct(o.get('attribution_scope_check'))} |",
        f"| Deterministic + agent | {_pct(agent['top1'])} | {_pct(agent['top3'])} | "
        f"{_pct(agent['tracking_classified_dq'])} | {o['false_alerts']} / "
        f"{o['healthy_scenarios']} (the agent changes no alert) | n/a |",
        "",
        "Both rows count every faulty scenario; where nothing was investigated (no incident, or "
        f"the investigation failed: {agent['scored_without_investigation']} scenarios) the "
        "agent row keeps the pipeline's ranking. On the "
        f"{agent['investigated_faulty']} investigated faulty scenarios alone, top-1 is "
        f"{_pct(agent['investigated_baseline_top1'])} for the baseline and "
        f"{_pct(agent['investigated_top1'])} with the agent.",
        "",
        "| Investigations | Statuses | Confident errors | Unstable conclusions | Robustness check "
        "(by agent) | Wrong conclusions downgraded | Agent changed top-1 (helped / hurt) | "
        "Escalated |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| {agent['investigations']} | "
        + ", ".join(f"{k} {v}" for k, v in agent["statuses"].items())
        + f" | {_pct(agent['confident_errors'])} | {_pct(agent['unstable_share'])} | "
        f"{_pct(agent['robustness_coverage'])} ({_pct(agent['robustness_by_agent'])}) | "
        f"{agent['wrong_downgraded']} of {agent['wrong']} | {agent['changed_top1']} "
        f"({agent['changed_top1_helped']} / {agent['changed_top1_hurt']}) | "
        f"{_pct(agent['escalated_share'])} |",
        "",
        "| Confidence | Investigations | Top-1 accuracy |",
        "| --- | --- | --- |",
        *(
            f"| {level} | {v['n']} | {_pct(v['accuracy'])} |"
            for level, v in agent["accuracy_by_confidence"].items()
        ),
        "",
        "| Cost per investigation (USD) | At Standard prices | Latency (s) | Tool calls | "
        "Verifier violations (final / rejected) |",
        "| --- | --- | --- | --- | --- |",
        f"| {_num(agent['cost_usd_mean'])} | {_num(agent['standard_cost_usd_mean'])} | "
        f"{_num(agent['latency_s_mean'])} | {_num(agent['tool_calls_mean'])} | "
        f"{agent['final_violations']} / {agent['rejected_violations']} |",
        "",
        "| Stage | Investigations | Calls | Input | Cached | Output | Reasoning | Cost USD | "
        "At Standard prices | Mean latency (s) | Cache hit rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        *(
            f"| {stage} | {v['investigations']} | {v['calls']} | {v['input_tokens']} | "
            f"{v['cached_tokens']} | {v['output_tokens']} | {v['reasoning_tokens']} | "
            f"{v['cost_usd']} | {v['standard_cost_usd']} | {_num(v['latency_s_mean'])} | "
            f"{_pct(v['cache_hit_rate'])} |"
            for stage, v in agent["per_stage"].items()
        ),
        "",
        "| Fault type | Baseline top-1 | Agent top-1 | Baseline top-3 | Agent top-3 | Agent "
        "cost at Standard (USD) | Agent latency (s) | Escalated |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for fault, v in summary["per_fault_type"].items():
        lines.append(
            f"| {fault} | {_pct(v['top1'])} | {_pct(v['agent_top1'])} | {_pct(v['top3'])} | "
            f"{_pct(v['agent_top3'])} | {_num(v['agent_standard_cost_usd_mean'])} | "
            f"{_num(v['agent_latency_s_mean'])} | {_pct(v['agent_escalated_share'])} |"
        )
    return lines


def write_reports(
    suite: str,
    started: datetime,
    summary: dict[str, object],
    judgements: list[Judgement],
    outcomes: list[ScenarioOutcome],
    total_runtime_s: float,
    thresholds_version: int,
    out_dir: Path = REPORT_DIR,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    report = {
        "suite": suite,
        "started_at": started.isoformat(),
        "thresholds_version": thresholds_version,
        "total_runtime_s": round(total_runtime_s, 2),
        "summary": summary,
        "judgements": [j.model_dump(mode="json") for j in judgements],
        "scenarios": [o.model_dump(mode="json") for o in outcomes],
    }
    json_path = out_dir / f"{stamp}-{suite}.json"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    md = render_markdown(
        suite, started, summary, judgements, outcomes, total_runtime_s, thresholds_version
    )
    md_path = out_dir / ("latest.md" if suite == "test_v3" else f"latest-{suite}.md")
    md_path.write_text(md, encoding="utf-8", newline="\n")
    return json_path, md_path
