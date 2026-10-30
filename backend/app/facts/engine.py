"""Fact engine: evaluates registered formulas for a store and persists facts with lineage."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, select

from app.domain.schema import stores
from app.facts import sql
from app.facts.formulas import REGISTRY
from app.facts.model import Fact, FactStatus, Period, Scope, ScopeKind
from app.facts.registry import FormulaRegistry, UnsupportedScopeError
from app.facts.repository import save_fact


@dataclass(frozen=True)
class PersistReport:
    inserted: int
    existing: int


class FactEngine:
    """Computes facts for one store. Use inside that store's tenant transaction.

    Results are memoized per `(formula, scope, period)`, so shared parents are computed once.
    """

    def __init__(
        self, conn: Connection, store_id: UUID, registry: FormulaRegistry = REGISTRY
    ) -> None:
        currency = conn.execute(
            select(stores.c.currency).where(stores.c.store_id == store_id)
        ).scalar_one_or_none()
        if currency is None:
            raise LookupError(f"store {store_id} does not exist or is not visible to this tenant")
        self._conn = conn
        self._store_id = store_id
        self._currency = str(currency)
        self._registry = registry
        self._cache: dict[tuple[str, Scope, Period], Fact] = {}
        self._by_hash: dict[str, Fact] = {}
        self._ids: dict[str, int] = {}
        self._report = [0, 0]  # [inserted, already existing]

    @property
    def conn(self) -> Connection:
        return self._conn

    @property
    def store_id(self) -> UUID:
        return self._store_id

    @property
    def currency(self) -> str:
        return self._currency

    def fact(self, formula_id: str, scope: Scope, period: Period) -> Fact:
        key = (formula_id, scope, period)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        formula = self._registry.get(formula_id)
        if scope.kind not in formula.scopes:
            raise UnsupportedScopeError(f"{formula_id} is not defined for {scope.kind} scope")
        out = formula.compute(self, scope, period)
        fact = Fact(
            store_id=self._store_id,
            formula_id=formula.formula_id,
            formula_version=formula.version,
            kind=formula.kind,
            scope=scope,
            period=period,
            status=FactStatus.DEFINED if out.undefined_reason is None else FactStatus.UNDEFINED,
            value=out.value if out.undefined_reason is None else None,
            unit=formula.unit,
            currency=out.currency,
            undefined_reason=out.undefined_reason,
            inputs_hash=out.inputs_hash,
            lineage=out.lineage,
        )
        self._cache[key] = fact
        self._by_hash[fact.fact_hash] = fact
        return fact

    def compute_all(self, period: Period) -> list[Fact]:
        """Every registered formula for the store, each product and each campaign."""
        scopes: dict[ScopeKind, list[Scope]] = {
            ScopeKind.STORE: [Scope.store()],
            ScopeKind.PRODUCT: [
                Scope.product(p) for p in sql.product_ids(self._conn, self._store_id)
            ],
            ScopeKind.CAMPAIGN: [
                Scope.campaign(c) for c in sql.campaign_ids(self._conn, self._store_id)
            ],
        }
        return [
            self.fact(formula.formula_id, scope, period)
            for formula in self._registry
            for kind in sorted(formula.scopes)
            for scope in scopes[kind]
        ]

    def adopt(self, fact: Fact) -> Fact:
        """Register a fact built outside the registry (e.g. a Shapley contribution) so that facts
        naming it as a parent can be persisted. A fact read back with its id is already
        persisted, with its parents: it is not written again."""
        self._by_hash.setdefault(fact.fact_hash, fact)
        if fact.id is not None:
            self._ids.setdefault(fact.fact_hash, fact.id)
        return fact

    def persist(self, fact: Fact) -> Fact:
        """Persist `fact` and, before it, its parents. Returns the fact with its id."""
        known = self._ids.get(fact.fact_hash)
        if known is None:
            for parent in fact.lineage.parents:
                self.persist(self._by_hash[parent.fact_hash])
            known, inserted = save_fact(self._conn, fact, self._ids)
            self._ids[fact.fact_hash] = known
            self._report[0 if inserted else 1] += 1
        return fact.model_copy(update={"id": known})

    def persist_all(self, facts: list[Fact]) -> tuple[list[Fact], PersistReport]:
        """Persist facts and their parents; the report counts every fact written, parents too."""
        self._report = [0, 0]
        saved = [self.persist(fact) for fact in facts]
        return saved, PersistReport(inserted=self._report[0], existing=self._report[1])
