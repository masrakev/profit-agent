"""WhatsApp (ADR 0027): the owner's number and its verification.

The number is set in the store's settings (`whatsapp_number`). `POST .../whatsapp/verification`
sends a six-digit code to it on WhatsApp (an approved authentication template, since the number
has not written yet); the owner types it on the web, `POST .../whatsapp/verification/confirm`.
Only a verified number interacts with the store.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import PrincipalDep, StoreDep
from app.api.deps import EngineDep, SettingsDep
from app.channels.whatsapp import WhatsAppError, WhatsAppMessage, WhatsAppSender
from app.channels.whatsapp import sender_from_settings as whatsapp_from_settings
from app.config import Settings, get_settings
from app.db import tenant_transaction
from app.whatsapp import numbers
from app.whatsapp.numbers import NumberError, NumberState

router = APIRouter(prefix="/api/v1/stores/{store_id}/whatsapp", tags=["whatsapp"])
CODE_TEMPLATE = "verification_code"


def get_whatsapp_sender() -> WhatsAppSender | None:
    return whatsapp_from_settings(get_settings())


WhatsAppDep = Annotated[WhatsAppSender | None, Depends(get_whatsapp_sender)]


class WhatsAppNumber(BaseModel):
    number: str | None  # E.164
    verified: bool
    verified_at: datetime | None = None
    code_expires_at: datetime | None = None  # a code was sent and is still valid until then
    window_open: bool = False  # the owner wrote in the last 24 hours: session messages work


class CodeSent(BaseModel):
    sent_to_ending: str  # the number's last four digits
    expires_at: datetime


class Code(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[0-9]{6}$")


def _out(found: NumberState | None, now: datetime) -> WhatsAppNumber:
    if found is None:
        return WhatsAppNumber(number=None, verified=False)
    pending_code = found.code_expires_at if not found.verified else None
    return WhatsAppNumber(
        number=found.e164,
        verified=found.verified,
        verified_at=found.verified_at,
        code_expires_at=pending_code if pending_code and pending_code > now else None,
        window_open=found.window_open(now),
    )


def _secret(settings: Settings) -> str:
    secret = settings.approval_link_secret
    if secret is None or not secret.get_secret_value():
        raise HTTPException(
            status_code=503,
            detail={"code": "whatsapp_unavailable", "message": "the signing secret is not set"},
        )
    return secret.get_secret_value()


def _error(exc: NumberError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def code_message(code: str) -> WhatsAppMessage:
    """The code, as a session text and as the authentication template (with its copy button)."""
    return WhatsAppMessage(
        text=f"Your Profit Agent verification code is {code}. It works for ten minutes. If you "
        "did not ask for it, ignore this message.",
        template=CODE_TEMPLATE,
        params=(code,),
        copy_code=code,
    )


@router.get("", response_model=WhatsAppNumber)
def get_number(store_id: StoreDep, engine: EngineDep) -> WhatsAppNumber:
    """The store's WhatsApp number and whether it is verified."""
    with tenant_transaction(engine, store_id) as conn:
        return _out(numbers.state(conn, store_id), datetime.now(UTC))


@router.post("/verification", status_code=202, response_model=CodeSent)
def post_verification(
    store_id: StoreDep, engine: EngineDep, settings: SettingsDep, sender: WhatsAppDep
) -> CodeSent:
    """Send a verification code to the settings' number on WhatsApp (three an hour at most)."""
    if sender is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "whatsapp_unavailable", "message": "WhatsApp is not configured"},
        )
    secret, now = _secret(settings), datetime.now(UTC)
    with tenant_transaction(engine, store_id) as conn:
        try:
            phone, code = numbers.start(conn, store_id, secret=secret, now=now)
        except NumberError as exc:
            raise _error(exc) from exc
        found = numbers.state(conn, store_id)
    assert found is not None
    assert found.code_expires_at is not None
    try:
        sender.send(phone, code_message(code), session=found.window_open(now))
    except WhatsAppError as exc:
        raise HTTPException(
            status_code=503 if exc.retryable else 502,
            detail={"code": "whatsapp_failed", "message": "the code could not be sent: retry"},
        ) from exc
    return CodeSent(sent_to_ending=phone[-4:], expires_at=found.code_expires_at)


@router.post("/verification/confirm", response_model=WhatsAppNumber)
def post_confirm(
    store_id: StoreDep,
    body: Code,
    engine: EngineDep,
    settings: SettingsDep,
    principal: PrincipalDep,
) -> WhatsAppNumber:
    """Confirm the number with the code it received: from now on it can talk to the store."""
    secret, now = _secret(settings), datetime.now(UTC)
    with tenant_transaction(engine, store_id) as conn:
        try:
            found = numbers.confirm(
                conn, store_id, body.code, secret=secret, actor=principal.label, now=now
            )
        except NumberError as exc:
            raise _error(exc) from exc
    if isinstance(found, NumberError):  # a wrong code: the attempt is counted, then refused
        raise _error(found)
    return _out(found, now)
