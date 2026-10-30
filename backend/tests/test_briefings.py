"""Briefings assembled from facts (SPEC sections 5.1-5.3): periods, content and storage."""

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine

from app.briefings import periods, wording
from app.briefings.content import build
from app.briefings.models import BriefingContent, BriefingKind
from app.briefings.store import FACTS_ONLY, exists, get, list_briefings, save
from app.causal.outcome import measure
from app.channels.render import Channel, load_entity_names, render
from app.db import tenant_transaction
from app.decisions.options import build_options
from app.decisions.store import propose
from app.detection import pipeline
from app.detection.models import AlertLevel
from app.facts.engine import FactEngine
from app.facts.repository import get_facts
from app.twin import fit_twin
from app.verifier import entity_references, fact_references, verify
from bench.generator.load import load
from bench.scenarios.manifest import load_suite
from bench.simulator import advance
from tests.action_helpers import Rig, actions, approved, option_set, simulator_store

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)
DATA_END = date(2026, 9, 29)  # golden stores: 120 days from 2026-06-01


def test_periods() -> None:
    assert periods.last_day(DATA_END, date(2026, 10, 30)) == date(2026, 9, 28)
    assert periods.last_day(DATA_END, date(2026, 9, 20)) == date(2026, 9, 19)
    assert periods.week_period(date(2026, 9, 28)) == (date(2026, 9, 21), date(2026, 9, 28))
    assert periods.week_period(date(2026, 9, 27)) == (date(2026, 9, 21), date(2026, 9, 28))
    assert periods.month_period(date(2026, 9, 28)) == (date(2026, 8, 1), date(2026, 9, 1))
    assert periods.month_period(date(2026, 8, 31)) == (date(2026, 8, 1), date(2026, 9, 1))
    assert periods.previous((date(2026, 9, 21), date(2026, 9, 28))) == (
        date(2026, 9, 14),
        date(2026, 9, 21),
    )
    assert periods.previous((date(2026, 3, 1), date(2026, 4, 1)), monthly=True) == (
        date(2026, 2, 1),
        date(2026, 3, 1),
    )


def assert_grounded(content: BriefingContent) -> None:
    """Code text holds no number of its own, and every reference is a cited fact or entity."""
    for text in content.texts():
        assert verify(text) == [], text
        assert fact_references(text) <= set(content.fact_ids), text
        assert entity_references(text) <= set(content.entities), text


def keys(content: BriefingContent) -> list[str]:
    return [s.key for s in content.sections]


@pytest.mark.db
def test_the_daily_brief_puts_the_critical_stockout_first(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    with tenant_transaction(app_engine, store) as conn:
        brief = build(conn, store, BriefingKind.DAILY, local_today=DATA_END, now=NOW)
    assert_grounded(brief)
    assert (brief.period_start, brief.period_end) == (date(2026, 9, 28), DATA_END)
    assert brief.headline == "A critical problem needs your attention today."
    assert keys(brief)[:3] == ["health", "money_at_stake", "top_items"]
    top = next(s for s in brief.sections if s.key == "top_items")
    assert 1 <= len(top.items) <= 3
    assert top.items[0].level == "critical"
    assert top.items[0].incident_id == golden_stockout["incident"]
    assert "out of stock" in top.items[0].text
    assert golden_stockout["incident"] in brief.incident_ids
    assert not brief.nothing_material


@pytest.fixture(scope="module")
def healthy(app_engine: Engine) -> Any:
    manifest = next(m for m in load_suite("golden") if m.scenario_id == "healthy-a")
    data = manifest.generate()
    load(app_engine, data, manifest.config)
    pipeline.run_pipeline(app_engine, data.store.store_id)
    return data.store.store_id


@pytest.mark.db
def test_a_healthy_store_needs_nothing(app_engine: Engine, healthy: Any) -> None:
    with tenant_transaction(app_engine, healthy) as conn:
        brief = build(conn, healthy, BriefingKind.DAILY, local_today=DATA_END, now=NOW)
        stale = build(
            conn, healthy, BriefingKind.DAILY, local_today=DATA_END + timedelta(days=3), now=NOW
        )
    assert_grounded(brief)
    assert brief.nothing_material
    assert brief.headline == "Nothing needs your attention today."
    assert set(keys(brief)) <= {"health", "data_notice"}
    notice = next(s for s in stale.sections if s.key == "data_notice")
    assert "stops before yesterday" in notice.items[0].text
    assert stale.period_start == brief.period_start  # the latest day with data


@pytest.mark.db
def test_the_weekly_report(app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    store = golden_stockout["id"]
    with tenant_transaction(app_engine, store) as conn:
        week = build(conn, store, BriefingKind.WEEKLY, local_today=DATA_END, now=NOW)
    assert_grounded(week)
    assert (week.period_start, week.period_end) == (date(2026, 9, 21), date(2026, 9, 28))
    assert keys(week)[:3] == ["summary", "profit_bridge", "campaigns"]
    sections = {s.key: s for s in week.sections}
    summary = sections["summary"]
    assert [i.text.split(":")[0] for i in summary.items] == [
        "Net profit",
        "Contribution margin",
        "Revenue",
        "Ad spend",
    ]
    assert all("on average over the previous weeks" in i.text for i in summary.items)
    bridge = sections["profit_bridge"].items
    assert bridge[0].text.startswith("Change in net profit")
    assert len(bridge) == 9  # the change and its eight drivers
    table = sections["campaigns"].table
    assert table is not None
    assert table.columns[0] == "Campaign"
    assert len(table.rows) >= 1
    with tenant_transaction(app_engine, store) as conn:
        facts = get_facts(conn, store, week.fact_ids)
        names = load_entity_names(conn, store, week.entities)
    shown = [render(t, facts, names, Channel.TEXT) for t in week.texts()]
    assert not [t for t in shown if re.search(r"\b(lost|down|gained|up) -", t)]
    assert all(" lost {{F" in i.text for i in sections["products_down"].items)
    assert all(" gained {{F" in i.text for i in sections["products_up"].items)
    assert re.search(r": (lost|gained) \{\{F", bridge[1].text)
    product = f"{{{{E:product:{golden_stockout['product']}}}}}"
    stock = sections["inventory"].items
    assert stock[0].text.startswith(product)
    assert "still advertised" in stock[0].text
    assert "decisions" in sections


@pytest.mark.db
def test_the_monthly_review(app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    store = golden_stockout["id"]
    with tenant_transaction(app_engine, store) as conn:
        month = build(conn, store, BriefingKind.MONTHLY, local_today=DATA_END, now=NOW)
    assert_grounded(month)
    assert (month.period_start, month.period_end) == (date(2026, 8, 1), date(2026, 9, 1))
    sections = {s.key: s for s in month.sections}
    for key in ("summary", "profit_bridge", "campaigns", "unit_economics", "fixed_costs", "trust"):
        assert key in sections, key
    economics = sections["unit_economics"].table
    assert economics is not None
    assert economics.columns == (
        "Product",
        "Units",
        "Net price",
        "Unit cost",
        "Fees",
        "Refunds",
        "Contribution",
    )
    assert all("on average over the previous months" in i.text for i in sections["summary"].items)
    assert [i.text.split(":")[0] for i in sections["trust"].items] == [
        "Pause a campaign",
        "Resume a campaign",
        "Change a daily budget",
    ]


@pytest.mark.db
def test_a_briefing_is_stored_once_per_day(app_engine: Engine, healthy: Any) -> None:
    day = date(2026, 10, 30)
    with tenant_transaction(app_engine, healthy) as conn:
        brief = build(conn, healthy, BriefingKind.DAILY, local_today=DATA_END, now=NOW)
        first, created = save(conn, healthy, brief, FACTS_ONLY, local_date=day)
        again, created_again = save(conn, healthy, brief, FACTS_ONLY, local_date=day)
        assert (created, created_again, again) == (True, False, first)
        assert exists(conn, healthy, BriefingKind.DAILY, day)
        assert not exists(conn, healthy, BriefingKind.WEEKLY, day)
        record = get(conn, healthy, first)
        assert record is not None
        assert (record.status, record.content) == ("facts_only", brief)
        assert [r.briefing_id for r in list_briefings(conn, healthy)] == [first]
        assert list_briefings(conn, healthy, kind=BriefingKind.WEEKLY) == []


@pytest.fixture(scope="module")
def lived(app_engine: Engine) -> dict[str, Any]:
    """A simulator store with an executed pause measured after its window, then a pending
    decision on its most urgent alert."""
    sim = simulator_store(app_engine, "dev-cpa_drift-08")
    store, drifting = sim["id"], sim["campaign"]
    other = next(c for c in sim["campaigns"] if c != drifting)
    done = approved(app_engine, store, option_set(other, label="briefing"))
    Rig(app_engine).executor().run_once()
    advance(app_engine, store, 7)
    [action] = actions(app_engine, store, done.decision_id)
    with tenant_transaction(app_engine, store) as conn:
        outcome = measure(conn, store, action.action_id)
    result = pipeline.run_pipeline(app_engine, store)
    alert = next(
        i for i in result.incidents if i.is_alert and i.alert is not AlertLevel.DATA_QUALITY
    )
    with tenant_transaction(app_engine, store) as conn:
        model = fit_twin(conn, store)
        options = build_options(
            model, "cpa_drift", f"campaign:{drifting}", floor_monthly=Decimal(100)
        )
        pending = propose(
            conn,
            FactEngine(conn, store),
            model,
            options,
            source="incident",
            incident_id=alert.incident_id,
        )
    return {
        "id": store,
        "local_today": result.as_of,
        "done": done,
        "outcome": outcome,
        "pending": pending,
        "incident": alert.incident_id,
    }


@pytest.mark.db
def test_briefings_show_decisions_and_outcomes(app_engine: Engine, lived: dict[str, Any]) -> None:
    store, now = lived["id"], datetime.now(UTC) + timedelta(minutes=1)
    with tenant_transaction(app_engine, store) as conn:
        daily, weekly, monthly = (
            build(conn, store, kind, local_today=lived["local_today"], now=now)
            for kind in (BriefingKind.DAILY, BriefingKind.WEEKLY, BriefingKind.MONTHLY)
        )
    for content in (daily, weekly, monthly):
        assert_grounded(content)
    top = next(s for s in daily.sections if s.key == "top_items").items
    item = next(i for i in top if i.incident_id == lived["incident"])
    assert item.decision_id == str(lived["pending"].decision_id)
    recommended = lived["pending"].option(lived["pending"].recommended_option_id)
    assert f"Recommended: {wording.option(recommended.kind)}, expected net-profit change {{{{F" in (
        item.text
    )
    assert [b.kind.value for b in item.buttons] == ["approve", "review", "evidence"]
    assert item.buttons[0].option_id == lived["pending"].recommended_option_id
    pending = next(s for s in daily.sections if s.key == "pending_decisions")
    assert str(lived["pending"].decision_id) not in {i.decision_id for i in pending.items}
    texts = [i.text for i in next(s for s in weekly.sections if s.key == "decisions").items]
    assert any(t.startswith("Decision on {{E:campaign:") for t in texts)
    assert any(t.startswith("Executed: pause a campaign") for t in texts)
    measured = lived["outcome"]["status"] == "measured"
    outcome = next(t for t in texts if t.startswith("Outcome on"))
    assert ("measured effect" in outcome) is measured
    if measured:
        assert "against a prediction of {{F" in outcome
    review = [i.text for i in next(s for s in monthly.sections if s.key == "decision_review").items]
    assert any(str(lived["done"].decision_id) and "pause the campaign" in t for t in review)
    trust = next(s for s in monthly.sections if s.key == "trust").items
    expected = "not enough measured outcomes yet" if measured else "no measured outcome yet"
    assert expected in trust[0].text


def test_wording_falls_back_to_plain_words() -> None:
    assert wording.option("pause_until_restock").startswith("pause the campaigns")
    assert wording.option("a_new_kind") == "a new kind"
    assert wording.cause(None) == "something changed"
