"""Golden scenarios: every scenario the golden question set needs exists or is pending, and
label placeholders in questions resolve from the scenario's ground truth."""

import re
from pathlib import Path

import yaml

from app.facts.model import ScopeKind
from bench.faults.conditions import ConditionKind
from bench.scenarios.manifest import ScenarioManifest, load_suite

GOLDEN = Path(__file__).resolve().parents[2] / "bench" / "golden"
PLACEHOLDER = re.compile(r"label\.(campaign|product)")


def questions() -> list[dict[str, object]]:
    data = yaml.safe_load((GOLDEN / "questions.yaml").read_text(encoding="utf-8"))
    assert data["version"] == 1
    return list(data["questions"])


def pending() -> dict[str, str]:
    return dict(yaml.safe_load((GOLDEN / "pending.yaml").read_text(encoding="utf-8"))["pending"])


def entity_kinds(manifest: ScenarioManifest) -> set[ScopeKind]:
    labels = [*manifest.labels, *manifest.condition_labels]
    return {e.kind for label in labels for e in label.entities}


def test_every_referenced_scenario_exists_or_is_pending() -> None:
    golden = {m.scenario_id for m in load_suite("golden")}
    referenced = {str(q["scenario"]) for q in questions()}
    missing = referenced - golden - set(pending())
    assert not missing, f"golden scenarios neither built nor pending: {sorted(missing)}"
    assert set(pending()) <= referenced  # nothing listed as pending without a question
    assert not set(pending()) & golden


def test_label_placeholders_resolve() -> None:
    golden = {m.scenario_id: m for m in load_suite("golden")}
    for q in questions():
        scenario = golden.get(str(q["scenario"]))
        if scenario is None:
            continue  # pending
        text = " ".join(map(str, [q["question"], *q.get("must_mention", [])]))  # type: ignore[list-item]
        for kind in PLACEHOLDER.findall(text):
            assert ScopeKind(kind) in entity_kinds(scenario), (q["id"], kind)


def test_golden_suite_composition() -> None:
    golden = {m.scenario_id: m for m in load_suite("golden")}
    assert golden["healthy-a"].is_healthy
    assert golden["healthy-b"].is_healthy
    faults = {m.labels[0].fault_type.value for m in golden.values() if m.labels}
    assert len(faults) == 8
    assert golden["golden-underfunded_campaign"].condition_labels[0].kind is (
        ConditionKind.UNDERFUNDED_CAMPAIGN
    )
    assert golden["golden-injection"].condition_labels[0].kind is ConditionKind.PROMPT_INJECTION
    overspent = golden["golden-past_optimal_budgets"]  # revenue goals whose plan costs profit
    assert overspent.is_healthy
    assert overspent.config.campaign_budget_policy == "past_optimal"
