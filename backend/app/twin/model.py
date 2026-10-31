"""Twin types: scenarios, the fitted store model and simulation results (ADR 0014)."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import NamedTuple
from uuid import UUID

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from app.domain.hashing import canonical_json, sha256_hex

FloatArray = npt.NDArray[np.float64]
METRICS = ("contribution_margin", "net_profit", "units", "ad_spend")
MONEY_METRICS = frozenset({"contribution_margin", "net_profit", "ad_spend"})
MAX_SCENARIO_DAYS = 90  # what-if questions stop at 60 (app.agent.evaluate); plans at 90


class ActionKind(StrEnum):
    CHANGE_BUDGET = "change_budget"  # one campaign's daily budget times (1 + change)
    PAUSE_CAMPAIGN = "pause_campaign"
    CHANGE_ALL_AD_SPEND = "change_all_ad_spend"  # every campaign's budget times (1 + change)
    CHANGE_PRICE = "change_price"  # one product's price times (1 + change)
    LAUNCH_CAMPAIGN = "launch_campaign"  # a new campaign promoting one product
    # Twin only, for plans: one product's supply restored from `start` (an owner's
    # reorder).
    RESTOCK_PRODUCT = "restock_product"


class Action(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ActionKind
    entity: UUID | None = None  # campaign or product; None for store-wide actions
    change: Decimal = Decimal(0)  # relative: -0.2 is 20% less
    days: int | None = Field(default=None, ge=1)  # how long it lasts; None: the whole horizon
    # The day it takes effect (plans date their steps); left out when 0, so existing
    # actions, decisions and fact hashes are unchanged.
    start: int = Field(default=0, ge=0, exclude_if=lambda v: v == 0)
    daily_budget: Decimal | None = None  # LAUNCH_CAMPAIGN: None uses the store's median spend


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actions: tuple[Action, ...] = ()
    horizon_days: int = Field(default=14, ge=7, le=MAX_SCENARIO_DAYS)

    @property
    def key(self) -> str:
        return sha256_hex(canonical_json(self.model_dump(mode="json")))[:16]

    @property
    def is_do_nothing(self) -> bool:
        return not self.actions


class Elasticity(NamedTuple):
    """Own-price elasticity: estimated from list-price changes, or the documented prior."""

    estimated: bool
    low: float  # draws are uniform on [low, high] (prior) or normal (estimate) clipped to it
    high: float
    mean: float
    sd: float


@dataclass(frozen=True)
class CurveFit:
    """purchases = a * (1 - exp(-b * spend)) on platform-attributed purchases, with bootstrap
    draws of (a, b, sigma)."""

    a: FloatArray
    b: FloatArray
    sigma: FloatArray
    point: tuple[float, float, float]
    spend_low: float  # observed daily spend range over the fit window
    spend_high: float


@dataclass(frozen=True)
class CampaignModel:
    campaign_id: UUID
    promoted: tuple[UUID, ...]
    mean_spend: float  # recent daily spend level (what "do nothing" keeps spending)
    spend_ratios: FloatArray  # daily spend / its mean over the window (spend noise)
    active_days: int
    curve: CurveFit | None
    undefined_reason: str | None = None


@dataclass(frozen=True)
class ProductModel:
    product_id: UUID
    units_observed: float  # units sold over the fit window
    ad_rate: float  # ad-driven units per day at the point fit (part of the observed rate)
    net_price: float  # revenue per unit, after discounts
    unit_cost: float  # recent cost per unit
    fee_per_unit: float
    refund_rate: float  # refunds / revenue
    units_per_line: float
    on_hand: float | None
    inflow_rate: float  # stock arrivals per day over the window
    elasticity: Elasticity
    lead_time_days: int | None = None  # supplier lead time


@dataclass(frozen=True)
class TwinModel:
    store_id: UUID
    currency: str
    as_of: date  # exclusive end of the data the model was fitted on
    window_days: int
    products: dict[UUID, ProductModel]
    campaigns: dict[UUID, CampaignModel]
    fixed_daily: float
    fingerprint: str  # hash of the fit inputs, part of every simulated fact
    notes: tuple[str, ...] = field(default_factory=tuple)


class Range(NamedTuple):
    p10: float
    p50: float
    p90: float


@dataclass(frozen=True)
class Simulation:
    scenario: Scenario
    totals: dict[str, Range]  # the scenario over the horizon
    do_nothing: dict[str, Range]  # the same draws without any action
    change: dict[str, Range]  # scenario minus do nothing, draw by draw
    low_evidence: tuple[str, ...] = ()
    undefined_reason: str | None = None
    calibration_version: int = 0
