"""Policy engine rules, one by one, and the trust ledger's promotion proposal."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from app.db import tenant_transaction
from app.policies.engine import ActionRequest, Rule, evaluate, exceeds_caps, set_store_switch
from app.policies.trust import MIN_OUTCOMES, trust_ledger
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
    for entry in ledger.values():
        assert entry.measured < MIN_OUTCOMES
        assert entry.proposal is None
        assert entry.level == int(AutonomyLevel.RECOMMEND)
