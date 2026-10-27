"""Store settings: specification defaults, validation, persistence and tenant isolation."""

from datetime import time
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, text

from app.db import tenant_transaction
from app.domain.audit import verify_chain
from app.domain.models import Store
from app.settings import StoreSettings, StoreSettingsRepository
from app.settings.models import (
    ActionType,
    AlertChannel,
    AutonomyLevel,
    DailyBrief,
    DetailLevel,
    Materiality,
    QuietHours,
)
from tests.conftest import create_store


def test_defaults_follow_the_specification() -> None:
    store = Store(store_id=uuid4(), name="S", currency="EUR", timezone="Europe/Paris")
    s = StoreSettings.defaults_for(store)
    assert (s.timezone, s.currency) == ("Europe/Paris", "EUR")
    assert s.daily_brief == DailyBrief(enabled=True, at=time(8), weekdays=(1, 2, 3, 4, 5, 6))
    assert (s.weekly_report.weekday, s.weekly_report.at) == (1, time(8))
    assert (s.monthly_review.day_of_month, s.monthly_review.at) == (1, time(8))
    assert s.alert_channels == (AlertChannel.WEB, AlertChannel.EMAIL)
    assert (s.quiet_hours.start, s.quiet_hours.end) == (time(21), time(7))
    assert s.alert_budget_per_day == 3
    assert s.materiality == Materiality(absolute=Decimal(100), relative=Decimal("0.03"))
    assert s.detail_level is DetailLevel.STANDARD
    assert s.autonomy == dict.fromkeys(ActionType, AutonomyLevel.RECOMMEND)
    assert s.spending_caps.max_budget_change_ratio == Decimal("0.30")
    assert s.spending_caps.max_budget_changes_per_campaign_per_day == 1
    assert s.language == "en"


def test_quiet_hours_wrap_midnight() -> None:
    night = QuietHours()
    assert night.contains(time(23))
    assert night.contains(time(6, 59))
    assert not night.contains(time(7))
    assert not night.contains(time(12))
    lunch = QuietHours(start=time(12), end=time(14))
    assert lunch.contains(time(13))
    assert not lunch.contains(time(15))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"timezone": "Mars/Olympus"}, "unknown time zone"),
        ({"autonomy": {ActionType.PAUSE_CAMPAIGN: AutonomyLevel.OBSERVE}}, "autonomy missing"),
        ({"alert_channels": ()}, "at least one alert channel"),
        ({"daily_brief": DailyBrief(weekdays=(1, 1))}, "distinct"),
        ({"language": "fr"}, "pattern"),
        ({"materiality": {"absolute": "100", "relative": "1.5"}}, "less than or equal"),
        ({"alert_budget_per_day": -1}, "greater than or equal"),
    ],
)
def test_validation(changes: dict[str, object], message: str) -> None:
    base = {"store_id": uuid4(), "currency": "USD"}
    with pytest.raises(ValidationError, match=message):
        StoreSettings.model_validate(base | changes)


@pytest.mark.db
def test_round_trip_upsert_and_audit(app_engine: Engine) -> None:
    store = create_store(app_engine, currency="EUR")
    with tenant_transaction(app_engine, store) as conn:
        repo = StoreSettingsRepository(conn)
        assert repo.get(store) is None
        defaults = repo.get_or_default(store)
        assert defaults.currency == "EUR"
        repo.save(defaults, actor="owner")
        changed = defaults.model_copy(
            update={
                "materiality": Materiality(absolute=Decimal("250.50"), relative=Decimal("0.05")),
                "alert_channels": (AlertChannel.EMAIL, AlertChannel.WHATSAPP),
                "detail_level": DetailLevel.EXPERT,
                "autonomy": defaults.autonomy | {ActionType.PAUSE_CAMPAIGN: AutonomyLevel.OBSERVE},
            }
        )
        repo.save(changed, actor="owner")
    with tenant_transaction(app_engine, store) as conn:
        assert StoreSettingsRepository(conn).get(store) == changed
        assert verify_chain(conn, store).entries_checked == 2
    with tenant_transaction(app_engine, uuid4()) as conn, pytest.raises(LookupError):
        StoreSettingsRepository(conn).get_or_default(store)  # another tenant sees nothing


@pytest.mark.db
def test_settings_are_tenant_isolated(app_engine: Engine) -> None:
    a, b = create_store(app_engine), create_store(app_engine)
    with tenant_transaction(app_engine, b) as conn:
        StoreSettingsRepository(conn).save(
            StoreSettingsRepository(conn).get_or_default(b), actor="owner"
        )
    with tenant_transaction(app_engine, a) as conn:
        assert StoreSettingsRepository(conn).get(b) is None
        assert conn.execute(text("SELECT count(*) FROM store_settings")).scalar_one() == 0
