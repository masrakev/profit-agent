"""Scenario manifests: generator config + seed + faults (and conditions) + ground-truth labels,
stored as JSON."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from bench.faults import AnyFault, FaultLabel
from bench.faults.conditions import AnyCondition, ConditionLabel
from bench.generator import GeneratedStore, GeneratorConfig, generate
from bench.generator.faults import fault_rng
from bench.generator.model import Intervention, Restock

SCENARIO_DIR = Path(__file__).resolve().parent
# dev: tuning only. test_v3: reported once the agent and thresholds are frozen.
# golden: named scenarios for the golden question set (bench/golden/questions.yaml).
# outcomes_v1: fresh stores for validating the calibrated outcome intervals, reported once.
# goals_dev: 400-day stores for tuning goal forecasts. goals_test: the same, reported once.
Suite = Literal["dev", "test_v3", "golden", "outcomes_v1", "goals_dev", "goals_test"]
CONDITION_STREAM = 100  # random streams of conditions start after those of faults


class ScenarioManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    suite: Suite
    description: str
    config: GeneratorConfig
    faults: tuple[AnyFault, ...] = ()
    labels: tuple[FaultLabel, ...] = ()
    conditions: tuple[AnyCondition, ...] = ()
    condition_labels: tuple[ConditionLabel, ...] = ()

    @property
    def is_healthy(self) -> bool:
        return not self.faults

    def generate(self, interventions: Sequence[Intervention | Restock] = ()) -> GeneratedStore:
        data = generate(self.config, faults=self.faults, interventions=interventions)
        for index, condition in enumerate(self.conditions):
            rng = fault_rng(self.config.seed, CONDITION_STREAM + index, condition)
            data = condition.apply(data, rng)
        return data

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def suite_dir(suite: Suite) -> Path:
    return SCENARIO_DIR / suite


def load_suite(suite: Suite) -> list[ScenarioManifest]:
    paths = sorted(suite_dir(suite).glob("*.json"))
    return [ScenarioManifest.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]


def save(manifest: ScenarioManifest) -> Path:
    path = suite_dir(manifest.suite) / f"{manifest.scenario_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.to_json(), encoding="utf-8", newline="\n")
    return path
