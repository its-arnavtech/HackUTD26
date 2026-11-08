"""Application errors and the JSON error response shape (L2).

Raise an `AppError` subclass anywhere in the backend; the handlers that
`install_error_handlers` registers turn it into a JSON response. FastAPI's own
`HTTPException`, request validation errors and unexpected exceptions get the
same shape, so the frontend only ever sees one error format:

    {"detail": "Unknown message_id",
     "error": {"code": "not_found", "message": "Unknown message_id",
               "details": {}, "message_id": "msg_0001"}}

`detail` is kept for compatibility with FastAPI's default shape.
Never put a key, a raw message or personal data in `message` or `details`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logs import current_message_id

log = logging.getLogger("app.errors")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    message_id: str | None = None


class ErrorResponse(BaseModel):
    detail: str
    error: ErrorBody


class AppError(Exception):
    """Base class for errors that map to a clean JSON response."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class UnauthorizedError(AppError):
    """No valid session (L13). The message never says which part of a sign-in failed."""

    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    """Signed in, but this role may not do this (L13), or the CSRF check failed (code `csrf_failed`)."""

    status_code = 403
    code = "forbidden"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class NotImplementedYetError(AppError):
    """A route or feature whose issue hasn't landed yet (and its mock is switched off)."""

    status_code = 501
    code = "not_implemented"

    def __init__(self, issue: str, what: str = "this route"):
        super().__init__(f"Not implemented yet: {issue} wires {what}", details={"issue": issue})


class IntegrationError(AppError):
    """An outside service (Nemotron, Gemini, Nessie, RDAP, Hugging Face) failed or is unavailable."""

    status_code = 502
    code = "integration_error"

    def __init__(self, service: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message, details={"service": service, **(details or {})})


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    501: "not_implemented",
}


def error_response(status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    body = ErrorResponse(
        detail=message,
        error=ErrorBody(code=code, message=message, details=details or {}, message_id=current_message_id()),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    level = logging.ERROR if exc.status_code >= 500 else logging.INFO
    log.log(level, "app error: %s", exc.message, extra={"fields": {"code": exc.code, "status": exc.status_code}})
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    response = error_response(exc.status_code, _HTTP_CODES.get(exc.status_code, "http_error"), message)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Only field locations and messages: never echo the submitted values back.
    errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]
    return error_response(422, "validation_error", "Request body or parameters are invalid", {"errors": errors})


async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", extra={"fields": {"error_type": type(exc).__name__}})
    return error_response(500, "internal_error", "Something went wrong on our side")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled)
