"""Per-stage model configuration and routing (ADR 0011, ADR 0013)."""

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path

from app.agent.llm.models import DataOrigin, ModelId, ReasoningEffort
from app.domain.hashing import sha256_hex

STAGES_FILE = Path(__file__).with_name("stages.toml")


class Stage(StrEnum):
    CLASSIFICATION = "classification"
    INTENT = "intent"
    LOOKUP = "lookup"
    EXPLANATION = "explanation"
    BRIEFING = "briefing"
    INVESTIGATION = "investigation"
    ESCALATION = "escalation"


class Routing(StrEnum):
    PRODUCTION = "production"  # the stage's model (Spark, Wonder on escalation)
    ECONOMY = "economy"  # Contributor model on synthetic stores (benchmark cost control)


@dataclass(frozen=True)
class StageConfig:
    stage: Stage
    model: ModelId
    reasoning_effort: ReasoningEffort
    max_output_tokens: int
    max_tool_calls: int
    max_input_tokens: int


@dataclass(frozen=True)
class Route:
    stage: Stage
    model: ModelId
    reasoning_effort: ReasoningEffort
    reason: str


@dataclass(frozen=True)
class StagesConfig:
    version: int
    digest: str  # content hash of the file, part of cache keys
    stages: dict[Stage, StageConfig]
    max_result_chars: int

    def __getitem__(self, stage: Stage) -> StageConfig:
        return self.stages[stage]

    def route(self, stage: Stage, origin: DataOrigin, routing: Routing, reason: str) -> Route:
        cfg = self.stages[stage]
        model = cfg.model
        if routing is Routing.ECONOMY:
            if origin is not DataOrigin.SYNTHETIC:
                raise ValueError("economy routing is only for synthetic benchmark stores")
            model = ModelId.SPARK_CONTRIBUTOR
            reason = f"{reason}; economy routing (synthetic store)"
        return Route(stage, model, cfg.reasoning_effort, reason)


@cache
def load_stages(path: Path = STAGES_FILE) -> StagesConfig:
    content = path.read_text(encoding="utf-8")
    raw = tomllib.loads(content)
    stages = {
        Stage(name): StageConfig(
            stage=Stage(name),
            model=ModelId(entry["model"]),
            reasoning_effort=ReasoningEffort(entry["reasoning_effort"]),
            max_output_tokens=int(entry["max_output_tokens"]),
            max_tool_calls=int(entry["max_tool_calls"]),
            max_input_tokens=int(entry["max_input_tokens"]),
        )
        for name, entry in raw["stages"].items()
    }
    missing = set(Stage) - set(stages)
    if missing:
        raise ValueError(f"stages.toml misses {sorted(missing)}")
    return StagesConfig(
        version=int(raw["version"]),
        digest=sha256_hex(content.replace(chr(13), ""))[:16],  # same digest on any OS
        stages=stages,
        max_result_chars=int(raw["tool_results"]["max_chars"]),
    )
