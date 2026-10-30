"""Errors as RFC 9457 problem details (`application/problem+json`), the same shape everywhere.

    {"type": "urn:profit-agent:problem:not_found", "title": "Not Found", "status": 404,
     "detail": "no such store", "code": "not_found", "request_id": "..."}

`code` is stable and machine-readable (the list is in docs/api/README.md); `detail` is for
people. Validation errors list the offending fields without echoing their values. An
unexpected error is a 500 with no detail: the request id leads to the logs.
"""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.observability import get_logger

PROBLEM_JSON = "application/problem+json"
CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    413: "too_large",
    422: "invalid_request",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
}
log = get_logger(__name__)


class FieldError(BaseModel):
    field: str
    message: str


class Problem(BaseModel):
    type: str
    title: str
    status: int
    detail: str | None = None
    code: str
    request_id: str | None = None
    errors: list[FieldError] | None = None


def request_id(request: Request) -> str | None:
    rid: str | None = getattr(request.state, "request_id", None)
    return rid


def problem(
    request: Request,
    status: int,
    *,
    code: str | None = None,
    detail: str | None = None,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    code = code or CODES.get(status, "error")
    body = Problem(
        type=f"urn:profit-agent:problem:{code}",
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        code=code,
        request_id=request_id(request),
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


def _from_detail(detail: Any) -> tuple[str | None, str | None]:
    if isinstance(detail, dict):
        return detail.get("code"), detail.get("message")
    return None, None if detail is None else str(detail)


async def http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    code, detail = _from_detail(exc.detail)
    return problem(
        request, exc.status_code, code=code, detail=detail, headers=getattr(exc, "headers", None)
    )


async def validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        FieldError(field=".".join(str(p) for p in e.get("loc", ())), message=str(e.get("msg")))
        for e in exc.errors()
    ]
    return problem(request, 422, detail="the request is not valid", errors=errors)


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("api.unexpected_error", request_id=request_id(request))
    return problem(request, 500, detail="unexpected error; quote the request id")


def install(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, unexpected_error)


# Documented on every route: the shape of every error response.
RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": Problem, "content": {PROBLEM_JSON: {}}, "description": phrase}
    for status, phrase in (
        (401, "Not signed in, or the token is not valid"),
        (403, "Not allowed (CSRF, a token where a session is needed)"),
        (404, "Not found, or not one of the caller's stores"),
        (422, "The request is not valid"),
        (429, "Too many requests"),
    )
}
