"""Authentication for the API (ADR 0020).

Two ways to call it:
- the web platform: an owner signs in with an email link and gets a session cookie (HTTP-only,
  Secure, SameSite=Lax); every state-changing request with that cookie must send the session's
  CSRF token in `X-CSRF-Token` and, when the browser sends an Origin, come from the platform;
- programs: `Authorization: Bearer pa_...`, a store's API token (no cookie, so no CSRF).

Every store route depends on `StoreDep`: the store must be one of the caller's, and a store
that is not is answered 404, as if it did not exist.
"""

from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import EmailSenderDep, EngineDep, SettingsDep
from app.auth.service import (
    LINK_TTL,
    SESSION_TTL,
    AuthError,
    Principal,
    create_api_token,
    list_api_tokens,
    open_session,
    request_link,
    revoke_api_token,
    revoke_session,
    same,
    session_principal,
    token_principal,
)
from app.channels.email import EmailError, EmailMessage
from app.channels.messages import render_sign_in
from app.db import tenant_transaction
from app.domain.audit import append_audit
from app.observability import get_logger

SESSION_COOKIE = "pa_session"
CSRF_COOKIE = "pa_csrf"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
EMAIL = r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$"

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["auth"])


def _now() -> datetime:
    return datetime.now(UTC)


def _unauthenticated(message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "unauthenticated", "message": message},
        headers={"WWW-Authenticate": 'Bearer realm="api", Cookie'},
    )


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def get_principal(request: Request, engine: EngineDep, settings: SettingsDep) -> Principal:
    now = _now()
    header = request.headers.get("authorization")
    if header:
        scheme, _, value = header.partition(" ")
        principal = (
            token_principal(engine, value.strip(), now) if scheme.lower() == "bearer" else None
        )
        if principal is None:
            raise _unauthenticated("the API token is not valid")
        return principal
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise _unauthenticated("sign in, or send an API token")
    principal = session_principal(engine, cookie, now)
    if principal is None:
        raise _unauthenticated("the session has expired: sign in again")
    if request.method in UNSAFE:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != _origin(settings.app_base_url):
            raise HTTPException(
                status_code=403, detail={"code": "csrf", "message": "cross-origin request"}
            )
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or principal.csrf_hash is None or not same(sent, principal.csrf_hash):
            raise HTTPException(
                status_code=403,
                detail={"code": "csrf", "message": f"send the session's {CSRF_HEADER}"},
            )
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def store_scope(store_id: UUID, principal: PrincipalDep) -> UUID:
    """The path's store, when the caller may see it."""
    if store_id not in principal.store_ids:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "no such store"}
        )
    return store_id


StoreDep = Annotated[UUID, Depends(store_scope)]


# --- sign in -------------------------------------------------------------------------------


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254, pattern=EMAIL)


class Accepted(BaseModel):
    status: str
    message: str


@router.post("/auth/magic-links", status_code=202, response_model=Accepted)
def post_magic_link(
    body: LinkRequest, engine: EngineDep, settings: SettingsDep, sender: EmailSenderDep
) -> Accepted:
    """Email a sign-in link (single use, 15 minutes). The answer is the same whether or not
    the address has an account."""
    token = request_link(engine, body.email, _now())
    if token is not None:
        link = f"{settings.app_base_url.rstrip('/')}/sign-in#token={token}"
        message = render_sign_in(link, minutes=int(LINK_TTL.total_seconds() // 60))
        try:
            sender.send(
                EmailMessage(
                    to=body.email.strip().lower(),
                    subject=message.subject,
                    text=message.text,
                    html=message.html,
                )
            )
        except EmailError as exc:
            log.warning("auth.link_not_sent", error=str(exc)[:200])
    return Accepted(
        status="accepted", message="If the address has an account, a sign-in link is on its way."
    )


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)


class SessionView(BaseModel):
    kind: str
    actor: str
    store_ids: list[UUID]
    csrf_token: str | None = None  # returned when the session opens (also in a cookie)
    expires_at: datetime | None = None


STATUS = {"invalid_link": 401, "expired_link": 410, "used_link": 409}


@router.post("/auth/sessions", status_code=201, response_model=SessionView)
def post_session(
    body: SessionRequest, response: Response, engine: EngineDep, settings: SettingsDep
) -> SessionView:
    """Exchange a sign-in link's token for a session (sets the session and CSRF cookies)."""
    try:
        session = open_session(engine, body.token, _now())
    except AuthError as exc:
        raise HTTPException(
            status_code=STATUS[exc.code], detail={"code": exc.code, "message": str(exc)}
        ) from exc
    age = int(SESSION_TTL.total_seconds())
    secure = settings.session_cookie_secure
    response.set_cookie(
        SESSION_COOKIE,
        session.token,
        max_age=age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api",
    )
    response.set_cookie(
        CSRF_COOKIE,
        session.csrf_token,
        max_age=age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    principal = session_principal(engine, session.token, _now())
    assert principal is not None
    return SessionView(
        kind="session",
        actor=principal.label,
        store_ids=sorted(principal.store_ids, key=str),
        csrf_token=session.csrf_token,
        expires_at=session.expires_at,
    )


@router.get("/auth/session", response_model=SessionView)
def get_session(principal: PrincipalDep) -> SessionView:
    """Who is calling, and the stores they can see."""
    return SessionView(
        kind=principal.kind,
        actor=principal.label,
        store_ids=sorted(principal.store_ids, key=str),
    )


@router.delete("/auth/session", status_code=204)
def delete_session(principal: PrincipalDep, engine: EngineDep) -> Response:
    """Sign out: the session is revoked and its cookies cleared."""
    if principal.session_id is not None:
        revoke_session(engine, principal.session_id, _now())
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/api")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


# --- API tokens ----------------------------------------------------------------------------


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)


class TokenOut(BaseModel):
    token_id: UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class NewToken(TokenOut):
    token: str  # shown once


@router.post("/stores/{store_id}/api-tokens", status_code=201, response_model=NewToken)
def post_api_token(
    store_id: StoreDep, body: TokenRequest, principal: PrincipalDep, engine: EngineDep
) -> NewToken:
    """A new API token for the store (signed-in owners only; the token is shown once)."""
    if principal.kind != "session":
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "an API token cannot create tokens"},
        )
    view, token = create_api_token(engine, store_id, body.name, principal.owner_id, _now())
    with tenant_transaction(engine, store_id) as conn:
        append_audit(
            conn,
            store_id,
            actor=principal.label,
            action="api_token.created",
            payload={"token_id": str(view.token_id), "name": view.name, "prefix": view.prefix},
        )
    return NewToken(**view.__dict__, token=token)


@router.get("/stores/{store_id}/api-tokens", response_model=list[TokenOut])
def get_api_tokens(store_id: StoreDep, engine: EngineDep) -> list[TokenOut]:
    return [TokenOut(**t.__dict__) for t in list_api_tokens(engine, store_id)]


@router.delete("/stores/{store_id}/api-tokens/{token_id}", status_code=204)
def delete_api_token(
    store_id: StoreDep, token_id: UUID, principal: PrincipalDep, engine: EngineDep
) -> Response:
    if not revoke_api_token(engine, store_id, token_id, _now()):
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "no such active token"}
        )
    with tenant_transaction(engine, store_id) as conn:
        append_audit(
            conn,
            store_id,
            actor=principal.label,
            action="api_token.revoked",
            payload={"token_id": str(token_id)},
        )
    return Response(status_code=204)
