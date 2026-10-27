"""Scenario manifests: generator config + seed + faults + ground-truth labels, stored as JSON."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from bench.faults import AnyFault, FaultLabel
from bench.generator import GeneratedStore, GeneratorConfig, generate

SCENARIO_DIR = Path(__file__).resolve().parent
Suite = Literal["dev", "test"]


class ScenarioManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    suite: Suite
    description: str
    config: GeneratorConfig
    faults: tuple[AnyFault, ...] = ()
    labels: tuple[FaultLabel, ...] = ()

    @property
    def is_healthy(self) -> bool:
        return not self.faults

    def generate(self) -> GeneratedStore:
        return generate(self.config, faults=self.faults)

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
