"""Decisions, approvals, rollback, journal, policy preview and kill switches (Task 4 B5).

The tenant is the `{store_id}` path parameter; every query runs under its row-level security.
Approval over the API is the web channel; email approval links are signed tokens, single use.
Opening a link (`GET /approval-links/{token}`) only shows what it would decide: mail scanners
open links, so a GET never decides. The confirmation page posts it (`POST`), which decides;
above the spending caps the link only returns a confirmation (approving then takes the web
channel). The global kill switch needs the admin token (`X-Admin-Token`).
"""

import hmac
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import PrincipalDep, StoreDep
from app.api.deps import EngineDep, OwnerEngineDep, SettingsDep
from app.api.pagination import Cursor, Limit, Page, paginate
from app.config import Settings
from app.db import tenant_transaction
from app.decisions.journal import JournalEntry, journal
from app.decisions.store import (
    Channel,
    DecisionError,
    DecisionView,
    LinkClaims,
    Verdict,
    consume_link,
    create_link,
    decide,
    get,
    link_available,
    list_decisions,
    read_link,
)
from app.executor.worker import request_rollback
from app.policies.engine import (
    ActionRequest,
    PolicyResult,
    evaluate,
    exceeds_caps,
    set_global_switch,
    set_store_switch,
)
from app.policies.trust import TrustEntry, trust_ledger

router = APIRouter(prefix="/api/v1")
STATUS = {
    "already_decided": 409,
    "expired": 409,
    "superseded": 409,
    "not_executable": 422,
    "unknown_option": 404,
    "invalid_link": 403,
    "expired_link": 410,
    "used_link": 409,
}


def _error(exc: DecisionError) -> HTTPException:
    return HTTPException(
        status_code=STATUS.get(exc.code, 400), detail={"code": exc.code, "message": str(exc)}
    )


class Approve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=300)


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=300)
    verdict: Verdict = Verdict.APPROVED


class LinkResponse(BaseModel):
    token: str


class LinkResult(BaseModel):
    decided: bool  # whether this request decided (a GET never does)
    confirmation_required: bool  # above the caps: confirm in the app instead
    option_id: str
    verdict: Verdict
    decision: DecisionView
    reason: str | None = None


class Preview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["pause_campaign", "resume_campaign", "change_budget"]
    campaign_id: UUID
    change: Decimal | None = None


class Switch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    reason: str | None = Field(default=None, max_length=500)


class RollbackResponse(BaseModel):
    action_id: UUID


def _found(fn: Any) -> Any:
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DecisionError as exc:
        raise _error(exc) from exc


@router.get("/stores/{store_id}/decisions", response_model=Page[DecisionView], tags=["decisions"])
def get_decisions(
    store_id: StoreDep, engine: EngineDep, limit: Limit = 50, cursor: Cursor = None
) -> Page[DecisionView]:
    """The store's decisions, newest first."""
    with tenant_transaction(engine, store_id) as conn:
        found = list_decisions(conn, store_id)
    return paginate(
        found,
        key=lambda d: (d.created_at.isoformat(), str(d.decision_id)),
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/stores/{store_id}/decisions/{decision_id}", response_model=DecisionView, tags=["decisions"]
)
def get_decision(store_id: StoreDep, decision_id: UUID, engine: EngineDep) -> DecisionView:
    with tenant_transaction(engine, store_id) as conn:
        result: DecisionView = _found(lambda: get(conn, store_id, decision_id))
        return result


def _decide(
    engine: Any,
    settings: Any,
    store_id: StoreDep,
    decision_id: UUID,
    option: str | None,
    verdict: Verdict,
    actor: str,
) -> DecisionView:
    with tenant_transaction(engine, store_id) as conn:
        result: DecisionView = _found(
            lambda: decide(
                conn,
                store_id,
                decision_id,
                option,
                verdict,
                channel=Channel.API,
                actor=actor,
                meta_links=settings.meta_campaign_links,
            )
        )
        return result


@router.post(
    "/stores/{store_id}/decisions/{decision_id}/approve",
    response_model=DecisionView,
    tags=["decisions"],
)
def post_approve(
    store_id: StoreDep,
    decision_id: UUID,
    body: Approve,
    engine: EngineDep,
    settings: SettingsDep,
    principal: PrincipalDep,
) -> DecisionView:
    """Approve one option (web channel): its actions are queued in the same transaction."""
    return _decide(
        engine, settings, store_id, decision_id, body.option_id, Verdict.APPROVED, principal.label
    )


@router.post(
    "/stores/{store_id}/decisions/{decision_id}/reject",
    response_model=DecisionView,
    tags=["decisions"],
)
def post_reject(
    store_id: StoreDep,
    decision_id: UUID,
    engine: EngineDep,
    settings: SettingsDep,
    principal: PrincipalDep,
) -> DecisionView:
    return _decide(engine, settings, store_id, decision_id, None, Verdict.REJECTED, principal.label)


def _secret(settings: Any) -> str:
    if settings.approval_link_secret is None:
        raise HTTPException(status_code=503, detail="email approval links are not configured")
    return str(settings.approval_link_secret.get_secret_value())


@router.post(
    "/stores/{store_id}/decisions/{decision_id}/links",
    response_model=LinkResponse,
    tags=["decisions"],
)
def post_link(
    store_id: StoreDep,
    decision_id: UUID,
    body: LinkRequest,
    engine: EngineDep,
    settings: SettingsDep,
) -> LinkResponse:
    """A signed, single-use link for the email channel (what the approval email carries)."""
    secret = _secret(settings)
    with tenant_transaction(engine, store_id) as conn:
        token: str = _found(
            lambda: create_link(
                conn, store_id, decision_id, body.option_id, body.verdict, secret=secret
            )
        )
    return LinkResponse(token=token)


ABOVE_CAPS = "the option goes beyond the spending caps: confirm in the app"


def _claims(token: str, settings: Settings) -> LinkClaims:
    try:
        return read_link(token, secret=_secret(settings))
    except DecisionError as exc:
        raise _error(exc) from exc


@router.get("/approval-links/{token}", response_model=LinkResult, tags=["decisions"])
def preview_link(token: str, engine: EngineDep, settings: SettingsDep) -> LinkResult:
    """What an email approval link would decide, without deciding (the link stays usable)."""
    claims = _claims(token, settings)
    with tenant_transaction(engine, claims.store_id) as conn:
        decision: DecisionView = _found(lambda: get(conn, claims.store_id, claims.decision_id))
        option = _found(lambda: decision.option(claims.option_id))
        if not link_available(conn, claims):
            raise _error(DecisionError("used_link", "the link was already used or has expired"))
        above = claims.verdict is Verdict.APPROVED and exceeds_caps(
            conn, claims.store_id, option.actions
        )
    return LinkResult(
        decided=False,
        confirmation_required=above,
        option_id=claims.option_id,
        verdict=claims.verdict,
        decision=decision,
        reason=ABOVE_CAPS if above else None,
    )


@router.post("/approval-links/{token}", response_model=LinkResult, tags=["decisions"])
def confirm_link(token: str, engine: EngineDep, settings: SettingsDep) -> LinkResult:
    """Confirm an email approval link: decide, once; above the caps, only a confirmation."""
    claims = _claims(token, settings)
    with tenant_transaction(engine, claims.store_id) as conn:
        decision: DecisionView = _found(lambda: get(conn, claims.store_id, claims.decision_id))
        option = _found(lambda: decision.option(claims.option_id))
        if claims.verdict is Verdict.APPROVED and exceeds_caps(
            conn, claims.store_id, option.actions
        ):
            return LinkResult(
                decided=False,
                confirmation_required=True,
                option_id=claims.option_id,
                verdict=claims.verdict,
                decision=decision,
                reason=ABOVE_CAPS,
            )
        _found(lambda: consume_link(conn, claims))
        decided: DecisionView = _found(
            lambda: decide(
                conn,
                claims.store_id,
                claims.decision_id,
                claims.option_id if claims.verdict is Verdict.APPROVED else None,
                claims.verdict,
                channel=Channel.EMAIL,
                actor="owner:email",
                meta_links=settings.meta_campaign_links,
            )
        )
    return LinkResult(
        decided=True,
        confirmation_required=False,
        option_id=claims.option_id,
        verdict=claims.verdict,
        decision=decided,
    )


@router.post(
    "/stores/{store_id}/actions/{action_id}/rollback",
    response_model=RollbackResponse,
    tags=["decisions"],
)
def post_rollback(
    store_id: StoreDep, action_id: UUID, engine: EngineDep, principal: PrincipalDep
) -> RollbackResponse:
    """Queue the inverse of an executed action (pause <-> resume, budget restored)."""
    with tenant_transaction(engine, store_id) as conn:
        try:
            new = request_rollback(conn, store_id, action_id, actor=principal.label)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RollbackResponse(action_id=new)


@router.get("/stores/{store_id}/journal", response_model=Page[JournalEntry], tags=["journal"])
def get_journal(
    store_id: StoreDep, engine: EngineDep, limit: Limit = 50, cursor: Cursor = None
) -> Page[JournalEntry]:
    """Incidents, decisions, approvals, actions and outcomes, newest first."""
    with tenant_transaction(engine, store_id) as conn:
        entries = journal(conn, store_id, limit=10_000)
    return paginate(
        entries, key=lambda e: (e.at.isoformat(), e.kind, e.id), limit=limit, cursor=cursor
    )


@router.post("/stores/{store_id}/policy/preview", response_model=PolicyResult, tags=["policy"])
def post_preview(store_id: StoreDep, body: Preview, engine: EngineDep) -> PolicyResult:
    """What the policy engine would decide for an approved action now (audited as a preview)."""
    from datetime import UTC, datetime

    with tenant_transaction(engine, store_id) as conn:
        return evaluate(
            conn,
            ActionRequest(
                store_id=store_id,
                kind=body.kind,
                campaign_id=body.campaign_id,
                approved=True,
                change=body.change,
            ),
            now=datetime.now(UTC),
            actor="api:preview",
        )


@router.get("/stores/{store_id}/trust", response_model=list[TrustEntry], tags=["policy"])
def get_trust(store_id: StoreDep, engine: EngineDep) -> list[TrustEntry]:
    with tenant_transaction(engine, store_id) as conn:
        return trust_ledger(conn, store_id)


@router.put("/stores/{store_id}/kill-switch", tags=["policy"])
def put_store_switch(
    store_id: StoreDep, body: Switch, engine: EngineDep, principal: PrincipalDep
) -> dict[str, bool]:
    with tenant_transaction(engine, store_id) as conn:
        set_store_switch(conn, store_id, body.enabled, actor=principal.label, reason=body.reason)
    return {"enabled": body.enabled}


@router.put("/admin/kill-switch", tags=["policy"])
def put_global_switch(
    body: Switch,
    owner: OwnerEngineDep,
    settings: SettingsDep,
    token: Annotated[str, Header(alias="X-Admin-Token")] = "",
) -> dict[str, bool]:
    """Stop (or allow) every action of every store. Admin only."""
    expected = settings.admin_token.get_secret_value() if settings.admin_token else ""
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="admin token required")
    with owner.begin() as conn:
        set_global_switch(conn, body.enabled, actor="admin", reason=body.reason)
    return {"enabled": body.enabled}
