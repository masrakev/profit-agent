"""Health (the process answers) and readiness (it can serve: the database answers)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import EngineDep
from app.api.problems import problem

router = APIRouter(prefix="/api/v1", tags=["health"])


class Health(BaseModel):
    status: str
    version: str = "v1"


@router.get("/health", response_model=Health)
def health() -> Health:
    """The process is up (no dependency is checked)."""
    return Health(status="ok")


class Ready(BaseModel):
    status: str
    database: str
    schema_revision: str | None = None


@router.get(
    "/ready",
    response_model=Ready,
    responses={503: {"description": "Not ready: the database does not answer"}},
)
def ready(request: Request, engine: EngineDep) -> Ready | JSONResponse:
    """Ready to serve: the database answers, and its schema revision."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return problem(request, 503, code="not_ready", detail="the database does not answer")
    revision = None
    try:  # informative only: the application role may not read the migration table
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError:
        revision = None
    return Ready(status="ready", database="ok", schema_revision=revision)
