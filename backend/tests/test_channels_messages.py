"""Briefings, alerts and decisions rendered for email: escaping, links, and golden snapshots of
the demo store's messages (backend/tests/snapshots; UPDATE_SNAPSHOTS=1 rewrites them)."""

import os
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from sqlalchemy import Engine

from app.briefings.content import build, open_incidents
from app.briefings.models import BriefingKind, Button, ButtonKind, Document, Item, Section
from app.briefings.notices import alert_document, decision_document, notice_context
from app.channels.messages import Inputs, Links, load_inputs, render_briefing, render_document
from app.db import tenant_transaction
from app.decisions.options import build_options
from app.decisions.store import propose
from app.facts.engine import FactEngine
from app.twin import fit_twin

SNAPSHOTS = Path(__file__).with_name("snapshots")
DATA_END = date(2026, 9, 29)
LINKS = Links("https://app.example", approval_token=lambda d, o: f"token-{o}")


def snapshot(name: str, content: str) -> None:
    path = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not path.exists():
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    assert content == path.read_text(encoding="utf-8"), f"{name} changed (UPDATE_SNAPSHOTS=1)"


def test_merchant_text_is_escaped_everywhere() -> None:
    product = "product:00000000-0000-0000-0000-000000000001"
    document = Document(
        headline="{{E:store}} has news.",
        sections=(
            Section(
                key="s",
                title="Products",
                items=(
                    Item(
                        text=f"{{{{E:{product}}}}} sells.",
                        level="high",
                        buttons=(
                            Button(kind=ButtonKind.EVIDENCE, label="Evidence", incident_id="i/1"),
                        ),
                    ),
                ),
            ),
        ),
        entities=("store", product),
    )
    inputs = Inputs(
        facts={},
        names={
            "store": '<script>alert("x")</script>\r\nBcc: someone@example.com',
            product: "Visit https://evil.example *now* {{F1}}",
        },
    )
    out = render_document(document, inputs, LINKS)
    assert "<script>" not in out.html
    assert "&lt;script&gt;" in out.html
    assert "\n" not in out.subject
    assert "\r" not in out.subject
    assert out.subject.startswith('<script>alert("x")</script> Bcc:')  # one line: no new header
    assert "https[:]//evil.example" in out.text  # a name never becomes a link
    assert "{{F1}}" in out.text  # a name is never read as a reference
    assert 'href="https://app.example/incidents/i%2F1"' in out.html


@pytest.mark.db
def test_the_demo_store_messages(app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    store = golden_stockout["id"]
    later = datetime.now(UTC) + timedelta(days=5)  # decisions of other tests have expired
    with tenant_transaction(app_engine, store) as conn:
        brief = build(conn, store, BriefingKind.DAILY, local_today=DATA_END, now=later)
        inputs = load_inputs(conn, store, brief)
        yesterday = next(
            fid
            for fid, f in inputs.facts.items()
            if f.formula_id == "net_profit" and f.period.end - f.period.start == timedelta(days=1)
        )
        daily = render_briefing(
            brief, f"Net profit was {{{{F{yesterday}}}}} yesterday.", inputs, LINKS
        )
        [incident] = [i for i in open_incidents(conn, store) if i.alert.value == "critical"]
        alert = alert_document(notice_context(conn, store, later), incident)
        alert_out = render_document(alert, load_inputs(conn, store, alert), LINKS)
        # A decision on the incident, rolled back at the end of the test.
        now = datetime.now(UTC)
        model = fit_twin(conn, store)
        options = build_options(
            model,
            "stockout_on_promoted",
            f"product:{golden_stockout['product']}",
            floor_monthly=Decimal(100),
        )
        decision = propose(
            conn,
            FactEngine(conn, store),
            model,
            options,
            source="incident",
            incident_id=incident.incident_id,
            now=now,
        )
        ctx = notice_context(conn, store, now)
        with_options = alert_document(ctx, incident)
        decided = decision_document(notice_context(conn, store, now), decision)
        with_options_out = render_document(
            with_options, load_inputs(conn, store, with_options), LINKS
        )
        decision_out = render_document(decided, load_inputs(conn, store, decided), LINKS)
        conn.rollback()
    assert daily.subject.endswith(
        "Daily brief, Monday 28 September 2026: A critical problem needs your attention today."
    )
    assert alert_out.subject.endswith(
        "Critical alert: Deluxe Bottle 23: ads keep spending on a product that is out of stock."
    )
    assert [s.key for s in with_options.sections] == [
        "detected",
        "why",
        "evidence",
        "uncertain",
        "options",
        "next_step",
    ]
    token = quote(f"token-{decision.recommended_option_id}", safe="")
    approve = f"https://app.example/approve#token={token}"
    assert approve in with_options_out.text

    def stable(text: str) -> str:
        return re.sub(str(decision.decision_id), "<decision>", text)

    snapshot("daily-brief.email.html.snap", daily.html)
    snapshot("daily-brief.email.txt.snap", daily.text)
    snapshot("alert.email.html.snap", alert_out.html)
    snapshot("alert-with-options.email.txt.snap", stable(with_options_out.text))
    snapshot("decision.email.html.snap", stable(decision_out.html))
    snapshot("decision.email.txt.snap", stable(decision_out.text))


@pytest.mark.db
def test_weekly_and_monthly_emails(app_engine: Engine, golden_stockout: dict[str, Any]) -> None:
    store = golden_stockout["id"]
    later = datetime.now(UTC) + timedelta(days=5)
    with tenant_transaction(app_engine, store) as conn:
        week = build(conn, store, BriefingKind.WEEKLY, local_today=DATA_END, now=later)
        month = build(conn, store, BriefingKind.MONTHLY, local_today=DATA_END, now=later)
        weekly = render_briefing(week, None, load_inputs(conn, store, week), LINKS)
        monthly = render_briefing(month, None, load_inputs(conn, store, month), LINKS)
    assert "Weekly report, 21 September to 27 September 2026: Your week." in weekly.subject
    assert "Monthly review, August 2026: Your month." in monthly.subject
    assert weekly.html.count("<table") == 3  # the layout's two, and the campaigns
    assert monthly.html.count("<table") == 4  # and unit economics
    campaign = next(line for line in weekly.text.splitlines() if "; POAS: " in line)
    assert campaign.startswith("- Campaign ")
    assert "Spend: $" in campaign


def test_a_long_subject_is_cut() -> None:
    document = Document(headline="{{E:store}} news.", sections=(), entities=("store",))
    out = render_document(document, Inputs(facts={}, names={"store": "S" * 300}), LINKS)
    assert len(out.subject) == 180
    assert out.subject.endswith("…")
