"""Privacy routes (ADR 0021): export a store, delete it, and its platform connections."""

import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import PrincipalDep, StoreDep
from app.api.deps import EngineDep, SettingsDep
from app.config import repo_path
from app.db import tenant_transaction
from app.domain.audit import append_audit
from app.privacy.connections import (
    ConnectionView,
    delete_connection,
    list_connections,
    master_key,
    save_connection,
)
from app.privacy.crypto import CryptoError
from app.privacy.deletion import delete_store
from app.privacy.export import write_export

router = APIRouter(prefix="/api/v1/stores/{store_id}", tags=["privacy"])
Provider = Annotated[Literal["meta", "shopify"], Path()]
CHUNK = 64 * 1024


def _now() -> datetime:
    return datetime.now(UTC)


@router.get(
    "/export",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {}}, "description": "the store's data"}},
)
def get_export(store_id: StoreDep, engine: EngineDep, principal: PrincipalDep) -> StreamingResponse:
    """Everything the store has, as a zip: one JSON Lines file per table, owners and API
    tokens as metadata, a manifest; no secret. Audited."""
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)  # noqa: SIM115
    write_export(engine, store_id, spool, actor=principal.label, now=_now())
    spool.seek(0)

    def chunks() -> Iterator[bytes]:
        try:
            while block := spool.read(CHUNK):
                yield block
        finally:
            spool.close()

    name = f"store-{store_id}-{_now():%Y%m%d}.zip"
    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_store_id: UUID = Field(description="the store's id again, to confirm")


class Deleted(BaseModel):
    store_id: UUID
    rows: dict[str, int]
    cassettes: int


@router.delete("", response_model=Deleted)
def delete_store_route(
    store_id: StoreDep,
    body: DeleteRequest,
    engine: EngineDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> Deleted:
    """Delete the store and all its data, for good (signed-in owners only, the store id
    confirmed). The deletion itself is recorded, outside the store's data."""
    if principal.kind != "session":
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "only a signed-in owner can delete a store"},
        )
    if body.confirm_store_id != store_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_request", "message": "confirm with the store's own id"},
        )
    done = delete_store(
        engine,
        store_id,
        actor=principal.label,
        cassette_dir=repo_path(settings.llm_cassette_dir),
    )
    return Deleted(store_id=done.store_id, rows=done.rows, cassettes=done.cassettes)


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=100)
    access_token: str = Field(min_length=1, max_length=4096)


class ConnectionOut(BaseModel):
    provider: str
    account_id: str
    key_id: str
    created_at: datetime
    updated_at: datetime


def _out(view: ConnectionView) -> ConnectionOut:
    return ConnectionOut(**view.__dict__)


@router.get("/connections", response_model=list[ConnectionOut])
def get_connections(store_id: StoreDep, engine: EngineDep) -> list[ConnectionOut]:
    """The store's platform connections (never their tokens)."""
    with tenant_transaction(engine, store_id) as conn:
        return [_out(v) for v in list_connections(conn, store_id)]


@router.put("/connections/{provider}", response_model=ConnectionOut)
def put_connection(
    store_id: StoreDep,
    provider: Provider,
    body: ConnectionIn,
    engine: EngineDep,
    settings: SettingsDep,
    principal: PrincipalDep,
) -> ConnectionOut:
    """Connect (or reconnect) a platform: the access token is encrypted before it is stored."""
    try:
        master = master_key(settings)
    except CryptoError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "unavailable", "message": str(exc)}
        ) from exc
    with tenant_transaction(engine, store_id) as conn:
        view = save_connection(
            conn, store_id, provider, body.account_id, body.access_token, master, _now()
        )
        append_audit(
            conn,
            store_id,
            actor=principal.label,
            action="connection.saved",
            payload={"provider": provider, "account_id": body.account_id, "key_id": view.key_id},
        )
    return _out(view)


@router.delete("/connections/{provider}", status_code=204)
def delete_connection_route(
    store_id: StoreDep, provider: Provider, engine: EngineDep, principal: PrincipalDep
) -> None:
    with tenant_transaction(engine, store_id) as conn:
        if not delete_connection(conn, store_id, provider):
            raise HTTPException(
                status_code=404, detail={"code": "not_found", "message": "no such connection"}
            )
        append_audit(
            conn,
            store_id,
            actor=principal.label,
            action="connection.deleted",
            payload={"provider": provider},
        )
