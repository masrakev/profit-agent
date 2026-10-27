"""Benchmark reports: a full JSON report per run and a `latest.md` summary."""

import json
from datetime import datetime
from pathlib import Path

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
        "| Top-1 | Top-3 | Detection | Mean delay (days) | Attribution check | "
        "False alerts (healthy) | Tracking breaks as data quality | Errors |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| {_pct(overall['top1'])} | {_pct(overall['top3'])} | "
        f"{_pct(overall['detection_rate'])} | {_num(overall['mean_delay_days'])} | "
        f"{_pct(overall['attribution_check'])} | {_pct(overall['false_alert_rate'])} | "
        f"{_pct(overall['tracking_classified_dq'])} | {overall['errors']} |",
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
            other = f"false alerts {_pct(m['false_alert_rate'])}"
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
    md_path = out_dir / ("latest.md" if suite == "test_v2" else f"latest-{suite}.md")
    md_path.write_text(md, encoding="utf-8", newline="\n")
    return json_path, md_path
