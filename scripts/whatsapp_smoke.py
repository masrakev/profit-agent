"""Live smoke test of the WhatsApp Cloud API, once credentials exist (ADR 0027).

    uv run python scripts/whatsapp_smoke.py            # make smoke-whatsapp

Needs, in `.env`: WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_APP_SECRET,
WHATSAPP_VERIFY_TOKEN and WHATSAPP_TEST_RECIPIENT (the test number, digits with the country code,
registered as a recipient of the app's test phone number). Three checks:

1. the `hello_world` template every WhatsApp Business account starts with (business-initiated,
   works outside the 24-hour window);
2. a session text and a reply-button message, which work only once the test recipient has written
   to the business number in the last 24 hours (send it any message first): a 131047 error here
   means the window is closed, not that the integration is broken;
3. the app secret and the verify token are set, as the webhook needs them (the webhook itself is
   checked through the tunnel: README, "WhatsApp setup").

Exits with status 1 and says what failed; nothing is sent when a credential is missing.
"""

import sys

from app.channels.whatsapp import (
    ReplyButton,
    WhatsAppError,
    WhatsAppMessage,
    sender_from_settings,
)
from app.config import Settings, get_settings

REQUIRED = (
    "whatsapp_access_token",
    "whatsapp_phone_number_id",
    "whatsapp_app_secret",
    "whatsapp_verify_token",
    "whatsapp_test_recipient",
)


def missing(settings: Settings) -> list[str]:
    def unset(name: str) -> bool:
        value = getattr(settings, name)
        getter = getattr(value, "get_secret_value", None)
        return not (getter() if getter is not None else value)

    return [name.upper() for name in REQUIRED if unset(name)]


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    out = sys.stdout
    absent = missing(settings)
    if absent:
        out.write(f"WhatsApp smoke skipped: set {', '.join(absent)} in .env\n")
        return 1
    sender = sender_from_settings(settings)
    assert sender is not None
    to = str(settings.whatsapp_test_recipient).removeprefix("+")
    checks = [
        ("template hello_world", WhatsAppMessage(text="", template="hello_world"), False),
        ("session text", WhatsAppMessage(text="Profit Agent smoke test: a session text."), True),
        (
            "reply buttons",
            WhatsAppMessage(
                text="Profit Agent smoke test: reply buttons (tapping them changes nothing).",
                buttons=(ReplyButton("smoke.yes", "Looks right"), ReplyButton("smoke.no", "No")),
            ),
            True,
        ),
    ]
    failed = 0
    for name, message, session in checks:
        try:
            message_id = sender.send(to, message, session=session)
        except WhatsAppError as exc:
            failed += 1
            hint = (
                " (the 24-hour window is closed: write to the business number first)"
                if exc.window_closed
                else ""
            )
            out.write(f"{name:<22} FAILED  {exc}{hint}\n")
        else:
            out.write(f"{name:<22} ok      {message_id}\n")
    out.write("webhook secrets        ok      app secret and verify token are set\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
