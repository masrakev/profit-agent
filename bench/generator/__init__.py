"""Deterministic synthetic store generator for benchmarks and demos."""

from bench.generator.config import GeneratorConfig
from bench.generator.faults import Fault, apply_faults
from bench.generator.model import GeneratedStore
from bench.generator.simulate import generate

__all__ = ["Fault", "GeneratedStore", "GeneratorConfig", "apply_faults", "generate"]
