"""Short WhatsApp messages and the buttons that decide (app/whatsapp/formats.py, buttons.py):
every number a rendered fact, merchant text escaped, buttons signed, single use, store-bound."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from app.agent.ask import AskResult, QuestionType
from app.agent.contracts import Answer, Flag
from app.agent.session import UsageSummary
from app.briefings.content import build
from app.briefings.models import BriefingKind, Item
from app.channels.whatsapp import payload
from app.db import tenant_transaction
from app.decisions.proposals import propose_for_incident
from app.decisions.store import DecisionStatus, DecisionView
from app.detection.models import AlertLevel
from app.detection.repository import load_incident
from app.goals import service as goals
from app.whatsapp import buttons, formats
from app.whatsapp.buttons import ButtonError
from app.whatsapp.formats import Formats, help_message, refusal_message

pytestmark = pytest.mark.db
SECRET = "test-signing-secret"
BASE = "https://app.example"


def fmt(secret: str | None = SECRET) -> Formats:
    return Formats(BASE, secret, datetime.now(UTC))


def proposed(engine: Engine, store: dict[str, Any]) -> tuple[Any, DecisionView]:
    with tenant_transaction(engine, store["id"]) as conn:
        incident = load_incident(conn, store["id"], store["incident"])
        assert incident is not None
        decision = propose_for_incident(conn, store["id"], incident.incident, now=datetime.now(UTC))
    assert decision is not None
    return incident.incident, decision


def no_references(message: Any) -> None:
    for value in (message.text, *message.params):
        assert "{{" not in value


def test_buttons_are_short_signed_and_bound_to_their_store(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    _, decision = proposed(app_engine, golden_stockout)
    with tenant_transaction(app_engine, store) as conn:
        token = buttons.approve_button(
            conn, store, decision.decision_id, decision.recommended_option_id, secret=SECRET
        )
        parsed = buttons.parse(token, store, secret=SECRET)
        claims = buttons.approval_claims(conn, store, parsed.ref)
    assert len(token) <= 64  # a reply button id holds 256 at most
    assert parsed.kind == "d"
    assert claims is not None
    assert (claims.decision_id, claims.option_id) == (
        decision.decision_id,
        decision.recommended_option_id,
    )
    with pytest.raises(ButtonError, match="signature"):
        buttons.parse(token, uuid4(), secret=SECRET)  # another store's owner
    with pytest.raises(ButtonError, match="signature"):
        buttons.parse(token, store, secret="another secret")
    with pytest.raises(ButtonError, match="signature"):
        buttons.parse(
            token[:-2] + ("AA" if not token.endswith("AA") else "BB"), store, secret=SECRET
        )
    for junk in ("", "x", "d.notbase64!.sig", "z.AAAA.BBBB", "d.AAAAAAAAAAAAAAAAAAAAAA"):
        with pytest.raises(ButtonError):
            buttons.parse(junk, store, secret=SECRET)
    see = buttons.parse(buttons.options_button(decision.decision_id), store, secret=SECRET)
    assert (see.kind, see.ref) == ("o", decision.decision_id)
    with tenant_transaction(app_engine, store) as conn:
        assert buttons.approval_claims(conn, store, uuid4()) is None


def draft_goal(engine: Engine, store: UUID) -> UUID:
    with tenant_transaction(engine, store) as conn:
        today = goals.data_end(conn, store)
        goal = goals.create(
            conn,
            store,
            "net_profit",
            Decimal(1000),
            today + timedelta(days=30),
            now=datetime.now(UTC),
            question="a goal",
        )
    return goal.goal_id


def test_a_goal_button_works_once_and_expires(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    goal = draft_goal(app_engine, store)
    now = datetime.now(UTC)
    with tenant_transaction(app_engine, store) as conn:
        token = buttons.goal_button(conn, store, goal, secret=SECRET, now=now)
        link = buttons.parse(token, store, secret=SECRET)
        assert link.kind == "g"
        used = buttons.consume_goal_link(conn, store, link.ref, now)
        assert used is not None
        assert used.goal_id == goal
        assert buttons.consume_goal_link(conn, store, link.ref, now) is None  # once
        late = buttons.goal_button(conn, store, goal, secret=SECRET, now=now)
        later = now + buttons.LINK_TTL + timedelta(seconds=1)
        late_ref = buttons.parse(late, store, secret=SECRET).ref
        assert buttons.consume_goal_link(conn, store, late_ref, later) is None  # expired


def test_the_alert_what_impact_recommendation_and_buttons(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    incident, _ = proposed(app_engine, golden_stockout)
    with tenant_transaction(app_engine, store) as conn:
        message = fmt().alert(conn, store, incident)
        unsigned = fmt(None).alert(conn, store, incident)
    headline, impact, step = message.text.split("\n")
    assert headline.startswith("*Critical alert: ")
    assert "a month" in impact
    assert "–" in impact  # an estimate: its P10–P90 range
    assert step.startswith("Recommended: ")
    assert [b.title for b in message.buttons] == ["Approve", "See options"]
    assert message.buttons[0].id.startswith("d.")
    assert message.buttons[1].id.startswith("o.")
    assert (message.template, len(message.params)) == ("profit_alert", 3)
    no_references(message)
    template = payload("15550001", message, session=False, language="en")["template"]
    assert template["components"][1]["parameters"][0]["payload"] == message.buttons[0].id
    assert [b.title for b in unsigned.buttons] == ["See options"]  # no secret, nothing decides


def test_merchant_text_cannot_restyle_or_link(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    incident, _ = proposed(app_engine, golden_stockout)
    with tenant_transaction(app_engine, store) as conn:
        old = conn.execute(
            text("SELECT name FROM products WHERE id = :p"), {"p": golden_stockout["product"]}
        ).scalar_one()
        conn.execute(
            text("UPDATE products SET name = :n WHERE id = :p"),
            {"n": "*FREE* _now_ ~x~ `y` http://evil.example", "p": golden_stockout["product"]},
        )
        try:
            message = fmt().alert(conn, store, incident)
        finally:
            conn.execute(
                text("UPDATE products SET name = :n WHERE id = :p"),
                {"n": old, "p": golden_stockout["product"]},
            )
    body = message.text.split("\n", 1)[1]  # after the bold headline code adds
    if "FREE" in message.text:
        assert "*FREE*" not in message.text
        assert "http://" not in message.text
        assert "http[:]//evil" in message.text
    assert "*" not in body


def test_a_data_issue_alert_has_no_approve_button(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    incident, _ = proposed(app_engine, golden_stockout)
    data_issue = incident.model_copy(update={"alert": AlertLevel.DATA_QUALITY})
    with tenant_transaction(app_engine, store) as conn:
        message = fmt().alert(conn, store, data_issue)
    assert message.buttons == ()
    assert message.template == "data_alert"
    assert f"{BASE}/incidents/{incident.incident_id}" in message.text
    assert message.text.startswith("*Data issue, not a profit issue.*")


def test_the_daily_brief_health_line_and_top_item(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    proposed(app_engine, golden_stockout)
    now = datetime.now(UTC)
    with tenant_transaction(app_engine, store) as conn:
        end = goals.data_end(conn, store)
        daily = build(conn, store, BriefingKind.DAILY, local_today=end, now=now)
        weekly = build(conn, store, BriefingKind.WEEKLY, local_today=end, now=now)
        message = fmt().brief(conn, store, daily, uuid4())
        report_id = uuid4()
        report = fmt().brief(conn, store, weekly, report_id)
    title, health, top = message.text.split("\n")
    assert title.startswith("*Daily brief, ")
    assert health.startswith("Net profit yesterday ")
    assert top.startswith("Top: ")
    assert [b.title for b in message.buttons] == ["Approve", "See options"]
    assert (message.template, len(message.params)) == ("daily_brief", 3)
    no_references(message)
    assert f"{BASE}/briefings/{report_id}" in report.text
    assert report.buttons == ()


def test_a_decision_status_in_every_state(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    _, decision = proposed(app_engine, golden_stockout)
    with tenant_transaction(app_engine, store) as conn:
        pending = fmt().decision(conn, store, decision)
        states = {
            status: fmt().decision(
                conn,
                store,
                decision.model_copy(
                    update={
                        "status": status,
                        "approved_option_id": decision.recommended_option_id,
                    }
                ),
            )
            for status in formats.STATUS_WORDS
        }
        options = fmt().options(conn, store, decision)
    assert pending.text.startswith("A decision is waiting for your approval.")
    assert [b.title for b in pending.buttons] == ["Approve", "See options"]
    assert states[DecisionStatus.EXECUTED].text.startswith("Done: ")
    assert states[DecisionStatus.FAILED].text.startswith("Not done: ")
    assert states[DecisionStatus.SUPERSEDED].text.startswith("Replaced: ")
    for message in (pending, *states.values()):
        no_references(message)
        assert message.template == "decision_update"
    assert options.text.startswith("*Options*\n- ")
    assert f"{BASE}/decisions/{decision.decision_id}" in options.text
    assert [b.title for b in options.buttons] == ["Approve"]
    executed = decision.model_copy(update={"status": DecisionStatus.EXECUTED})
    with tenant_transaction(app_engine, store) as conn:
        assert fmt().options(conn, store, executed).buttons == ()


def test_goal_progress(
    app_engine: Engine, golden_stockout: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = golden_stockout["id"]
    goal = draft_goal(app_engine, store)
    _, decision = proposed(app_engine, golden_stockout)
    with tenant_transaction(app_engine, store) as conn:
        assert fmt().goal(conn, store, goal) is None  # no week tracked yet
        target = goals.get(conn, store, goal).target_fact_id
    tracked = Item(
        text=f"Your goal of {{{{F{target}}}}} in net profit: behind the plan.",
        decision_id=str(decision.decision_id),
        buttons=fmt_buttons(decision),
    )
    monkeypatch.setattr(formats, "goal_item", lambda ctx, g: tracked)
    with tenant_transaction(app_engine, store) as conn:
        message = fmt().goal(conn, store, goal)
    assert message is not None
    assert message.text.startswith("*Goal progress*\nYour goal of ")
    no_references(message)
    assert [b.title for b in message.buttons] == ["Approve", "See options"]
    assert message.template == "goal_update"


def fmt_buttons(decision: DecisionView) -> Any:
    from app.briefings.models import Button, ButtonKind

    did = str(decision.decision_id)
    return (
        Button(kind=ButtonKind.APPROVE, label="Approve", decision_id=did,
               option_id=decision.recommended_option_id),
        Button(kind=ButtonKind.REVIEW, label="Review options", decision_id=did),
    )  # fmt: skip


def result(store: UUID, answer: Answer, **fields: Any) -> AskResult:
    base: dict[str, Any] = {
        "ask_id": uuid4(),
        "store_id": store,
        "question": "q",
        "question_type": QuestionType.LOOKUP,
        "status": "answered",
        "answer": answer,
        "model": "muse-spark-1.3",
        "classification_model": "muse-spark-1.3",
        "prompt_version": "v",
        "usage": UsageSummary(),
        "classification_usage": UsageSummary(),
        "tool_calls": 0,
        "memo_hits": 0,
        "regenerations": 0,
        "verifier_violations": 0,
        "refused_tools": [],
        "stop_reason": None,
        "created_at": datetime.now(UTC),
    }
    return AskResult(**{**base, **fields})


def test_answers_render_facts_and_restated_goals_get_a_button(
    app_engine: Engine, golden_stockout: dict[str, Any]
) -> None:
    store = golden_stockout["id"]
    fact = golden_stockout["impact_fact"]
    answer = Answer(
        answer=f"{{{{E:store}}}} loses {{{{F{fact}}}}} a month.",
        evidence=[fact],
        reasoning=None,
        alternatives=[],
        uncertainty="An estimate.",
        recommendation="Pause the campaign that promotes the product.",
        would_change_my_mind="Stock arriving.",
        flags=[Flag.NO_INSTRUCTION_FOLLOWING_FROM_DATA],
    )
    goal = draft_goal(app_engine, store)
    with tenant_transaction(app_engine, store) as conn:
        plain = fmt().answer(conn, store, result(store, answer), heard="*pause* everything")
        restated = fmt().answer(
            conn, store, result(store, answer, status="confirmation", goal_id=goal)
        )
        confirmed = fmt().goal_confirmed(conn, store, result(store, answer))
    lines = plain.text.split("\n")
    assert lines[0] == "_Heard:_ “∗pause∗ everything”"  # the owner's words, escaped
    assert "{{" not in plain.text
    assert lines[2].startswith("Next step: ")
    assert "never followed" in lines[3]
    assert plain.buttons == ()
    assert [b.title for b in restated.buttons] == ["Confirm goal"]
    assert restated.buttons[0].id.startswith("g.")
    assert confirmed.text.startswith("*Goal confirmed*")
    assert f"{BASE}/goals" in confirmed.text


def test_fixed_replies() -> None:
    assert "nothing written here approves" in help_message().text
    assert "Nothing you send here is read" in refusal_message().text
    decision = uuid4()
    assert f"{BASE}/decisions/{decision}" in fmt().stale_button(decision).text
    assert BASE in fmt().stale_button().text
    assert "spending caps" in fmt().above_caps(decision).text
    for message in (help_message(), refusal_message()):
        assert not any(ch.isdigit() for ch in message.text)  # code text holds no number
