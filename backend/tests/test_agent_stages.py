"""Stage configuration, routing and tool-result compaction (no database)."""

import json
from pathlib import Path

import pytest

from app.agent.llm.models import DataOrigin, ModelId, ReasoningEffort
from app.agent.stages import STAGES_FILE, Routing, Stage, load_stages
from app.agent.tools.base import TRUNCATED, compact


def test_stage_config_matches_the_task() -> None:
    cfg = load_stages()
    assert cfg.version == 1
    assert len(cfg.digest) == 16
    expected = {
        Stage.CLASSIFICATION: (ModelId.SPARK, ReasoningEffort.LOW),
        Stage.LOOKUP: (ModelId.SPARK, ReasoningEffort.LOW),
        Stage.INVESTIGATION: (ModelId.SPARK, ReasoningEffort.MEDIUM),
        Stage.ESCALATION: (ModelId.WONDER, ReasoningEffort.HIGH),
    }
    for stage, (model, effort) in expected.items():
        assert (cfg[stage].model, cfg[stage].reasoning_effort) == (model, effort)
        assert cfg[stage].max_output_tokens > 0
        assert cfg[stage].max_input_tokens > 0
    assert cfg[Stage.CLASSIFICATION].max_tool_calls == 0
    assert cfg.max_result_chars > 0


def test_routing() -> None:
    cfg = load_stages()
    prod = cfg.route(Stage.ESCALATION, DataOrigin.REAL, Routing.PRODUCTION, "ambiguous")
    assert (prod.model, prod.reasoning_effort, prod.reason) == (
        ModelId.WONDER,
        ReasoningEffort.HIGH,
        "ambiguous",
    )
    eco = cfg.route(Stage.ESCALATION, DataOrigin.SYNTHETIC, Routing.ECONOMY, "ambiguous")
    assert (eco.model, eco.reasoning_effort) == (ModelId.SPARK_CONTRIBUTOR, ReasoningEffort.HIGH)
    assert "economy" in eco.reason
    with pytest.raises(ValueError, match="synthetic"):
        cfg.route(Stage.INVESTIGATION, DataOrigin.REAL, Routing.ECONOMY, "x")


def test_digest_ignores_line_endings(tmp_path: Path) -> None:
    text = STAGES_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    lf, crlf = tmp_path / "lf.toml", tmp_path / "crlf.toml"
    lf.write_bytes(text.encode("utf-8"))
    crlf.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert load_stages.__wrapped__(lf).digest == load_stages.__wrapped__(crlf).digest
    broken = tmp_path / "broken.toml"
    broken.write_text(text.split("[stages.escalation]")[0] + "[tool_results]\nmax_chars = 1\n")
    with pytest.raises(ValueError, match="misses"):
        load_stages.__wrapped__(broken)


def test_compaction_cuts_the_longest_list_with_one_marker() -> None:
    result = {
        "items": [{"n": f"item {i}", "pad": "x" * 50} for i in range(40)],
        "short": ["a", "b"],
        "name": "kept",
    }
    small, truncated = compact(result, 1200)
    assert truncated
    assert len(json.dumps(small)) <= 1200
    assert small["items"][-1] == TRUNCATED
    assert small["items"].count(TRUNCATED) == 1
    assert small["items"][0] == result["items"][0]  # the first (best) items are kept
    assert small["short"] == ["a", "b"]
    assert small["name"] == "kept"
    same, untouched = compact(result, 10**6)
    assert (same, untouched) == (result, False)
    nothing_to_cut, flagged = compact({"text": "x" * 500}, 100)
    assert (nothing_to_cut, flagged) == ({"text": "x" * 500}, False)
