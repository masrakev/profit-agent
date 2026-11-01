"""WhatsApp through the Cloud API, behind one interface (ADR 0027).

Messages go to `POST https://graph.facebook.com/{version}/{phone_number_id}/messages` with the
access token (Graph API reference and guides, checked on 2026-11-01):

- text: `{"type": "text", "text": {"body": ..., "preview_url": false}}`;
- reply buttons: `{"type": "interactive", "interactive": {"type": "button", "body": {"text"},
  "footer": {"text"}, "action": {"buttons": [{"type": "reply", "reply": {"id", "title"}}]}}}`,
  at most 3 buttons, a title at most 20 characters, an id at most 256, the body at most 1024,
  the footer at most 60;
- an approved template, the only message a business may start more than 24 hours after the
  owner last wrote: `{"type": "template", "template": {"name", "language": {"code"},
  "components": [{"type": "body", "parameters": [{"type": "text", "text"}]}, {"type":
  "button", "sub_type": "quick_reply", "index": "0", "parameters": [{"type": "payload",
  "payload"}]}]}}`. Template parameters hold no line break, tab or run of spaces; an
  authentication template's copy-code button takes the code as a `url` button parameter.

Media (a voice note): `GET /{version}/{media_id}` returns a URL valid five minutes, which is
then fetched with the same token. Errors are `{"error": {"message", "type", "code",
"error_data": {"details"}, "fbtrace_id"}}`; worth retrying: 131000 (unknown), 130429
(throughput), 131056 (too many to one number), 4 and 80007 (rate limits), any HTTP 5xx, a
timeout or a lost connection. 131047 means more than 24 hours have passed since the owner last
wrote: a template is needed.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx2

from app.config import Settings

API_VERSION = "v25.0"
MAX_TEXT = 4096
MAX_BODY = 1024
MAX_FOOTER = 60
MAX_BUTTONS = 3
MAX_TITLE = 20
MAX_BUTTON_ID = 256
MAX_PARAM = 900
RETRYABLE_CODES = frozenset({131000, 130429, 131056, 4, 80007})
WINDOW_CLOSED = 131047
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class ReplyButton:
    id: str
    title: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.id) <= MAX_BUTTON_ID or not 1 <= len(self.title) <= MAX_TITLE:
            raise ValueError("a reply button holds an id of 1-256 and a title of 1-20 characters")


@dataclass(frozen=True)
class WhatsAppMessage:
    """What to say: a session message (text, with reply buttons) and, for when the 24-hour window
    is closed, the approved template that says the same in single-line parameters."""

    text: str
    buttons: tuple[ReplyButton, ...] = ()
    footer: str | None = None
    template: str | None = None
    params: tuple[str, ...] = ()
    copy_code: str | None = None  # an authentication template's one-time code button

    def __post_init__(self) -> None:
        if len(self.buttons) > MAX_BUTTONS:
            raise ValueError("at most three reply buttons")


class WhatsAppError(Exception):
    def __init__(self, message: str, *, retryable: bool, code: int | str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code

    @property
    def window_closed(self) -> bool:
        return self.code == WINDOW_CLOSED


class WhatsAppSender(Protocol):
    @property
    def provider(self) -> str: ...

    def send(self, to: str, message: WhatsAppMessage, *, session: bool) -> str:
        """Send a session message (`session`) or the message's template; the message id."""
        ...

    def download(self, media_id: str, *, max_bytes: int) -> bytes: ...


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _param(text: str) -> str:
    return _cut(_SPACES.sub(" ", text).strip(), MAX_PARAM) or "-"


def payload(to: str, message: WhatsAppMessage, *, session: bool, language: str) -> dict[str, Any]:
    """The `messages` request body."""
    base: dict[str, Any] = {"messaging_product": "whatsapp", "recipient_type": "individual"}
    base["to"] = to
    if not session:
        if message.template is None:
            raise WhatsAppError("no template for a message outside the window", retryable=False)
        components: list[dict[str, Any]] = [
            {
                "type": "body",
                "parameters": [{"type": "text", "text": _param(p)} for p in message.params],
            }
        ]
        components += [
            {
                "type": "button",
                "sub_type": "quick_reply",
                "index": str(i),
                "parameters": [{"type": "payload", "payload": b.id}],
            }
            for i, b in enumerate(message.buttons)
        ]
        if message.copy_code is not None:
            components.append(
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": message.copy_code}],
                }
            )
        return {
            **base,
            "type": "template",
            "template": {
                "name": message.template,
                "language": {"code": language},
                "components": components,
            },
        }
    if not message.buttons:
        return {
            **base,
            "type": "text",
            "text": {"body": _cut(message.text, MAX_TEXT), "preview_url": False},
        }
    interactive: dict[str, Any] = {
        "type": "button",
        "body": {"text": _cut(message.text, MAX_BODY)},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": b.id, "title": b.title}} for b in message.buttons
            ]
        },
    }
    if message.footer:
        interactive["footer"] = {"text": _cut(message.footer, MAX_FOOTER)}
    return {**base, "type": "interactive", "interactive": interactive}


def _error(response: httpx2.Response) -> WhatsAppError:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    code = error.get("code")
    details = (error.get("error_data") or {}).get("details") or error.get("message") or ""
    retryable = response.status_code >= 500 or code in RETRYABLE_CODES
    return WhatsAppError(
        f"HTTP {response.status_code} {code}: {details}"[:300], retryable=retryable, code=code
    )


@dataclass
class CloudApiSender:
    access_token: str
    phone_number_id: str
    api_version: str = API_VERSION
    language: str = "en"
    timeout_s: float = 10.0
    transport: httpx2.BaseTransport | None = None
    base_url: str = "https://graph.facebook.com"
    _client: httpx2.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx2.Client(
            transport=self.transport or httpx2.HTTPTransport(retries=0),
            timeout=self.timeout_s,
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

    @property
    def provider(self) -> str:
        return "whatsapp:cloud"

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{self.api_version}/{path}"

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx2.Response:
        try:
            response = self._client.request(method, url, **kwargs)
        except (httpx2.TimeoutException, httpx2.TransportError) as exc:
            raise WhatsAppError(f"{type(exc).__name__}: {exc}"[:300], retryable=True) from exc
        if response.status_code >= 400:
            raise _error(response)
        return response

    def send(self, to: str, message: WhatsAppMessage, *, session: bool) -> str:
        body = payload(to, message, session=session, language=self.language)
        response = self._request("POST", self._url(f"{self.phone_number_id}/messages"), json=body)
        try:
            return str(response.json()["messages"][0]["id"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise WhatsAppError("unexpected response to a message", retryable=False) from exc

    def download(self, media_id: str, *, max_bytes: int) -> bytes:
        meta = self._request(
            "GET", self._url(media_id), params={"phone_number_id": self.phone_number_id}
        ).json()
        size = meta.get("file_size")
        if isinstance(size, int) and size > max_bytes:
            raise WhatsAppError("the voice note is too large", retryable=False, code="too_large")
        url = meta.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise WhatsAppError("no media URL", retryable=False)
        data = bytearray()
        try:
            with self._client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise _error(response)
                for chunk in response.iter_bytes():
                    data += chunk
                    if len(data) > max_bytes:
                        raise WhatsAppError(
                            "the voice note is too large", retryable=False, code="too_large"
                        )
        except (httpx2.TimeoutException, httpx2.TransportError) as exc:
            raise WhatsAppError(f"{type(exc).__name__}: {exc}"[:300], retryable=True) from exc
        return bytes(data)

    def close(self) -> None:
        self._client.close()


@dataclass
class FakeWhatsApp:
    """Keeps messages in memory and serves media from a dict (tests, dry runs, the demo)."""

    sent: list[tuple[str, WhatsAppMessage, bool]] = field(default_factory=list)
    failures: list[WhatsAppError] = field(default_factory=list)  # raised first, in order
    media: dict[str, bytes] = field(default_factory=dict)

    @property
    def provider(self) -> str:
        return "whatsapp:fake"

    def send(self, to: str, message: WhatsAppMessage, *, session: bool) -> str:
        if self.failures:
            raise self.failures.pop(0)
        payload(to, message, session=session, language="en")  # the same validation
        self.sent.append((to, message, session))
        return f"wamid.fake{len(self.sent)}"

    def download(self, media_id: str, *, max_bytes: int) -> bytes:
        if media_id not in self.media:
            raise WhatsAppError(f"no media {media_id}", retryable=False, code=131052)
        data = self.media[media_id]
        if len(data) > max_bytes:
            raise WhatsAppError("the voice note is too large", retryable=False, code="too_large")
        return data


def sender_from_settings(settings: Settings) -> CloudApiSender | None:
    """The Cloud API sender, or None while the credentials are not set."""
    token, number = settings.whatsapp_access_token, settings.whatsapp_phone_number_id
    if token is None or not token.get_secret_value() or not number:
        return None
    return CloudApiSender(
        access_token=token.get_secret_value(),
        phone_number_id=number,
        api_version=settings.whatsapp_api_version,
        language=settings.whatsapp_template_language,
    )
