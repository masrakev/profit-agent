"""Generator configuration. Together with the seed it fully determines the generated store."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.hashing import canonical_json, sha256_hex

MAX_LONG_DAYS = 400


class LongHistory(BaseModel):
    """Demand dynamics for long histories (goal backtests): the market grows or shrinks at a
    rate that drifts slowly, with yearly seasonality and occasional regime changes. They scale
    organic demand and the ad response (budgets do not follow). Drawn from a random stream of
    their own, so the rest of the store is the same stream of draws as without them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    growth_per_year: Decimal = Field(default=Decimal(0), ge=-1, le=2)  # mean log growth a year
    growth_drift: Decimal = Field(default=Decimal("0.1"), ge=0)  # the rate's sd after a year
    yearly_amplitude: Decimal = Field(default=Decimal("0.15"), ge=0, lt=1)
    yearly_peak: int = Field(default=330, ge=1, le=366)  # day of the year with the most demand
    regime_changes_per_year: Decimal = Field(default=Decimal(1), ge=0)
    regime_shift_sd: Decimal = Field(default=Decimal("0.15"), ge=0)  # log level shift


class GeneratorConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int = Field(ge=0)
    store_name: str | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    start_date: date = date(2026, 6, 1)
    days: int = Field(default=120, ge=35)
    products_min: int = Field(default=15, ge=1)
    products_max: int = Field(default=40, ge=1)
    campaigns_min: int = Field(default=3, ge=0)
    campaigns_max: int = Field(default=8, ge=0)
    # Monday..Sunday demand multipliers. Decimals (not floats) so the config hashes canonically.
    weekly_seasonality: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal] = (
        Decimal("0.92"),
        Decimal("0.95"),
        Decimal("0.97"),
        Decimal("1.00"),
        Decimal("1.08"),
        Decimal("1.15"),
        Decimal("0.93"),
    )
    tax_rate: Decimal = Decimal("0.08")
    free_shipping_threshold: Decimal = Decimal("75.00")
    shipping_fee: Decimal = Decimal("5.99")
    payment_fee_rate: Decimal = Decimal("0.029")
    payment_fee_fixed: Decimal = Decimal("0.30")
    discount_probability: Decimal = Field(default=Decimal("0.2"), ge=0, le=1)
    discount_rate: Decimal = Decimal("0.10")
    cross_sell_probability: Decimal = Field(default=Decimal("0.12"), ge=0, le=1)
    # Share of products whose supplier cost changes once during the horizon.
    cost_change_probability: Decimal = Field(default=Decimal("0.3"), ge=0, le=1)
    # Initial stock, in days of base demand (low, high).
    initial_stock_days: tuple[int, int] = (20, 45)
    # "static": reorder on base demand with `safety_stock_days` of safety stock.
    # "adaptive": reorder on recent actual sales (and expected ad demand), at three lead times
    # plus `safety_stock_days` of cover, so on-hand stock stays above one lead time of demand
    # even while an order is in transit.
    reorder_policy: Literal["static", "adaptive"] = "static"
    safety_stock_days: int = Field(default=7, ge=0)
    # "random": daily budget drawn uniformly. "profit_optimal": budget set below the spend that
    # maximises expected campaign profit, so a healthy campaign is profitable.
    campaign_budget_policy: Literal["random", "profit_optimal"] = "random"
    # Off unless set; left out of the serialized config when off, so existing manifests, seeds
    # and stores are unchanged.
    long_history: LongHistory | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def _ranges(self) -> "GeneratorConfig":
        if self.products_max < self.products_min or self.campaigns_max < self.campaigns_min:
            raise ValueError("max must be >= min")
        if self.long_history is not None and self.days > MAX_LONG_DAYS:
            raise ValueError(f"long histories have at most {MAX_LONG_DAYS} days")
        if self.initial_stock_days[1] < self.initial_stock_days[0]:
            raise ValueError("initial_stock_days must be (low, high)")
        return self

    @property
    def fingerprint(self) -> str:
        return sha256_hex(canonical_json(self.model_dump()))
