"""Load and save store settings. Every change is recorded in the audit log."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.domain.audit import append_audit
from app.domain.repositories import StoreRepository
from app.domain.schema import store_settings
from app.settings.models import (
    ActionType,
    AutonomyLevel,
    DailyBrief,
    Materiality,
    MonthlyReview,
    QuietHours,
    SpendingCaps,
    StoreSettings,
    WeeklyReport,
)


def _row(settings: StoreSettings) -> dict[str, Any]:
    return {
        "store_id": settings.store_id,
        "timezone": settings.timezone,
        "currency": settings.currency,
        "daily_brief_enabled": settings.daily_brief.enabled,
        "daily_brief_at": settings.daily_brief.at,
        "daily_brief_weekdays": list(settings.daily_brief.weekdays),
        "weekly_report_enabled": settings.weekly_report.enabled,
        "weekly_report_weekday": settings.weekly_report.weekday,
        "weekly_report_at": settings.weekly_report.at,
        "monthly_review_enabled": settings.monthly_review.enabled,
        "monthly_review_day": settings.monthly_review.day_of_month,
        "monthly_review_at": settings.monthly_review.at,
        "alert_channels": [c.value for c in settings.alert_channels],
        "quiet_hours_start": settings.quiet_hours.start,
        "quiet_hours_end": settings.quiet_hours.end,
        "alert_budget_per_day": settings.alert_budget_per_day,
        "materiality_absolute": settings.materiality.absolute,
        "materiality_relative": settings.materiality.relative,
        "detail_level": settings.detail_level.value,
        "autonomy": {k.value: int(v) for k, v in settings.autonomy.items()},
        "max_budget_change_ratio": settings.spending_caps.max_budget_change_ratio,
        "max_budget_changes_per_day": (
            settings.spending_caps.max_budget_changes_per_campaign_per_day
        ),
        "language": settings.language,
        "notification_email": settings.notification_email,
    }


def _from_row(row: Any) -> StoreSettings:
    return StoreSettings(
        store_id=row.store_id,
        timezone=row.timezone,
        currency=row.currency.strip(),
        daily_brief=DailyBrief(
            enabled=row.daily_brief_enabled,
            at=row.daily_brief_at,
            weekdays=tuple(row.daily_brief_weekdays),
        ),
        weekly_report=WeeklyReport(
            enabled=row.weekly_report_enabled,
            weekday=row.weekly_report_weekday,
            at=row.weekly_report_at,
        ),
        monthly_review=MonthlyReview(
            enabled=row.monthly_review_enabled,
            day_of_month=row.monthly_review_day,
            at=row.monthly_review_at,
        ),
        alert_channels=tuple(row.alert_channels),
        quiet_hours=QuietHours(start=row.quiet_hours_start, end=row.quiet_hours_end),
        alert_budget_per_day=row.alert_budget_per_day,
        materiality=Materiality(
            absolute=row.materiality_absolute, relative=row.materiality_relative
        ),
        detail_level=row.detail_level,
        autonomy={ActionType(k): AutonomyLevel(v) for k, v in row.autonomy.items()},
        spending_caps=SpendingCaps(
            max_budget_change_ratio=row.max_budget_change_ratio,
            max_budget_changes_per_campaign_per_day=row.max_budget_changes_per_day,
        ),
        language=row.language,
        notification_email=row.notification_email,
    )


class StoreSettingsRepository:
    """Use inside the store's tenant transaction."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def get(self, store_id: UUID) -> StoreSettings | None:
        row = self.conn.execute(
            select(store_settings).where(store_settings.c.store_id == store_id)
        ).first()
        return None if row is None else _from_row(row)

    def get_or_default(self, store_id: UUID) -> StoreSettings:
        """Saved settings, or the specification defaults for the store (not persisted)."""
        saved = self.get(store_id)
        if saved is not None:
            return saved
        store = StoreRepository(self.conn).get(store_id)
        if store is None:
            raise LookupError(f"store {store_id} does not exist or is not visible")
        return StoreSettings.defaults_for(store)

    def save(self, settings: StoreSettings, *, actor: str) -> StoreSettings:
        row = _row(settings)
        updates = {k: v for k, v in row.items() if k != "store_id"}
        self.conn.execute(
            pg_insert(store_settings)
            .values(**row)
            .on_conflict_do_update(index_elements=["store_id"], set_=updates)
        )
        append_audit(
            self.conn,
            settings.store_id,
            actor=actor,
            action="settings.saved",
            payload=settings.model_dump(mode="json"),
        )
        return settings
