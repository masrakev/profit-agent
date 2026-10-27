"""Detection vocabulary: entities, fault families, symptoms and incidents.

Symptoms and incidents never carry raw amounts: every measurement they rely on is a persisted
fact, referenced by id. `score` fields are internal ranking statistics, not numbers for users.
"""

from datetime import date
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.facts.model import ScopeKind


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EntityRef(_Frozen):
    kind: ScopeKind
    id: UUID | None = None

    @model_validator(mode="after")
    def _id_matches_kind(self) -> Self:
        if (self.kind is ScopeKind.STORE) != (self.id is None):
            raise ValueError("the store entity has no id; products and campaigns need one")
        return self

    @classmethod
    def store(cls) -> "EntityRef":
        return cls(kind=ScopeKind.STORE)

    @classmethod
    def product(cls, product_id: UUID) -> "EntityRef":
        return cls(kind=ScopeKind.PRODUCT, id=product_id)

    @classmethod
    def campaign(cls, campaign_id: UUID) -> "EntityRef":
        return cls(kind=ScopeKind.CAMPAIGN, id=campaign_id)

    def __str__(self) -> str:
        return self.kind.value if self.id is None else f"{self.kind.value}:{self.id}"


class FaultFamily(StrEnum):
    CPA_DRIFT = "cpa_drift"
    CANNIBALIZATION = "cannibalization"
    STOCKOUT_ON_PROMOTED = "stockout_on_promoted"
    SUPPLIER_COST_INCREASE = "supplier_cost_increase"
    REFUND_SPIKE = "refund_spike"
    MIX_SHIFT = "mix_shift"
    FEE_INCREASE = "fee_increase"
    TRACKING_BREAK = "tracking_break"


class SymptomCategory(StrEnum):
    PROFITABILITY = "profitability"
    DATA_QUALITY = "data_quality"


class AlertLevel(StrEnum):
    """What reaches the owner (docs/product/SPEC.md, section 6)."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    WATCHLIST = "watchlist"  # real but not material: the briefing watchlist, not an alert
    DATA_QUALITY = "data_quality"


# Presentation order: alerts first, data quality between high and normal, watchlist last.
ALERT_RANK = {
    AlertLevel.CRITICAL: 0,
    AlertLevel.HIGH: 1,
    AlertLevel.DATA_QUALITY: 2,
    AlertLevel.NORMAL: 3,
    AlertLevel.WATCHLIST: 4,
}
OUT_OF_STOCK_NOTE = "out of stock while promoted"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Symptom(_Frozen):
    detector_id: str
    entity: EntityRef
    metric: str
    category: SymptomCategory
    severity: Severity
    score: float  # internal ranking statistic (detector-specific, comparable to its threshold)
    first_seen: date  # the day the persistence requirement was first met
    last_seen: date
    baseline_fact_ids: tuple[int, ...]
    current_fact_ids: tuple[int, ...]
    note: str | None = None


class Candidate(_Frozen):
    family: FaultFamily
    entity: EntityRef
    score: float
    evidence: tuple[str, ...]  # detector ids and attribution drivers that support it


class Incident(_Frozen):
    incident_id: str
    category: SymptomCategory
    severity_score: float
    first_seen: date
    last_seen: date
    entities: tuple[EntityRef, ...]
    symptoms: tuple[Symptom, ...]
    candidates: tuple[Candidate, ...]  # ranked, best first
    attribution_fact_ids: tuple[int, ...] = ()
    alert: AlertLevel = AlertLevel.WATCHLIST
    material: bool = False
    monthly_impact_fact_id: int | None = None  # `expected_monthly_impact` estimate fact

    @property
    def is_alert(self) -> bool:
        return self.alert is not AlertLevel.WATCHLIST
