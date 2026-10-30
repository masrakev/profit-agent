"""FastAPI application: Ask and investigations.

    uv run uvicorn app.api.main:app --app-dir backend

Until authentication exists, investigation routes name the tenant in the `X-Store-Id` header
(incident ids are only unique within a store); every query still runs under that store's
row-level security. The engine and the model provider are dependencies, replaced in tests.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from app.agent.ask import AskResult, ask
from app.agent.investigator import Investigation, investigate, load_investigation
from app.api.decisions import router as decisions_router
from app.api.deps import EngineDep, ProviderDep, StoreHeader, get_engine, get_provider
from app.db import tenant_transaction

API_VERSION = "v1"


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)


router = APIRouter(prefix=f"/api/{API_VERSION}")


@router.post("/stores/{store_id}/ask", response_model=AskResult, tags=["ask"])
def post_ask(
    store_id: UUID, body: AskRequest, engine: EngineDep, provider: ProviderDep
) -> AskResult:
    """Answer a question about the store with the answer contract (SPEC section 8)."""
    try:
        return ask(engine, store_id, body.question, provider)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/incidents/{incident_id}/investigate", response_model=Investigation, tags=["investigations"]
)
def post_investigate(
    incident_id: Annotated[str, Path(pattern=r"^inc-[0-9a-f]{12}$")],
    store_id: StoreHeader,
    engine: EngineDep,
    provider: ProviderDep,
    refresh: bool = False,
) -> Investigation:
    """Investigate an incident; an identical investigation is served from the cache unless
    `refresh` is set."""
    try:
        return investigate(engine, store_id, incident_id, provider, use_cache=not refresh)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/investigations/{investigation_id}", response_model=Investigation, tags=["investigations"]
)
def get_investigation(
    investigation_id: UUID, store_id: StoreHeader, engine: EngineDep
) -> Investigation:
    with tenant_transaction(engine, store_id) as conn:
        found = load_investigation(conn, store_id, investigation_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no investigation {investigation_id}")
    return found


def create_app() -> FastAPI:
    app = FastAPI(
        title="Verifiable Profit Agent API",
        version=API_VERSION,
        description="Every number is a fact with an id; model text cites facts, never numbers.",
    )
    app.include_router(router)
    app.include_router(decisions_router)
    return app


app = create_app()
__all__ = ["app", "create_app", "get_engine", "get_provider"]
