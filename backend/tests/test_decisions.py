"""Decisions: the database state machine, single approval, outbox in the same transaction, and
signed single-use approval links."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import product
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import tenant_transaction
from app.decisions.options import build_options
from app.decisions.store import (
    TRANSITIONS,
    Channel,
    DecisionError,
    DecisionStatus,
    DecisionView,
    Verdict,
    consume_link,
    create_link,
    decide,
    expire_due,
    get,
    list_decisions,
    propose,
    read_link,
    transition,
)
from app.facts.engine import FactEngine
from app.twin import fit_twin

pytestmark = pytest.mark.db
SECRET = "test-approval-secret"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


@pytest.fixture
def conn(app_engine: Engine, golden_stockout: dict[str, Any]) -> Iterator[Connection]:
    with tenant_transaction(app_engine, golden_stockout["id"]) as c:
        yield c


def proposed(conn: Connection, store: dict[str, Any], now: datetime = NOW) -> DecisionView:
    model = fit_twin(conn, store["id"])
    options = build_options(
        model, "stockout_on_promoted", f"product:{store['product']}", floor_monthly=Decimal(100)
    )
    return propose(
        conn,
        FactEngine(conn, store["id"]),
        model,
        options,
        source="incident",
        incident_id=store["incident"],
        now=now,
    )


def test_a_proposed_decision_holds_simulated_options(
    conn: Connection, golden_stockout: dict[str, Any]
) -> None:
    decision = proposed(conn, golden_stockout)
    assert decision.status is DecisionStatus.PROPOSED
    assert decision.recommended_option_id.startswith("stockout_on_promoted:pause_until_restock")
    pause = decision.option(decision.recommended_option_id)
    assert pause.executable
    assert pause.impact_fact_id is not None
    assert pause.p10 is not None
    assert pause.p50 is not None
    assert pause.p90 is not None
    assert pause.p10 <= pause.p50 <= pause.p90
    assert decision in list_decisions(conn, golden_stockout["id"])
    with pytest.raises(DecisionError, match="no option"):
        decision.option("missing")


def _drive(conn: Connection, d: DecisionView, path: list[DecisionStatus]) -> None:
    for status in path:
        option = d.recommended_option_id if status is DecisionStatus.APPROVED else None
        transition(conn, d.store_id, d.decision_id, status, approved_option_id=option)


PATHS = {
    DecisionStatus.PROPOSED: [],
    DecisionStatus.APPROVED: [DecisionStatus.APPROVED],
    DecisionStatus.REJECTED: [DecisionStatus.REJECTED],
    DecisionStatus.EXPIRED: [DecisionStatus.EXPIRED],
    DecisionStatus.EXECUTING: [DecisionStatus.APPROVED, DecisionStatus.EXECUTING],
    DecisionStatus.EXECUTED: [
        DecisionStatus.APPROVED,
        DecisionStatus.EXECUTING,
        DecisionStatus.EXECUTED,
    ],
    DecisionStatus.FAILED: [
        DecisionStatus.APPROVED,
        DecisionStatus.EXECUTING,
        DecisionStatus.FAILED,
    ],
    DecisionStatus.MEASURED: [
        DecisionStatus.APPROVED,
        DecisionStatus.EXECUTING,
        DecisionStatus.EXECUTED,
        DecisionStatus.MEASURED,
    ],
}


def test_the_database_refuses_every_illegal_transition(
    conn: Connection, golden_stockout: dict[str, Any]
) -> None:
    refused = 0
    for start in DecisionStatus:
        d = proposed(conn, golden_stockout)
        _drive(conn, d, PATHS[start])
        assert get(conn, d.store_id, d.decision_id).status is start
        for to in DecisionStatus:
            if (start, to) in TRANSITIONS:
                continue
            with (
                pytest.raises(DBAPIError, match="illegal decision transition"),
                conn.begin_nested(),
            ):
                transition(conn, d.store_id, d.decision_id, to)
            refused += 1
    assert refused == len(DecisionStatus) ** 2 - len(TRANSITIONS)
    allowed = {(a, b) for a, b in product(DecisionStatus, DecisionStatus)} - set(TRANSITIONS)
    assert len(allowed) == refused


def test_inserts_start_proposed_and_content_is_immutable(
    conn: Connection, golden_stockout: dict[str, Any]
) -> None:
    d = proposed(conn, golden_stockout)
    with pytest.raises(DBAPIError, match="starts as proposed"), conn.begin_nested():
        conn.execute(
            text(
                "INSERT INTO decisions (decision_id, store_id, source, cause, entity, status, "
                "recommended_option_id, horizon_days, floor, currency, as_of, expires_at, "
                "payload) SELECT gen_random_uuid(), store_id, source, cause, entity, 'approved', "
                "recommended_option_id, horizon_days, floor, currency, as_of, expires_at, "
                "payload FROM decisions WHERE decision_id = :d"
            ),
            {"d": d.decision_id},
        )
    with pytest.raises(DBAPIError, match="immutable"), conn.begin_nested():
        conn.execute(
            text(
                "UPDATE decisions SET status = 'approved', payload = '{}'::jsonb "
                "WHERE decision_id = :d"
            ),
            {"d": d.decision_id},
        )
    _drive(conn, d, [DecisionStatus.APPROVED])
    with pytest.raises(DBAPIError, match="approved option cannot change"), conn.begin_nested():
        conn.execute(
            text(
                "UPDATE decisions SET status = 'executing', approved_option_id = 'other' "
                "WHERE decision_id = :d"
            ),
            {"d": d.decision_id},
        )


def test_approval_queues_the_actions_in_the_same_transaction(
    conn: Connection, golden_stockout: dict[str, Any]
) -> None:
    d = proposed(conn, golden_stockout)
    approved = decide(
        conn,
        d.store_id,
        d.decision_id,
        d.recommended_option_id,
        Verdict.APPROVED,
        channel=Channel.API,
        actor="owner",
        now=NOW,
    )
    assert approved.status is DecisionStatus.APPROVED
    assert approved.approved_option_id == d.recommended_option_id
    rows = conn.execute(
        text(
            "SELECT a.kind, a.status, a.provider, a.idempotency_key, o.status AS outbox "
            "FROM actions a JOIN outbox o ON o.action_id = a.action_id "
            "WHERE a.decision_id = :d ORDER BY a.seq"
        ),
        {"d": d.decision_id},
    ).all()
    pauses = d.option(d.recommended_option_id).actions
    assert [r.kind for r in rows] == ["pause_campaign"] * len(pauses)
    assert {(r.status, r.outbox, r.provider) for r in rows} == {("pending", "pending", "simulator")}
    assert rows[0].idempotency_key == f"{d.decision_id}:{d.recommended_option_id}:0"
    # A second decision, from another channel, is refused: by code, and by the database.
    with pytest.raises(DecisionError, match="already approved"):
        decide(
            conn,
            d.store_id,
            d.decision_id,
            None,
            Verdict.REJECTED,
            channel=Channel.EMAIL,
            actor="owner",
        )
    with pytest.raises(IntegrityError), conn.begin_nested():
        conn.execute(
            text(
                "INSERT INTO approvals (approval_id, store_id, decision_id, verdict, channel, "
                "actor) VALUES (gen_random_uuid(), :s, :d, 'rejected', 'email', 'x')"
            ),
            {"s": d.store_id, "d": d.decision_id},
        )
    with pytest.raises(IntegrityError), conn.begin_nested():  # idempotency key is unique
        conn.execute(
            text(
                "INSERT INTO actions (action_id, store_id, decision_id, option_id, seq, kind, "
                "campaign_id, provider, params, idempotency_key, status) SELECT "
                "gen_random_uuid(), store_id, decision_id, option_id, seq, kind, campaign_id, "
                "provider, params, idempotency_key, 'pending' FROM actions WHERE decision_id = :d "
                "LIMIT 1"
            ),
            {"d": d.decision_id},
        )


def test_rejection_and_expiry(conn: Connection, golden_stockout: dict[str, Any]) -> None:
    d = proposed(conn, golden_stockout)
    rejected = decide(
        conn, d.store_id, d.decision_id, None, Verdict.REJECTED, channel=Channel.API, actor="o"
    )
    assert rejected.status is DecisionStatus.REJECTED
    late = proposed(conn, golden_stockout)
    with pytest.raises(DecisionError, match="expired"):
        decide(
            conn,
            late.store_id,
            late.decision_id,
            late.recommended_option_id,
            Verdict.APPROVED,
            channel=Channel.API,
            actor="o",
            now=late.expires_at + timedelta(seconds=1),
        )
    assert get(conn, late.store_id, late.decision_id).status is DecisionStatus.EXPIRED
    stale = proposed(conn, golden_stockout)
    assert expire_due(conn, stale.store_id, now=stale.expires_at) >= 1
    manual = next(o for o in proposed(conn, golden_stockout).options if not o.executable)
    fresh = proposed(conn, golden_stockout)
    with pytest.raises(DecisionError, match="executable"):
        decide(
            conn,
            fresh.store_id,
            fresh.decision_id,
            manual.option_id,
            Verdict.APPROVED,
            channel=Channel.API,
            actor="o",
            now=NOW,
        )


def test_email_links_are_signed_single_use_and_expire(
    conn: Connection, golden_stockout: dict[str, Any]
) -> None:
    d = proposed(conn, golden_stockout)
    token = create_link(
        conn,
        d.store_id,
        d.decision_id,
        d.recommended_option_id,
        Verdict.APPROVED,
        secret=SECRET,
        now=NOW,
    )
    claims = read_link(token, secret=SECRET, now=NOW)
    assert (claims.decision_id, claims.verdict) == (d.decision_id, Verdict.APPROVED)
    with pytest.raises(DecisionError, match="signature"):
        read_link(token, secret="another-secret", now=NOW)
    body, signature = token.split(".")
    with pytest.raises(DecisionError, match="signature"):
        read_link(body[:-2] + "AA." + signature, secret=SECRET, now=NOW)
    with pytest.raises(DecisionError, match="malformed"):
        read_link("no-dot", secret=SECRET, now=NOW)
    with pytest.raises(DecisionError, match="expired"):
        read_link(token, secret=SECRET, now=NOW + timedelta(hours=24, seconds=1))
    consume_link(conn, claims, now=NOW)
    with pytest.raises(DecisionError, match="already used"):
        consume_link(conn, claims, now=NOW)
    with pytest.raises(DecisionError, match="no option"):
        create_link(conn, d.store_id, d.decision_id, "missing", Verdict.APPROVED, secret=SECRET)
    assert isinstance(claims.store_id, UUID)
