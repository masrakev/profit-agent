"""Formula registry. A formula is identified by `(formula_id, version)`; any change to its
definition must bump the version, which changes the hash of every fact it produces."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import Connection

from app.facts.model import Fact, FactKind, Lineage, Period, Scope, ScopeKind, Unit


class FactContext(Protocol):
    """What a formula may use: the tenant connection, the store, and other facts."""

    @property
    def conn(self) -> Connection: ...

    @property
    def store_id(self) -> UUID: ...

    @property
    def currency(self) -> str: ...

    def fact(self, formula_id: str, scope: Scope, period: Period) -> Fact: ...


@dataclass(frozen=True)
class Computed:
    """Raw output of a formula, before the engine wraps it into a `Fact`."""

    value: Decimal | None
    currency: str | None
    inputs_hash: str
    lineage: Lineage = field(default_factory=Lineage)
    undefined_reason: str | None = None


ComputeFn = Callable[[FactContext, Scope, Period], Computed]


@dataclass(frozen=True)
class Formula:
    formula_id: str
    version: int
    kind: FactKind
    unit: Unit
    scopes: frozenset[ScopeKind]
    inputs: tuple[str, ...]
    description: str
    compute: ComputeFn


class UnknownFormulaError(KeyError):
    pass


class UnsupportedScopeError(ValueError):
    pass


class FormulaRegistry:
    def __init__(self) -> None:
        self._formulas: dict[str, Formula] = {}

    def register(self, formula: Formula) -> Formula:
        if formula.formula_id in self._formulas:
            raise ValueError(f"formula {formula.formula_id!r} is already registered")
        unknown = [i for i in formula.inputs if i not in self._formulas]
        if unknown:
            raise ValueError(f"formula {formula.formula_id!r} has unregistered inputs {unknown}")
        self._formulas[formula.formula_id] = formula
        return formula

    def get(self, formula_id: str) -> Formula:
        try:
            return self._formulas[formula_id]
        except KeyError:
            raise UnknownFormulaError(formula_id) from None

    def __iter__(self) -> Iterator[Formula]:
        return iter(self._formulas.values())

    def __len__(self) -> int:
        return len(self._formulas)

    def for_scope(self, kind: ScopeKind) -> list[Formula]:
        return [f for f in self._formulas.values() if kind in f.scopes]
