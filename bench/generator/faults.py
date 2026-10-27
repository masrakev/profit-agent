"""Fault injection protocol. Concrete faults arrive in Task 2.

A fault is a pure transformation of generated data: no I/O, no global state, and all randomness
from the generator it is given. Applying the same faults to the same data with the same seed
always yields the same result.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np

from app.domain.hashing import sha256_hex
from bench.generator.model import GeneratedStore


@runtime_checkable
class Fault(Protocol):
    @property
    def name(self) -> str: ...

    def apply(self, data: GeneratedStore, rng: np.random.Generator) -> GeneratedStore:
        """Return a new `GeneratedStore`; never mutate `data`. Keep references consistent."""
        ...


def fault_rng(seed: int, index: int, fault: Fault) -> np.random.Generator:
    """Independent stream per fault, stable under reordering of unrelated faults' internals."""
    name_key = int(sha256_hex(fault.name)[:16], 16)
    return np.random.default_rng([seed, index, name_key])


def apply_faults(data: GeneratedStore, faults: Sequence[Fault], seed: int) -> GeneratedStore:
    for index, fault in enumerate(faults):
        data = fault.apply(data, fault_rng(seed, index, fault))
    return data
