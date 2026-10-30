"""The briefing cost report (bench/briefing_costs.py): summary per type and the table."""

from typing import Any

from bench.briefing_costs import markdown, summarize


def row(kind: str, cost: str, status: str = "narrated", **overrides: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "scenario": "golden-x",
        "kind": kind,
        "status": status,
        "model": "muse-spark-1.3",
        "attempts": 1,
        "input_tokens": 1000,
        "output_tokens": 300,
        "cost_usd": cost,
        "facts": 12,
        "sections": 4,
        "fallback_reason": None if status == "narrated" else "its output failed verification",
    }
    out.update(overrides)
    return out


def test_summary_and_report() -> None:
    rows = [
        row("daily", "0.002000"),
        row("daily", "0.004000", input_tokens=3000, attempts=2),
        row("weekly", "0.010000", status="facts_only"),
    ]
    summary = summarize(rows)
    assert summary["daily"] == {
        "briefings": 2,
        "narrated": 2,
        "mean_cost_usd": "0.003000",
        "max_cost_usd": "0.004000",
        "mean_input_tokens": 2000,
        "mean_output_tokens": 300,
        "mean_attempts": 1.5,
    }
    assert summary["weekly"]["narrated"] == 0
    assert "monthly" not in summary
    report = markdown("briefing-costs-x", rows, summary)
    assert "| daily | 2 | 2 | 0.003000 | 0.004000 | 2000 | 300 | 1.5 |" in report
    assert "Total cost of the run: USD 0.016000." in report
    assert "- golden-x weekly: its output failed verification" in report
