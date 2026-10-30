"""Per-store settings (docs/product/SPEC.md, section 4), with the specification's defaults.

Business thresholds that decide what reaches the owner (materiality, alert budget, quiet hours)
live here, per store. Statistical thresholds of the detectors live in the versioned thresholds
file (`app/detection/thresholds_v1.toml`).
"""

from datetime import time
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Annotated, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.domain.models import Store
from app.domain.money import Currency, NonNegativeMoney


def _valid_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown time zone {name!r}") from None
    return name


Timezone = Annotated[str, AfterValidator(_valid_timezone)]
IsoWeekday = Annotated[int, Field(ge=1, le=7)]  # 1 = Monday
Ratio = Annotated[Decimal, Field(ge=0, le=1, max_digits=9, decimal_places=6)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DailyBrief(_Frozen):
    enabled: bool = True
    at: time = time(8, 0)
    weekdays: tuple[IsoWeekday, ...] = (1, 2, 3, 4, 5, 6)  # Monday to Saturday


class WeeklyReport(_Frozen):
    """Covers the previous Monday to Sunday."""

    enabled: bool = True
    weekday: IsoWeekday = 1
    at: time = time(8, 0)


class MonthlyReview(_Frozen):
    enabled: bool = True
    day_of_month: int = Field(default=1, ge=1, le=28)
    at: time = time(8, 0)


class QuietHours(_Frozen):
    """Only `critical` alerts are delivered between `start` and `end` (may wrap midnight)."""

    start: time = time(21, 0)
    end: time = time(7, 0)

    def contains(self, moment: time) -> bool:
        if self.start <= self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end


class Materiality(_Frozen):
    """An alert needs both: expected monthly profit impact >= `absolute` (store currency) and
    >= `relative` x trailing-30-day contribution margin."""

    absolute: NonNegativeMoney = Decimal("100")
    relative: Ratio = Decimal("0.03")


class SpendingCaps(_Frozen):
    max_budget_change_ratio: Ratio = Decimal("0.30")
    max_budget_changes_per_campaign_per_day: int = Field(default=1, ge=0)


class AlertChannel(StrEnum):
    WEB = "web"
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class DetailLevel(StrEnum):
    BRIEF = "brief"
    STANDARD = "standard"
    EXPERT = "expert"


class ActionType(StrEnum):
    PAUSE_CAMPAIGN = "pause_campaign"
    CHANGE_BUDGET = "change_budget"
    RESUME_CAMPAIGN = "resume_campaign"
    REORDER_PRODUCT = "reorder_product"
    CHANGE_PRICE = "change_price"
    NEW_CREATIVE = "new_creative"


class AutonomyLevel(IntEnum):
    OBSERVE = 1
    RECOMMEND = 2  # the owner approves every action
    EXECUTE_CAPPED = 3
    MANAGE_SCOPE = 4


def _default_autonomy() -> dict[ActionType, AutonomyLevel]:
    return dict.fromkeys(ActionType, AutonomyLevel.RECOMMEND)


class StoreSettings(_Frozen):
    store_id: UUID
    timezone: Timezone = "UTC"
    currency: Currency
    daily_brief: DailyBrief = DailyBrief()
    weekly_report: WeeklyReport = WeeklyReport()
    monthly_review: MonthlyReview = MonthlyReview()
    alert_channels: tuple[AlertChannel, ...] = (AlertChannel.WEB, AlertChannel.EMAIL)
    quiet_hours: QuietHours = QuietHours()
    alert_budget_per_day: int = Field(default=3, ge=0)  # non-critical alerts; overflow -> briefing
    materiality: Materiality = Materiality()
    detail_level: DetailLevel = DetailLevel.STANDARD
    autonomy: dict[ActionType, AutonomyLevel] = Field(default_factory=_default_autonomy)
    spending_caps: SpendingCaps = SpendingCaps()
    language: str = Field(default="en", pattern=r"^en$")  # French is planned later
    # Where email goes; without it, email deliveries are skipped (recorded, not sent).
    notification_email: str | None = Field(
        default=None, max_length=254, pattern=r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$"
    )

    @model_validator(mode="after")
    def _complete(self) -> Self:
        missing = set(ActionType) - set(self.autonomy)
        if missing:
            raise ValueError(f"autonomy missing for {sorted(missing)}")
        if not self.alert_channels:
            raise ValueError("at least one alert channel is required")
        if len(set(self.daily_brief.weekdays)) != len(self.daily_brief.weekdays):
            raise ValueError("daily brief weekdays must be distinct")
        return self

    @classmethod
    def defaults_for(cls, store: Store) -> "StoreSettings":
        """Specification defaults; time zone and currency come from the store."""
        return cls(store_id=store.store_id, timezone=store.timezone, currency=store.currency)
