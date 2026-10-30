"""Transactional email behind one interface (ADR 0019).

`EmailSender.send` takes a message with a text and an HTML part and returns the provider's
message id. `SmtpSender` speaks SMTP: Mailpit locally (docker compose, no TLS, no login), or a
real provider's relay with STARTTLS or implicit TLS and credentials from the environment. Errors
say whether retrying can help (a lost connection, a timeout, a 4xx reply) or not (a refused
recipient, bad credentials, a 5xx reply); the delivery worker retries the former with backoff.
"""

import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage as MimeMessage
from email.utils import format_datetime, make_msgid, parseaddr
from typing import Literal, Protocol
from uuid import uuid4

from app.config import Settings

Security = Literal["none", "starttls", "ssl"]


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


class EmailError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class EmailSender(Protocol):
    @property
    def provider(self) -> str: ...

    def send(self, message: EmailMessage) -> str: ...


def mime(message: EmailMessage, *, sender: str, message_id: str) -> MimeMessage:
    """The MIME message: multipart/alternative with the text part first, then the HTML."""
    out = MimeMessage()
    out["From"] = sender
    out["To"] = message.to
    out["Subject"] = message.subject
    out["Date"] = format_datetime(datetime.now(UTC))
    out["Message-ID"] = message_id
    out["Auto-Submitted"] = "auto-generated"  # RFC 3834: no auto-replies to it
    out.set_content(message.text)
    out.add_alternative(message.html, subtype="html")
    return out


@dataclass
class SmtpSender:
    host: str
    port: int
    from_address: str
    security: Security = "none"
    username: str | None = None
    password: str | None = None
    timeout: float = 10.0
    connect: Callable[..., smtplib.SMTP] | None = None  # tests: a fake SMTP class

    @property
    def provider(self) -> str:
        return f"smtp:{self.host}"

    def _open(self) -> smtplib.SMTP:
        if self.connect is not None:
            return self.connect(self.host, self.port, timeout=self.timeout)
        if self.security == "ssl":
            return smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=ssl.create_default_context()
            )
        return smtplib.SMTP(self.host, self.port, timeout=self.timeout)

    def send(self, message: EmailMessage) -> str:
        domain = parseaddr(self.from_address)[1].rpartition("@")[2] or "localhost"
        message_id = make_msgid(domain=domain)
        try:
            with self._open() as smtp:
                if self.security == "starttls":
                    smtp.starttls(context=ssl.create_default_context())
                if self.username:
                    smtp.login(self.username, self.password or "")
                smtp.send_message(mime(message, sender=self.from_address, message_id=message_id))
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailError(f"recipient refused: {exc.recipients}", retryable=False) from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailError("the SMTP credentials were refused", retryable=False) from exc
        except smtplib.SMTPResponseException as exc:
            raise EmailError(
                f"SMTP {exc.smtp_code}: {exc.smtp_error!r}"[:300],
                retryable=400 <= exc.smtp_code < 500,
            ) from exc
        except (smtplib.SMTPException, OSError) as exc:  # lost connection, timeout, no route
            raise EmailError(f"{type(exc).__name__}: {exc}"[:300], retryable=True) from exc
        return message_id


@dataclass
class RecordingSender:
    """Keeps messages in memory (tests, dry runs)."""

    sent: list[EmailMessage] = field(default_factory=list)
    failures: list[EmailError] = field(default_factory=list)  # raised first, in order

    @property
    def provider(self) -> str:
        return "recording"

    def send(self, message: EmailMessage) -> str:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(message)
        return f"<{uuid4()}@recording>"


def sender_from_settings(settings: Settings) -> SmtpSender:
    return SmtpSender(
        host=settings.email_smtp_host,
        port=settings.email_smtp_port,
        from_address=settings.email_from,
        security=settings.email_smtp_security,
        username=settings.email_smtp_username,
        password=(
            settings.email_smtp_password.get_secret_value()
            if settings.email_smtp_password
            else None
        ),
        timeout=settings.email_smtp_timeout_s,
    )
