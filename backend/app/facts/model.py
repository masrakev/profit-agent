"""Fact value objects. A fact is immutable; its hash covers everything except its database id."""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from functools import cached_property
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.hashing import canonical_json, sha256_hex
from app.domain.models import UtcDatetime


class FactKind(StrEnum):
    EXACT = "exact"
    ESTIMATE = "estimate"


class ScopeKind(StrEnum):
    STORE = "store"
    PRODUCT = "product"
    CAMPAIGN = "campaign"


class Unit(StrEnum):
    MONEY = "money"
    COUNT = "count"
    RATIO = "ratio"
    DAYS = "days"


class FactStatus(StrEnum):
    DEFINED = "defined"
    UNDEFINED = "undefined"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Scope(_Frozen):
    kind: ScopeKind
    id: UUID | None = None

    @model_validator(mode="after")
    def _id_matches_kind(self) -> Self:
        if (self.kind is ScopeKind.STORE) != (self.id is None):
            raise ValueError("store scope has no id; product and campaign scopes require one")
        return self

    @classmethod
    def store(cls) -> "Scope":
        return cls(kind=ScopeKind.STORE)

    @classmethod
    def product(cls, product_id: UUID) -> "Scope":
        return cls(kind=ScopeKind.PRODUCT, id=product_id)

    @classmethod
    def campaign(cls, campaign_id: UUID) -> "Scope":
        return cls(kind=ScopeKind.CAMPAIGN, id=campaign_id)


class Period(_Frozen):
    """Half-open UTC interval `[start, end)`."""

    start: UtcDatetime
    end: UtcDatetime

    @model_validator(mode="after")
    def _non_empty(self) -> Self:
        if self.end <= self.start:
            raise ValueError("period end must be after start")
        return self

    @classmethod
    def days(cls, first: date, end_exclusive: date) -> "Period":
        """The UTC calendar days `first` through `end_exclusive - 1`."""
        return cls(
            start=datetime.combine(first, time(), tzinfo=UTC),
            end=datetime.combine(end_exclusive, time(), tzinfo=UTC),
        )


class SourceRef(_Frozen):
    table: str
    id: UUID


class ParentRef(_Frozen):
    role: str
    fact_hash: str


class Lineage(_Frozen):
    sources: tuple[SourceRef, ...] = ()
    parents: tuple[ParentRef, ...] = ()


class Fact(_Frozen):
    store_id: UUID
    formula_id: str
    formula_version: int
    kind: FactKind
    scope: Scope
    period: Period
    # Comparison facts (e.g. Shapley contributions to a change) also name the baseline period.
    baseline: Period | None = None
    status: FactStatus
    value: Decimal | None
    unit: Unit
    currency: str | None
    undefined_reason: str | None = None
    p10: Decimal | None = None
    p50: Decimal | None = None
    p90: Decimal | None = None
    method: str | None = None
    inputs_hash: str
    lineage: Lineage = Lineage()
    id: int | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.status is FactStatus.DEFINED:
            if self.value is None or self.undefined_reason is not None:
                raise ValueError("a defined fact has a value and no undefined reason")
            if self.kind is FactKind.ESTIMATE and None in (self.p10, self.p50, self.p90):
                raise ValueError("a defined estimate has P10, P50 and P90")
            if self.kind is FactKind.ESTIMATE and not self.method:
                raise ValueError("a defined estimate names its method")
        elif self.value is not None or not self.undefined_reason:
            raise ValueError("an undefined fact has no value and a reason")
        if (self.unit is Unit.MONEY) != (self.currency is not None):
            raise ValueError("money facts, and only money facts, carry a currency")
        if self.baseline is not None and self.baseline.end > self.period.start:
            raise ValueError("the baseline period must end before the period starts")
        return self

    @cached_property
    def fact_hash(self) -> str:
        content: dict[str, object] = {
            "store_id": self.store_id,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "kind": self.kind,
            "scope_kind": self.scope.kind,
            "scope_id": self.scope.id,
            "period_start": self.period.start,
            "period_end": self.period.end,
            "status": self.status,
            "value": self.value,
            "unit": self.unit,
            "currency": self.currency,
            "undefined_reason": self.undefined_reason,
            "p10": self.p10,
            "p50": self.p50,
            "p90": self.p90,
            "method": self.method,
            "inputs_hash": self.inputs_hash,
        }
        # Added only when present, so facts without a baseline keep their original hashes.
        if self.baseline is not None:
            content["baseline_start"] = self.baseline.start
            content["baseline_end"] = self.baseline.end
        return sha256_hex(canonical_json(content))

    @property
    def is_defined(self) -> bool:
        return self.status is FactStatus.DEFINED
