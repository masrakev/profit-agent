"""Domain models. Every record carries `store_id`; every amount carries an ISO 4217 currency."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.domain.money import Currency, NonNegativeMoney, PositiveMoney


def _to_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be UTC")
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Store(DomainModel):
    store_id: UUID
    name: str
    currency: Currency
    timezone: str = "UTC"


class Product(DomainModel):
    id: UUID
    store_id: UUID
    sku: str
    name: str
    price: NonNegativeMoney
    unit_cost: NonNegativeMoney
    unit_fee: NonNegativeMoney
    currency: Currency
    supplier_lead_time_days: int | None = Field(default=None, ge=0)


class OrderStatus(StrEnum):
    PAID = "paid"
    CANCELLED = "cancelled"


class Order(DomainModel):
    id: UUID
    store_id: UUID
    external_id: str
    ordered_at: UtcDatetime
    status: OrderStatus = OrderStatus.PAID
    currency: Currency
    shipping_amount: NonNegativeMoney = Decimal(0)
    payment_fee_amount: NonNegativeMoney = Decimal(0)


class OrderLine(DomainModel):
    """One product line. `unit_cost_at_sale` and `unit_fee_at_sale` snapshot costs at sale time.

    The payment fee allocated to the line is derived from the order by the repository.
    """

    id: UUID
    store_id: UUID
    order_id: UUID
    product_id: UUID
    quantity: int = Field(gt=0)
    unit_price: NonNegativeMoney
    discount_amount: NonNegativeMoney = Decimal(0)
    tax_amount: NonNegativeMoney = Decimal(0)
    unit_cost_at_sale: NonNegativeMoney
    unit_fee_at_sale: NonNegativeMoney
    currency: Currency

    @property
    def net_amount(self) -> Decimal:
        """Amount paid for the line after discounts, excluding tax and shipping."""
        return self.unit_price * self.quantity - self.discount_amount

    @model_validator(mode="after")
    def _discount_within_gross(self) -> Self:
        if self.discount_amount > self.unit_price * self.quantity:
            raise ValueError("discount exceeds the line's gross amount")
        return self


class Refund(DomainModel):
    """Merchandise refund for one order line, excluding refunded tax and shipping."""

    id: UUID
    store_id: UUID
    order_id: UUID
    order_line_id: UUID
    refunded_at: UtcDatetime
    amount: PositiveMoney
    quantity: int = Field(ge=0)
    currency: Currency
    reason: str | None = None


class InventorySnapshot(DomainModel):
    """Units on hand at the end of `snapshot_date` (UTC)."""

    id: UUID
    store_id: UUID
    product_id: UUID
    snapshot_date: date
    units_on_hand: int = Field(ge=0)


class CampaignStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class AdCampaign(DomainModel):
    id: UUID
    store_id: UUID
    external_id: str
    name: str
    platform: str
    status: CampaignStatus = CampaignStatus.ACTIVE
    currency: Currency
    daily_budget: NonNegativeMoney


class AdCampaignProduct(DomainModel):
    store_id: UUID
    campaign_id: UUID
    product_id: UUID


class AdMetricDaily(DomainModel):
    """Platform-reported daily metrics. `metric_date` is a UTC calendar day."""

    id: UUID
    store_id: UUID
    campaign_id: UUID
    metric_date: date
    spend: NonNegativeMoney
    currency: Currency
    impressions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    attributed_purchases: int = Field(ge=0)
    attributed_revenue: NonNegativeMoney


class CostItem(DomainModel):
    """A fixed cost covering the half-open day range `[period_start, period_end)`."""

    id: UUID
    store_id: UUID
    name: str
    category: str
    kind: Literal["fixed"] = "fixed"
    amount: NonNegativeMoney
    currency: Currency
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def _non_empty_period(self) -> Self:
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class AuditLogEntry(DomainModel):
    store_id: UUID
    seq: int = Field(ge=1)
    occurred_at: UtcDatetime
    actor: str
    action: str
    payload: dict[str, Any]
    prev_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
