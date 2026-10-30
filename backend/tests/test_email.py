"""The email channel: MIME structure, the SMTP adapter and its error classes (no network)."""

import smtplib
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from app.channels.email import (
    EmailError,
    EmailMessage,
    RecordingSender,
    SmtpSender,
    mime,
    sender_from_settings,
)
from app.config import get_settings

MESSAGE = EmailMessage(
    to="owner@example.com", subject="Daily brief", text="Plain text.", html="<p>HTML</p>"
)


class FakeSmtp:
    instances: ClassVar[list["FakeSmtp"]] = []
    fail: ClassVar[Exception | None] = None

    def __init__(self, host: str, port: int, *, timeout: float) -> None:
        self.args = (host, port, timeout)
        self.calls: list[str] = []
        self.sent: list[Any] = []
        FakeSmtp.instances.append(self)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def starttls(self, *, context: Any) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, message: Any) -> None:
        if FakeSmtp.fail is not None:
            raise FakeSmtp.fail
        self.sent.append(message)


@pytest.fixture(autouse=True)
def reset() -> None:
    FakeSmtp.instances, FakeSmtp.fail = [], None


def test_the_message_has_a_text_and_an_html_part() -> None:
    out = mime(MESSAGE, sender="Profit Agent <b@example.com>", message_id="<id@example.com>")
    assert out.get_content_type() == "multipart/alternative"
    parts = list(out.iter_parts())
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]
    assert parts[0].get_content().strip() == "Plain text."
    assert (out["To"], out["Subject"], out["Message-ID"]) == (
        "owner@example.com",
        "Daily brief",
        "<id@example.com>",
    )
    assert out["Auto-Submitted"] == "auto-generated"


def test_mailpit_style_delivery() -> None:
    sender = SmtpSender("localhost", 1025, "Profit Agent <b@profit.test>", connect=FakeSmtp)
    message_id = sender.send(MESSAGE)
    [smtp] = FakeSmtp.instances
    assert smtp.args == ("localhost", 1025, 10.0)
    assert smtp.calls == ["quit"]  # no TLS and no login against Mailpit
    assert smtp.sent[0]["Message-ID"] == message_id
    assert message_id.endswith("@profit.test>")
    assert sender.provider == "smtp:localhost"


def test_a_provider_relay_uses_starttls_and_credentials() -> None:
    sender = SmtpSender(
        "smtp.provider.example",
        587,
        "b@example.com",
        security="starttls",
        username="apikey",
        password="secret",
        connect=FakeSmtp,
    )
    sender.send(MESSAGE)
    assert FakeSmtp.instances[0].calls == ["starttls", "login:apikey", "quit"]


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (smtplib.SMTPRecipientsRefused({"owner@example.com": (550, b"no such user")}), False),
        (smtplib.SMTPAuthenticationError(535, b"bad credentials"), False),
        (smtplib.SMTPDataError(451, b"try again later"), True),
        (smtplib.SMTPDataError(554, b"rejected"), False),
        (smtplib.SMTPServerDisconnected("lost"), True),
        (TimeoutError("timed out"), True),
        (ConnectionRefusedError("refused"), True),
    ],
)
def test_errors_say_whether_to_retry(error: Exception, retryable: bool) -> None:
    FakeSmtp.fail = error
    sender = SmtpSender("localhost", 1025, "b@example.com", connect=FakeSmtp)
    with pytest.raises(EmailError) as caught:
        sender.send(MESSAGE)
    assert caught.value.retryable is retryable


def test_settings_configure_the_sender() -> None:
    settings = get_settings().model_copy(
        update={
            "email_smtp_host": "smtp.example.com",
            "email_smtp_port": 465,
            "email_smtp_security": "ssl",
            "email_smtp_username": "user",
            "email_smtp_password": SecretStr("pw"),
        }
    )
    sender = sender_from_settings(settings)
    assert (sender.host, sender.port, sender.security, sender.username, sender.password) == (
        "smtp.example.com",
        465,
        "ssl",
        "user",
        "pw",
    )
    assert sender_from_settings(get_settings()).port == 1025  # Mailpit by default


def test_the_recording_sender() -> None:
    sender = RecordingSender(failures=[EmailError("down", retryable=True)])
    with pytest.raises(EmailError):
        sender.send(MESSAGE)
    assert sender.send(MESSAGE).endswith("@recording>")
    assert sender.sent == [MESSAGE]
    assert sender.provider == "recording"
