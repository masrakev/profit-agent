"""Generator configuration. Together with the seed it fully determines the generated store."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.hashing import canonical_json, sha256_hex


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

    @model_validator(mode="after")
    def _ranges(self) -> "GeneratorConfig":
        if self.products_max < self.products_min or self.campaigns_max < self.campaigns_min:
            raise ValueError("max must be >= min")
        return self

    @property
    def fingerprint(self) -> str:
        return sha256_hex(canonical_json(self.model_dump()))
