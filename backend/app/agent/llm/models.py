"""Models, data-usage modes, token usage and cost accounting.

Contributor mode lets Meta train on prompts and responses, so it is allowed only for synthetic
benchmark data (`DataOrigin.SYNTHETIC`). Real store data always goes to a Standard-mode model.
"""

import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from app.agent.llm.errors import ContributorModeForbiddenError

PRICES_FILE = Path(__file__).with_name("prices_v1.toml")
PER_TOKENS = Decimal(1_000_000)


class ModelId(StrEnum):
    SPARK = "muse-spark-1.3"
    SPARK_CONTRIBUTOR = "muse-spark-1.3-contributor"
    WONDER = "muse-wonder-1.0"


class DataMode(StrEnum):
    STANDARD = "standard"  # content is not used for training
    CONTRIBUTOR = "contributor"  # content may be used to train future Meta models


class DataOrigin(StrEnum):
    """Where the data in a prompt comes from. Derive it from the store row
    (`stores.synthetic`), never from the caller's say-so."""

    SYNTHETIC = "synthetic"  # benchmark stores built by the generator
    REAL = "real"


class ReasoningEffort(StrEnum):
    # "none" is rejected by every Muse model (HTTP 400), so it is not offered.
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"  # Spark 1.3 and Wonder only


@dataclass(frozen=True)
class ModelSpec:
    model_id: ModelId
    mode: DataMode
    efforts: frozenset[ReasoningEffort]


_ALL_EFFORTS = frozenset(ReasoningEffort)
MODELS: dict[ModelId, ModelSpec] = {
    ModelId.SPARK: ModelSpec(ModelId.SPARK, DataMode.STANDARD, _ALL_EFFORTS),
    ModelId.SPARK_CONTRIBUTOR: ModelSpec(
        ModelId.SPARK_CONTRIBUTOR, DataMode.CONTRIBUTOR, _ALL_EFFORTS - {ReasoningEffort.MAX}
    ),
    ModelId.WONDER: ModelSpec(ModelId.WONDER, DataMode.STANDARD, _ALL_EFFORTS),
}


def check_data_policy(model: ModelId, origin: DataOrigin) -> None:
    """Refuse Contributor mode for anything but synthetic data."""
    if MODELS[model].mode is DataMode.CONTRIBUTOR and origin is not DataOrigin.SYNTHETIC:
        raise ContributorModeForbiddenError(
            f"{model} is a Contributor-mode model: real store data must use Standard mode"
        )


@dataclass(frozen=True)
class Usage:
    """Token counts as reported in `usage`. Cached tokens are part of the input tokens and
    reasoning tokens part of the output tokens."""

    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.cached_tokens + other.cached_tokens,
            self.output_tokens + other.output_tokens,
            self.reasoning_tokens + other.reasoning_tokens,
        )


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input: Decimal
    cached_input: Decimal
    output: Decimal


@dataclass(frozen=True)
class PriceTable:
    version: int
    verified_on: date
    source: str
    prices: dict[ModelId, Price]

    def price(self, model: ModelId) -> Price:
        return self.prices[model]

    def cost(self, model: ModelId, usage: Usage) -> Decimal:
        """Exact USD cost of one call: uncached input, cached input and output (reasoning
        included) at their rates."""
        p = self.prices[model]
        uncached = usage.input_tokens - usage.cached_tokens
        return (
            Decimal(uncached) * p.input
            + Decimal(usage.cached_tokens) * p.cached_input
            + Decimal(usage.output_tokens) * p.output
        ) / PER_TOKENS

    def upper_bound(self, model: ModelId, input_tokens: int, max_output_tokens: int) -> Decimal:
        """The most a call can cost: every input token uncached, every output token used."""
        p = self.prices[model]
        return (Decimal(input_tokens) * p.input + Decimal(max_output_tokens) * p.output) / (
            PER_TOKENS
        )


@lru_cache(maxsize=1)
def load_prices(path: Path = PRICES_FILE) -> PriceTable:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    prices: dict[ModelId, Price] = {}
    for entry in raw["models"].values():
        model = ModelId(entry["id"])
        if DataMode(entry["mode"]) is not MODELS[model].mode:
            raise ValueError(f"price table mode of {model} disagrees with the model catalogue")
        prices[model] = Price(
            Decimal(entry["input"]), Decimal(entry["cached_input"]), Decimal(entry["output"])
        )
    missing = set(ModelId) - set(prices)
    if missing:
        raise ValueError(f"price table misses {sorted(missing)}")
    return PriceTable(int(raw["version"]), raw["verified_on"], str(raw["source"]), prices)
