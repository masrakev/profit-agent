"""Unit economics generated from measured costs (bench/unit_economics.py)."""

import json
from decimal import Decimal
from pathlib import Path

from bench.unit_economics import (
    BEGIN,
    END,
    PROFILES,
    ledger_totals,
    measure,
    profile_row,
    readiness_block,
    report,
    update_readiness,
)


def write_reports(folder: Path) -> None:
    golden = {
        "meta": {"started": "2026-10-30T09:23:09+00:00", "routing": "production"},
        "summary": {
            "cost_usd": "0.04",
            "investigations": {
                "n": 2,
                "cost_usd": "0.20",
                "standard_cost_usd_mean": "0.10",
                "cost_usd_max": "0.15",
            },
        },
        "questions": [
            {"usage": {"standard_cost_usd": "0.01"}},
            {"usage": {"standard_cost_usd": "0.03"}},
            {"pending": "needs a decision"},
        ],
    }
    (folder / "golden-20261030T092309Z-production.json").write_text(json.dumps(golden))
    rows = [
        {"kind": "daily", "cost_usd": "0.006"},
        {"kind": "daily", "cost_usd": "0.008"},
        {"kind": "weekly", "cost_usd": "0.012"},
        {"kind": "monthly", "cost_usd": "0.02"},
    ]
    (folder / "briefing-costs-20261030T175145Z.json").write_text(json.dumps({"rows": rows}))


def test_unit_economics(tmp_path: Path) -> None:
    write_reports(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            json.dumps({"run_id": "golden-20261030T092309Z", "amount": a})
            for a in ("0.30", "-0.06")
        )
    )
    m = measure(tmp_path, ledger_totals(ledger))
    assert (m.investigation_mean, m.investigation_max, m.investigations) == (
        Decimal("0.10"),
        Decimal("0.15"),
        2,
    )
    assert (m.answer_mean, m.answers) == (Decimal("0.02"), 2)
    assert m.briefing_mean["daily"] == Decimal("0.007")
    assert m.runs[0]["ledger_usd"] == Decimal("0.24") == m.runs[0]["reported_usd"]
    typical = profile_row(PROFILES[0], m)
    briefings = Decimal("0.007") * 26 + Decimal("0.012") * 4 + Decimal("0.02")
    assert typical["model"] == Decimal("0.10") * 10 + Decimal("0.02") * 30 + briefings
    assert typical["total"] == typical["model"] + Decimal("2.00") + Decimal("0.05") + Decimal(
        "1.77"
    )
    worst = profile_row(PROFILES[2], m)
    assert worst["model"] - profile_row(PROFILES[1], m)["model"] == Decimal("0.05") * 40
    assert "| Typical store | 10 | 30 |" in report(m)
    doc = tmp_path / "readiness.md"
    doc.write_text(f"# Doc\n\n{BEGIN}\nold estimates\n{END}\n\nAfter.\n")
    update_readiness(doc, readiness_block(m))
    text = doc.read_text()
    assert "old estimates" not in text
    assert "a daily brief USD 0.0070" in text
    assert text.endswith("\n\nAfter.\n")
    assert ledger_totals(tmp_path / "missing.jsonl") == {}
