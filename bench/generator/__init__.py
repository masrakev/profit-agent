"""Deterministic synthetic store generator for benchmarks and demos."""

from bench.generator.config import GeneratorConfig, LongHistory
from bench.generator.faults import Fault, apply_faults
from bench.generator.model import GeneratedStore, Intervention, Restock
from bench.generator.simulate import generate

__all__ = [
    "Fault",
    "GeneratedStore",
    "GeneratorConfig",
    "Intervention",
    "LongHistory",
    "Restock",
    "apply_faults",
    "generate",
]
