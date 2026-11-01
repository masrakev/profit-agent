"""The WhatsApp demo, end to end (bench/demo_whatsapp.py): the seeded stockout alert delivered on
WhatsApp with its buttons, approved from the phone through the signed webhook and the normal
decision flow, executed by the executor under the policy engine, its status sent back; a second
tap decides nothing. WhatsApp is the fake adapter; the seed replays the recorded model calls."""

import os
from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import get_settings
from app.db import make_engine
from bench.demo_seed import demo_provider, seed
from bench.demo_whatsapp import markdown, run
from bench.runner.__main__ import prepare_database

pytestmark = pytest.mark.db
DB = os.environ.get("TEST_DATABASE_NAME", "profit_test") + "_demo_whatsapp"


@pytest.fixture(scope="module")
def demo(database_urls: tuple[str, str]) -> dict[str, Any]:
    engine = make_engine(prepare_database(DB))
    settings = get_settings().model_copy(
        update={"meta_access_token": None, "meta_campaign_links": {}}
    )
    try:
        return run(engine, settings, seed(engine, demo_provider(settings)))
    finally:
        engine.dispose()


def test_the_alert_arrives_with_its_buttons(demo: dict[str, Any]) -> None:
    alert = demo["alert_message"]
    assert alert["text"].startswith("*Critical alert: ")
    assert "a month" in alert["text"]
    assert alert["buttons"] == ["Approve", "See options"]
    assert alert["as"] == "template profit_alert"  # the owner had not written in 24 hours
    assert demo["verified"]["verified"] is True


def test_approving_from_the_phone_executes_the_pause(demo: dict[str, Any]) -> None:
    assert demo["received"] == {"messages": 1, "new": 1, "statuses": 0}
    assert demo["approved"] == "button: approved"
    assert demo["approval"]["channel"] == "whatsapp"
    assert demo["reply"]["as"] == "session message"
    assert demo["reply"]["text"].startswith("Approved for ")
    assert [a["kind"] for a in demo["actions"]] == ["pause_campaign"] * len(demo["actions"])
    assert {a["status"] for a in demo["actions"]} == {"executed"}
    assert demo["decision_status"] == "executed"
    assert demo["status_message"]["text"].startswith("Done for ")
    assert demo["again"] == "button: stale"


def test_the_report(demo: dict[str, Any]) -> None:
    text = markdown(demo, datetime.now(UTC))
    assert "# Demo: the stockout alert on WhatsApp" in text
    assert "> [Approve] [See options]" in text
    assert "Tapping Approve again: `button: stale`" in text
