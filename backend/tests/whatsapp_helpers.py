"""Signed webhook notifications built from the recorded payloads, and an inbox on fakes."""

import hashlib
import hmac
import json
from itertools import count
from pathlib import Path
from typing import Any

PAYLOADS = Path(__file__).resolve().parent / "fixtures" / "whatsapp"
APP_SECRET = "test-app-secret"
_ids = count(1)


def notification(name: str, sender: str, **content: Any) -> tuple[dict[str, Any], str]:
    """A recorded notification from `sender`, with a fresh message id; `content` replaces the
    message's body (text), media id (audio) or button id (button_reply, template_button)."""
    payload: dict[str, Any] = json.loads((PAYLOADS / f"{name}.json").read_text(encoding="utf-8"))
    value = payload["entry"][0]["changes"][0]["value"]
    message_id = f"wamid.test{next(_ids)}"
    for message in value.get("messages", []):
        message["from"], message["id"] = sender, message_id
        if "body" in content:
            message["text"]["body"] = content["body"]
        if "media_id" in content:
            message["audio"]["id"] = content["media_id"]
        if "button_id" in content and message["type"] == "interactive":
            message["interactive"]["button_reply"]["id"] = content["button_id"]
        if "button_id" in content and message["type"] == "button":
            message["button"]["payload"] = content["button_id"]
    for contact in value.get("contacts", []):
        contact["wa_id"] = sender
    return payload, message_id


def signed(payload: dict[str, Any], secret: str = APP_SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"}


class RecordingQueue:
    def __init__(self) -> None:
        self.ids: list[str] = []

    async def enqueue(self, message_id: str) -> None:
        self.ids.append(message_id)
