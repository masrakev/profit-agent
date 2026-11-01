"""The WhatsApp webhook (ADR 0027): who may call it, what it keeps, and how fast it answers.

- Handshake: Meta's `GET` carries `hub.mode=subscribe`, `hub.verify_token` and `hub.challenge`;
  the challenge is echoed back only when the token is ours.
- Every `POST` is signed: `X-Hub-Signature-256: sha256=<hex>`, the HMAC-SHA256 of the raw body
  keyed with the app secret. A missing or wrong signature is refused before the body is read as
  JSON; nothing is stored.
- Each message is stored once, by its WhatsApp message id (the primary key of
  `whatsapp.inbound`): Meta retries a delivery for up to 36 hours and may send it twice, and a
  replayed id is acknowledged and ignored. The webhook answers at once; a job processes the
  message (app.whatsapp.inbound).

Kept from a message: a text's body, a voice note's media id, a button's id; any other kind is
only its type. Statuses of sent messages are counted, not stored.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text

MAX_TEXT = 4096
PREFIX = "sha256="


def signature_valid(header: str | None, body: bytes, secret: str) -> bool:
    if not header or not header.startswith(PREFIX) or not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len(PREFIX) :].strip().lower(), expected)


def handshake(mode: str | None, token: str | None, challenge: str | None, ours: str) -> str | None:
    """The challenge to echo, or None to refuse."""
    if mode != "subscribe" or not ours or token is None or challenge is None:
        return None
    if not hmac.compare_digest(token, ours) or not challenge.isdigit() or len(challenge) > 64:
        return None
    return challenge


@dataclass(frozen=True)
class Inbound:
    message_id: str
    phone: str
    kind: str  # text | audio | button | other
    content: dict[str, Any]


def _content(message: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    kind = message.get("type")
    if kind == "text":
        return "text", {"body": str((message.get("text") or {}).get("body", ""))[:MAX_TEXT]}
    if kind == "audio":
        audio = message.get("audio") or {}
        return "audio", {
            "media_id": str(audio.get("id", "")),
            "mime_type": str(audio.get("mime_type", "")),
            "voice": bool(audio.get("voice", False)),
        }
    if kind == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply")
        if interactive.get("type") == "button_reply" and isinstance(reply, dict):
            return "button", {"id": str(reply.get("id", "")), "title": str(reply.get("title"))}
    if kind == "button":  # a template's quick reply: the payload is the button id
        button = message.get("button") or {}
        return "button", {"id": str(button.get("payload", "")), "title": str(button.get("text"))}
    return "other", {"type": str(kind)}


def parse(payload: Any) -> tuple[list[Inbound], int]:
    """The messages in a notification, and how many statuses it carried."""
    messages: list[Inbound] = []
    statuses = 0
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return messages, statuses
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            if (change or {}).get("field") != "messages":
                continue
            value = change.get("value") or {}
            statuses += len(value.get("statuses") or [])
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                message_id, phone = str(message.get("id", "")), str(message.get("from", ""))
                if not 1 <= len(message_id) <= 256 or not phone.isdigit():
                    continue
                kind, content = _content(message)
                messages.append(Inbound(message_id, phone, kind, content))
    return messages, statuses


def store(engine: Engine, messages: list[Inbound]) -> list[str]:
    """Store the messages not seen before; their ids (a replayed id is not returned)."""
    new: list[str] = []
    with engine.begin() as conn:
        for m in messages:
            inserted = conn.execute(
                text(
                    "INSERT INTO whatsapp.inbound (message_id, phone, kind, content, status) "
                    "VALUES (:m, :p, :k, CAST(:c AS jsonb), 'pending') "
                    "ON CONFLICT (message_id) DO NOTHING RETURNING message_id"
                ),
                {"m": m.message_id, "p": m.phone, "k": m.kind, "c": json.dumps(m.content)},
            ).scalar()
            if inserted is not None:
                new.append(inserted)
    return new
