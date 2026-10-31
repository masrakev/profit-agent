"""The golden questions before and after attaching citations in code (bench/citation_attach.py)."""

import json
from pathlib import Path
from typing import Any

from bench.citation_attach import load, main, run_stats


def question(passed: bool, regenerations: int, attached: int | None, failed: list[str]) -> Any:
    q: dict[str, Any] = {
        "status": "answered",
        "passed": passed,
        "regenerations": regenerations,
        "failed_checks": failed,
    }
    if attached is not None:
        q["citations_attached"] = attached
    return q


def write_run(folder: Path, name: str, questions: list[Any], cost: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    passed = sum(q["passed"] for q in questions)
    summary = {
        "passed": passed,
        "active": len(questions),
        "verifier_violations_in_answers": 0,
        "cost_usd": cost,
    }
    questions = [*questions, {"pending": "needs a decision"}]
    (folder / name).write_text(json.dumps({"summary": summary, "questions": questions}))


def test_runs_before_and_after(tmp_path: Path) -> None:
    for i in range(3):
        write_run(
            tmp_path / "before",
            f"golden-b{i}-economy.json",
            [
                question(True, 2, None, []),
                question(False, 1, None, ["reference:cpa (cited ['roas'])", "mention:x"]),
            ],
            "0.05",
        )
        write_run(
            tmp_path / "after",
            f"golden-a{i}-economy.json",
            [question(True, 0, 2, []), question(True, 1, 0, [])],
            "0.04",
        )
    one = run_stats(tmp_path / "before" / "golden-b0-economy.json")
    assert (one.passed, one.active, one.answered, one.regenerations) == (1, 2, 2, 3)
    assert one.regenerated_answers == 2
    assert one.failed == {"mention": 1, "reference": 1}
    runs = load(tmp_path)
    assert [r.attached for r in runs["after"]] == [2, 2, 2]
    assert main(["--runs", str(tmp_path), "--out", str(tmp_path)]) == 0
    text = (tmp_path / "citation-attach.md").read_text(encoding="utf-8")
    assert "| before | 50.0% (50.0% to 50.0%) | 3.0 (3.0 to 3.0) |" in text
    assert "| `golden-a0-economy` | f1c146b | 2 / 2 | 100% | 1 | 1 / 2 | 2 | 1 | 0 |" in text
    assert "code attached 6 citations in 3 answers" in text
    assert "Of the 0 failed checks after, 0 are `reference` checks" in text
