"""Deterministic synthetic store generator for benchmarks and demos."""

from bench.generator.config import GeneratorConfig
from bench.generator.faults import Fault, apply_faults
from bench.generator.model import GeneratedStore, Intervention
from bench.generator.simulate import generate

__all__ = [
    "Fault",
    "GeneratedStore",
    "GeneratorConfig",
    "Intervention",
    "apply_faults",
    "generate",
]
