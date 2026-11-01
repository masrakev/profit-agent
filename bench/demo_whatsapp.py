"""The stockout alert on WhatsApp, approved from the phone (Task 8 part B, ADR 0027).

    uv run python -m bench.demo_whatsapp   # make demo-whatsapp: seeds the demo store afresh,
                                           # writes bench/reports/demo-whatsapp.md

1. The demo store is seeded as `make demo-seed` does (bench/demo_seed.py): the critical stockout
   alert (ads still spending on a product that is out of stock), its decision pending.
2. The owner adds a WhatsApp number in the settings, receives the code on WhatsApp and types it
   on the web; WhatsApp joins the store's channels.
3. The alert is delivered on WhatsApp by the delivery worker: what was detected, the impact (a
   range), the recommended option, and the buttons "Approve" and "See options". The owner has
   not written in 24 hours, so it goes as the approved template.
4. The owner taps "Approve". Meta posts the quick reply to the webhook, signed; it is stored once
   and processed: the button's signed, single-use token approves the recommended option through
   the normal decision flow (channel `whatsapp`).
5. The executor runs the policy engine and executes the pause, on the Meta sandbox when its
   credentials are set, else on the documented-contract fake, mirrored on the simulator.
6. The owner hears how it went: the decision's status, as a session message (the owner wrote
   minutes ago). Tapping "Approve" again decides nothing.

WhatsApp is the fake adapter until WhatsApp credentials exist: the messages are shown as sent.
"""

import hashlib
import hmac
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

from app.api.deps import get_app_settings, get_engine
from app.api.main import app
from app.api.whatsapp import get_inbound_queue, get_whatsapp_sender
from app.channels.email import RecordingSender
from app.channels.whatsapp import FakeWhatsApp, WhatsAppMessage
from app.config import Settings, get_settings
from app.db import make_engine, tenant_transaction
from app.decisions.store import get
from app.delivery.queue import Subject, enqueue
from app.delivery.worker import DeliveryWorker
from app.executor.simulator import SimulatorAdapter
from app.executor.worker import Executor
from app.observability import configure_logging
from app.settings.models import AlertChannel
from app.whatsapp.inbound import Inbox
from app.whatsapp.webhook import PREFIX
from bench.demo import _meta
from bench.demo_seed import DEMO_DB, Seeded, demo_provider, seed
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR

OWNER_NUMBER = "+15550100777"
APP_SECRET = "demo-app-secret"  # noqa: S105 - the demo's webhook signing key, not a credential
APP_BASE_URL = "https://app.example"


@dataclass
class Queue:
    ids: list[str]

    async def enqueue(self, message_id: str) -> None:
        self.ids.append(message_id)


class Unused:
    """The demo asks nothing by voice."""

    def transcribe(self, request: Any) -> Any:
        raise AssertionError("no voice note in the demo")


def tap(button_id: str, title: str, message_id: str, sender: str) -> dict[str, Any]:
    """Meta's notification of a template quick reply tapped (the recorded shape)."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "102290129340398",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550783881",
                                "phone_number_id": "106540352242922",
                            },
                            "contacts": [{"profile": {"name": "Store owner"}, "wa_id": sender}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": message_id,
                                    "timestamp": str(int(datetime.now(UTC).timestamp())),
                                    "type": "button",
                                    "button": {"payload": button_id, "text": title},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _post(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    signature = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/whatsapp/webhook",
        content=body,
        headers={"X-Hub-Signature-256": f"{PREFIX}{signature}"},
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def _shown(message: WhatsAppMessage, session: bool) -> dict[str, Any]:
    return {
        "text": message.text,
        "buttons": [b.title for b in message.buttons],
        "as": "session message" if session else f"template {message.template}",
    }


def run(engine: Engine, settings: Settings, seeded: Seeded) -> dict[str, Any]:
    store = seeded.store_id
    label = seeded.manifest.labels[0]
    campaign = next(e.id for e in label.entities if e.kind.value == "campaign")
    assert campaign is not None
    with tenant_transaction(engine, store) as conn:
        budget = conn.execute(
            text("SELECT daily_budget FROM ad_campaigns WHERE store_id = :s AND id = :c"),
            {"s": store, "c": campaign},
        ).scalar_one()
        alert_id: UUID = conn.execute(
            text("SELECT alert_id FROM alerts WHERE store_id = :s AND decision_id = :d"),
            {"s": store, "d": seeded.decision_id},
        ).scalar_one()
    meta, links, meta_mode, _ = _meta(settings, campaign, budget)
    signing = settings.approval_link_secret or SecretStr("demo-secret")
    settings = settings.model_copy(
        update={
            "meta_campaign_links": links,
            "approval_link_secret": signing,
            "whatsapp_app_secret": SecretStr(APP_SECRET),
        }
    )
    whatsapp, queue = FakeWhatsApp(), Queue([])
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_whatsapp_sender] = lambda: whatsapp
    app.dependency_overrides[get_inbound_queue] = lambda: queue
    try:
        client = TestClient(app, headers={"Authorization": f"Bearer {seeded.api_token}"})
        base = f"/api/v1/stores/{store}"
        # 2. the number, verified by the code it receives; WhatsApp among the channels
        current = client.get(f"{base}/settings").json()
        channels = [*current["alert_channels"], AlertChannel.WHATSAPP.value]
        client.put(
            f"{base}/settings",
            json={**current, "whatsapp_number": OWNER_NUMBER, "alert_channels": channels},
        ).raise_for_status()
        client.post(f"{base}/whatsapp/verification").raise_for_status()
        code = whatsapp.sent[-1][1].params[0]
        verified = client.post(f"{base}/whatsapp/verification/confirm", json={"code": code})
        verified.raise_for_status()
        # 3. the alert, delivered on WhatsApp
        now = datetime.now(UTC)
        with tenant_transaction(engine, store) as conn:
            enqueue(
                conn,
                store,
                Subject.ALERT,
                str(alert_id),
                channels=(AlertChannel.WHATSAPP,),
                recipient=None,
                available_at=now,
                now=now,
            )
        delivery = DeliveryWorker(
            engine,
            RecordingSender(),
            APP_BASE_URL,
            approval_secret=signing.get_secret_value(),
            whatsapp=whatsapp,
        )
        delivery.run_once()
        _, alert, alert_session = whatsapp.sent[-1]
        approve = next(b for b in alert.buttons if b.title == "Approve")
        # 4. the owner taps Approve: the webhook stores it, the job processes it
        sender = OWNER_NUMBER.removeprefix("+")
        received = _post(client, tap(approve.id, "Approve", "wamid.demo.approve", sender))
        inbox = Inbox(
            engine,
            whatsapp,
            demo_provider(settings),
            Unused(),
            None,
            APP_BASE_URL,
            approval_secret=signing.get_secret_value(),
            refusal_key=APP_SECRET,
            meta_links=links,
        )
        approved = inbox.process(queue.ids[-1])
        _, reply, reply_session = whatsapp.sent[-1]
        with tenant_transaction(engine, store) as conn:
            approval = conn.execute(
                text(
                    "SELECT channel, actor FROM approvals WHERE store_id = :s AND decision_id = :d"
                ),
                {"s": store, "d": seeded.decision_id},
            ).first()
        # 5. the executor: policy engine, then the pause
        Executor(
            engine, {"simulator": SimulatorAdapter(engine), "meta": meta}, meta_links=links
        ).run_once()
        with tenant_transaction(engine, store) as conn:
            decision = get(conn, store, seeded.decision_id)
            actions = [
                dict(r._mapping)
                for r in conn.execute(
                    text(
                        "SELECT kind, provider, status FROM actions WHERE store_id = :s AND "
                        "decision_id = :d ORDER BY seq"
                    ),
                    {"s": store, "d": seeded.decision_id},
                )
            ]
            policy = conn.execute(
                text(
                    "SELECT payload FROM audit_log WHERE store_id = :s AND action LIKE 'policy.%' "
                    "ORDER BY seq DESC LIMIT 1"
                ),
                {"s": store},
            ).scalar()
        # 6. how it went, on WhatsApp; and a second tap decides nothing
        delivery.run_once()
        _, status, status_session = whatsapp.sent[-1]
        _post(client, tap(approve.id, "Approve", "wamid.demo.again", sender))
        again = inbox.process(queue.ids[-1])
        _, again_reply, _ = whatsapp.sent[-1]
    finally:
        app.dependency_overrides.clear()
    return {
        "store": store,
        "alert": seeded.incident,
        "decision_id": seeded.decision_id,
        "number": OWNER_NUMBER,
        "verified": verified.json(),
        "alert_message": _shown(alert, alert_session),
        "received": received,
        "approved": approved,
        "approval": dict(approval._mapping) if approval else None,
        "reply": _shown(reply, reply_session),
        "decision_status": decision.status.value,
        "actions": actions,
        "policy": policy,
        "meta_mode": meta_mode,
        "status_message": _shown(status, status_session),
        "again": again,
        "again_reply": again_reply.text,
    }


def markdown(r: dict[str, Any], started: datetime) -> str:
    def quoted(shown: dict[str, Any]) -> list[str]:
        lines = [f"> {line}" for line in shown["text"].split("\n")]
        if shown["buttons"]:
            lines.append("> " + " ".join(f"[{b}]" for b in shown["buttons"]))
        return [*lines, "", f"Sent as: {shown['as']}.", ""]

    return "\n".join(
        [
            "# Demo: the stockout alert on WhatsApp",
            "",
            f"Run {started.isoformat()} on the demo store (`make demo-seed`), store "
            f"`{r['store']}`. WhatsApp: the fake adapter (no WhatsApp credentials); Meta side: "
            f"{r['meta_mode']}.",
            "",
            f"1. The owner's number `{r['number'][:-4]}****` is verified by the code it received "
            f"on WhatsApp (verified: {r['verified']['verified']}).",
            f"2. The critical alert `{r['alert'].incident_id}` arrives on WhatsApp:",
            "",
            *quoted(r["alert_message"]),
            f"3. The owner taps Approve. The webhook stores the signed notification "
            f"({r['received']['new']} new message) and the job processes it: `{r['approved']}`, "
            f"approval channel `{r['approval']['channel']}` by `{r['approval']['actor']}`. "
            "The reply:",
            "",
            *quoted(r["reply"]),
            "4. The executor runs the policy engine and executes: "
            + ", ".join(f"{a['kind']} on {a['provider']} ({a['status']})" for a in r["actions"])
            + f"; the decision is `{r['decision_status']}`.",
            "5. The owner hears how it went:",
            "",
            *quoted(r["status_message"]),
            f"6. Tapping Approve again: `{r['again']}`; the reply says: "
            f'"{r["again_reply"].split(":")[0]}".',
            "",
        ]
    )


def main() -> int:
    configure_logging("WARNING")
    started = datetime.now(UTC).replace(microsecond=0)
    engine = make_engine(prepare_database(DEMO_DB))
    settings = get_settings()
    result = run(engine, settings, seed(engine, demo_provider(settings)))
    text_ = markdown(result, started)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "demo-whatsapp.md").write_text(text_, encoding="utf-8", newline="\n")
    sys.stdout.write(text_)
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
