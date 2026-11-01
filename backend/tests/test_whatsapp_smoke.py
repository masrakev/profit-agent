"""The live WhatsApp smoke script (scripts/whatsapp_smoke.py), on the fake adapter: nothing is
sent without every credential; a closed 24-hour window is told apart from a broken integration."""

from typing import Any

import pytest
from pydantic import SecretStr

from app.channels.whatsapp import FakeWhatsApp, WhatsAppError, payload
from app.config import Settings
from scripts import whatsapp_smoke

CONFIGURED: dict[str, Any] = {
    "whatsapp_access_token": SecretStr("t"),
    "whatsapp_phone_number_id": "1",
    "whatsapp_app_secret": SecretStr("s"),
    "whatsapp_verify_token": SecretStr("v"),
    "whatsapp_test_recipient": "+15550001111",
}


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_nothing_is_sent_without_every_credential(capsys: pytest.CaptureFixture[str]) -> None:
    partial = {k: v for k, v in CONFIGURED.items() if k != "whatsapp_app_secret"}
    assert whatsapp_smoke.main([], settings(**partial)) == 1
    assert "set WHATSAPP_APP_SECRET in .env" in capsys.readouterr().out


def test_the_three_checks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeWhatsApp()
    monkeypatch.setattr(whatsapp_smoke, "sender_from_settings", lambda s: fake)
    assert whatsapp_smoke.main([], settings(**CONFIGURED)) == 0
    sent = [(to, m.template, session) for to, m, session in fake.sent]
    assert sent == [
        ("15550001111", "hello_world", False),
        ("15550001111", None, True),
        ("15550001111", None, True),
    ]
    assert (
        "components" not in payload("1", fake.sent[0][1], session=False, language="en")["template"]
    )  # hello_world takes no parameter
    fake.failures += [WhatsAppError("re-engagement", retryable=False, code=131047)]
    assert whatsapp_smoke.main([], settings(**CONFIGURED)) == 1
    assert "the 24-hour window is closed" in capsys.readouterr().out
