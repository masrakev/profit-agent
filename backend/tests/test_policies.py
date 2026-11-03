"""Policy engine rules, one by one, and the trust ledger's promotion proposal."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from app.db import tenant_transaction
from app.policies.engine import ActionRequest, Rule, evaluate, exceeds_caps, set_store_switch
from app.policies.trust import CONFIRMATIONS, entry, progress, trust_ledger
from app.settings.models import ActionType, AutonomyLevel
from app.settings.repository import StoreSettingsRepository

pytestmark = pytest.mark.db
NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)


def request(store: Any, **fields: Any) -> ActionRequest:
    base: dict[str, Any] = {
        "store_id": store,
        "kind": "pause_campaign",
        "campaign_id": uuid4(),
        "approved": True,
    }
    return ActionRequest(**{**base, **fields})


def test_each_rule(app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    store = golden_stockout["id"]
    with tenant_transaction(app_engine, store) as conn:
        assert evaluate(conn, request(store), now=NOW).rule is Rule.ALLOWED
        assert evaluate(conn, request(store, kind="change_price"), now=NOW).rule is (
            Rule.EXECUTABLE_ACTION
        )
        assert evaluate(conn, request(store, approved=False), now=NOW).rule is Rule.APPROVAL
        cap = evaluate(conn, request(store, kind="change_budget", change=Decimal("0.31")), now=NOW)
        assert (cap.allowed, cap.rule) == (False, Rule.BUDGET_CAP)
        assert evaluate(conn, request(store, kind="change_budget"), now=NOW).rule is (
            Rule.BUDGET_CAP  # a budget change needs its size
        )
        ok = evaluate(conn, request(store, kind="change_budget", change=Decimal("-0.3")), now=NOW)
        assert ok.allowed
        repo = StoreSettingsRepository(conn)
        settings = repo.get_or_default(store)
        autonomy = {
            **settings.autonomy,
            ActionType.PAUSE_CAMPAIGN: AutonomyLevel.OBSERVE,
            ActionType.CHANGE_BUDGET: AutonomyLevel.EXECUTE_CAPPED,
        }
        repo.save(settings.model_copy(update={"autonomy": autonomy}), actor="test")
        assert evaluate(conn, request(store), now=NOW).rule is Rule.AUTONOMY
        unapproved = request(store, kind="change_budget", change=Decimal("0.1"), approved=False)
        assert evaluate(conn, unapproved, now=NOW).allowed  # execute-capped needs no approval
        set_store_switch(conn, store, True, actor="test", reason="drill")
        assert evaluate(conn, unapproved, now=NOW).rule is Rule.STORE_KILL_SWITCH
        assert exceeds_caps(conn, store, [{"kind": "change_budget", "change": "0.5"}])
        assert not exceeds_caps(conn, store, [{"kind": "change_budget", "change": "-0.3"}])
        assert not exceeds_caps(conn, store, [{"kind": "pause_campaign", "change": None}])
        conn.rollback()


def test_the_trust_ledger_only_proposes(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    with tenant_transaction(app_engine, store) as conn:
        ledger = {e.action_type: e for e in trust_ledger(conn, store)}
    assert set(ledger) == {"pause_campaign", "resume_campaign", "change_budget"}
    for e in ledger.values():
        assert e.confirmations < CONFIRMATIONS
        assert e.proposal is None
        assert e.proposed_level is None
        assert e.threshold == CONFIRMATIONS
        assert e.level == int(AutonomyLevel.RECOMMEND)
        assert (
            e.progress == f"{e.confirmations} of 10 confirmations before I can ask to do this alone"
        )


def held(n: int) -> list[tuple[str, dict[str, Any]]]:
    """n measured outcomes whose effect fell inside the predicted range."""
    predicted = {"p10": "10", "p50": "20", "p90": "30"}
    return [
        ("measured", {"predicted": predicted, "effect": {"p10": "0", "p50": "21", "p90": "40"}})
    ] * n


def missed(n: int) -> list[tuple[str, dict[str, Any]]]:
    predicted = {"p10": "10", "p50": "20", "p90": "30"}
    return [
        ("measured", {"predicted": predicted, "effect": {"p10": "0", "p50": "-5", "p90": "1"}})
    ] * n


def test_a_promotion_is_proposed_after_ten_confirmations_only() -> None:
    change = ActionType.CHANGE_BUDGET
    nine = entry(change, AutonomyLevel.RECOMMEND, held(9), 0)
    assert (nine.confirmations, nine.threshold, nine.proposal, nine.proposed_level) == (
        9,
        10,
        None,
        None,
    )
    assert nine.progress == "9 of 10 confirmations before I can ask to do this alone"
    ten = entry(change, AutonomyLevel.RECOMMEND, [*held(10), ("abstained", {})], 0)
    assert (ten.proposed_level, ten.abstained) == (3, 1)
    assert ten.proposal == "propose autonomy level 3 for change_budget"
    assert ten.progress == "My predictions held 10 times: I can ask to do this alone."
    # Ten held, but too many missed (under 75%), or a rollback: no proposal.
    assert entry(change, AutonomyLevel.RECOMMEND, held(10) + missed(4), 0).proposal is None
    assert entry(change, AutonomyLevel.RECOMMEND, held(12), 1).proposal is None
    # At the top level there is nothing left to ask for.
    top = entry(change, AutonomyLevel.MANAGE_SCOPE, held(12), 0)
    assert (top.proposal, top.progress) == (None, None)


def test_progress_names_the_next_level() -> None:
    assert progress(1, AutonomyLevel.RECOMMEND, None) == (
        "1 of 10 confirmations before I can ask to do this alone"
    )
    assert progress(0, AutonomyLevel.OBSERVE, None) == (
        "0 of 10 confirmations before I can ask to recommend this"
    )
    assert progress(3, AutonomyLevel.EXECUTE_CAPPED, None) == (
        "3 of 10 confirmations before I can ask to manage this within its scope"
    )
