"""The WhatsApp Cloud API adapter (app/channels/whatsapp.py): the documented request bodies, the
limits, errors that are worth retrying, the 24-hour window, media download with a size cap."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.channels.whatsapp import (
    CloudApiSender,
    FakeWhatsApp,
    ReplyButton,
    WhatsAppError,
    WhatsAppMessage,
    payload,
    sender_from_settings,
)
from app.config import Settings

TO = "15551234567"
BUTTONS = (ReplyButton("d.token", "Approve"), ReplyButton("o.decision", "See options"))
ALERT = WhatsAppMessage(
    text="*Critical alert*\nAds still spend on a product out of stock.",
    buttons=BUTTONS,
    footer="Every number is a checked fact.",
    template="profit_alert",
    params=("Critical alert", "Ads still spend\non a   product out of stock."),
)


def sender(handler: Callable[[httpx2.Request], httpx2.Response]) -> tuple[CloudApiSender, list]:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    return (
        CloudApiSender(
            access_token="test-token",
            phone_number_id="1234",
            transport=httpx2.MockTransport(handle),
        ),
        seen,
    )


def sent(message_id: str = "wamid.A1") -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda r: httpx2.Response(
        200,
        json={
            "messaging_product": "whatsapp",
            "contacts": [{"input": TO, "wa_id": TO}],
            "messages": [{"id": message_id, "message_status": "accepted"}],
        },
    )


def error(status: int, code: int, details: str = "x") -> Callable[[httpx2.Request], Any]:
    return lambda r: httpx2.Response(
        status,
        json={
            "error": {
                "message": f"(#{code}) title",
                "type": "OAuthException",
                "code": code,
                "error_data": {"messaging_product": "whatsapp", "details": details},
                "fbtrace_id": "trace",
            }
        },
    )


def test_text_message() -> None:
    body = payload(TO, WhatsAppMessage(text="Hello"), session=True, language="en")
    assert body == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": TO,
        "type": "text",
        "text": {"body": "Hello", "preview_url": False},
    }
    long = payload(TO, WhatsAppMessage(text="x" * 5000), session=True, language="en")
    assert len(long["text"]["body"]) == 4096


def test_reply_buttons_message() -> None:
    body = payload(TO, ALERT, session=True, language="en")
    interactive = body["interactive"]
    assert (body["type"], interactive["type"]) == ("interactive", "button")
    assert interactive["body"] == {"text": ALERT.text}
    assert interactive["footer"] == {"text": "Every number is a checked fact."}
    assert interactive["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "d.token", "title": "Approve"}},
        {"type": "reply", "reply": {"id": "o.decision", "title": "See options"}},
    ]
    with pytest.raises(ValueError, match="1-20"):
        ReplyButton("x", "A title well over twenty")
    with pytest.raises(ValueError, match="1-256"):
        ReplyButton("x" * 257, "Approve")
    with pytest.raises(ValueError, match="three"):
        WhatsAppMessage(text="x", buttons=(BUTTONS[0],) * 4)


def test_template_outside_the_window() -> None:
    body = payload(TO, ALERT, session=False, language="en")
    template = body["template"]
    assert (body["type"], template["name"], template["language"]) == (
        "template",
        "profit_alert",
        {"code": "en"},
    )
    body_params, approve, options = template["components"]
    assert body_params == {
        "type": "body",
        "parameters": [
            {"type": "text", "text": "Critical alert"},
            {"type": "text", "text": "Ads still spend on a product out of stock."},  # one line
        ],
    }
    assert approve == {
        "type": "button",
        "sub_type": "quick_reply",
        "index": "0",
        "parameters": [{"type": "payload", "payload": "d.token"}],
    }
    assert options["index"] == "1"
    with pytest.raises(WhatsAppError, match="no template"):
        payload(TO, WhatsAppMessage(text="x"), session=False, language="en")


def test_sending_returns_the_message_id() -> None:
    s, seen = sender(sent("wamid.XYZ"))
    assert s.send(TO, ALERT, session=True) == "wamid.XYZ"
    request = seen[0]
    assert (request.method, request.url.path) == ("POST", "/v25.0/1234/messages")
    assert request.headers["authorization"] == "Bearer test-token"
    assert json.loads(request.read())["type"] == "interactive"
    assert s.provider == "whatsapp:cloud"
    s.close()


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, 131047, False),  # the window is closed: a template is needed
        (400, 131026, False),
        (400, 132001, False),
        (401, 190, False),
        (429, 130429, True),
        (400, 131056, True),
        (400, 131000, True),
        (500, 1, True),
    ],
)
def test_errors_say_whether_to_retry(status: int, code: int, retryable: bool) -> None:
    s, _ = sender(error(status, code))
    with pytest.raises(WhatsAppError) as caught:
        s.send(TO, ALERT, session=True)
    assert (caught.value.retryable, caught.value.code) == (retryable, code)
    assert caught.value.window_closed is (code == 131047)


def test_network_failures_and_odd_answers() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    s, _ = sender(down)
    with pytest.raises(WhatsAppError) as caught:
        s.send(TO, ALERT, session=True)
    assert caught.value.retryable
    s, _ = sender(lambda r: httpx2.Response(200, json={"no": "messages"}))
    with pytest.raises(WhatsAppError, match="unexpected"):
        s.send(TO, ALERT, session=True)
    s, _ = sender(lambda r: httpx2.Response(502, text="<html>bad gateway"))
    with pytest.raises(WhatsAppError) as caught:
        s.send(TO, ALERT, session=True)
    assert caught.value.retryable


def media_api(audio: bytes, *, size: int | None = None, url: str = "https://lookaside/m1"):
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/v25.0/MEDIA1":
            assert request.url.params["phone_number_id"] == "1234"
            return httpx2.Response(
                200,
                json={
                    "messaging_product": "whatsapp",
                    "url": url,
                    "mime_type": "audio/ogg; codecs=opus",
                    "sha256": "abc",
                    "file_size": len(audio) if size is None else size,
                    "id": "MEDIA1",
                },
            )
        assert request.headers["authorization"] == "Bearer test-token"  # the token is needed
        return httpx2.Response(200, content=audio)

    return handle


def test_a_voice_note_is_downloaded_within_its_size_cap() -> None:
    s, seen = sender(media_api(b"OggS voice"))
    assert s.download("MEDIA1", max_bytes=100) == b"OggS voice"
    assert [r.url.host for r in seen] == ["graph.facebook.com", "lookaside"]
    s, _ = sender(media_api(b"OggS", size=10_000))
    with pytest.raises(WhatsAppError, match="too large"):
        s.download("MEDIA1", max_bytes=100)  # stated too large: not fetched
    s, _ = sender(media_api(b"x" * 500, size=1))
    with pytest.raises(WhatsAppError, match="too large"):
        s.download("MEDIA1", max_bytes=100)  # understated: stopped while reading
    s, _ = sender(media_api(b"x", url="http://plain/m1"))
    with pytest.raises(WhatsAppError, match="no media URL"):
        s.download("MEDIA1", max_bytes=100)


def test_the_fake_validates_like_the_real_one() -> None:
    fake = FakeWhatsApp(media={"m": b"OggS"})
    assert fake.send(TO, ALERT, session=False) == "wamid.fake1"
    assert fake.sent == [(TO, ALERT, False)]
    with pytest.raises(WhatsAppError, match="no template"):
        fake.send(TO, WhatsAppMessage(text="x"), session=False)
    assert fake.download("m", max_bytes=10) == b"OggS"
    with pytest.raises(WhatsAppError):
        fake.download("other", max_bytes=10)
    with pytest.raises(WhatsAppError, match="too large"):
        fake.download("m", max_bytes=2)
    fake.failures.append(WhatsAppError("down", retryable=True))
    with pytest.raises(WhatsAppError, match="down"):
        fake.send(TO, ALERT, session=True)


def test_without_credentials_there_is_no_sender() -> None:
    assert sender_from_settings(Settings(_env_file=None)) is None  # type: ignore[call-arg]
    configured = Settings(
        _env_file=None,  # type: ignore[call-arg]
        whatsapp_access_token=SecretStr("t"),
        whatsapp_phone_number_id="99",
    )
    built = sender_from_settings(configured)
    assert built is not None
    assert (built.phone_number_id, built.api_version) == ("99", "v25.0")
