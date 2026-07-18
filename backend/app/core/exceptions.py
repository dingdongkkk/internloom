"""Typed API errors + global handlers. [OPUS]

Guarantees: no endpoint ever crashes on bad input with a raw 500. Validation
errors, our own ApiError, and truly-unexpected exceptions all come back in the
standard envelope with a stable error code.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .envelope import err


class ApiError(Exception):
    """Business-logic error with an HTTP status and stable code."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


# --- Convenience constructors for the errors the spec calls out explicitly ---
def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found")


def forbidden(msg: str = "You are not allowed to access this resource") -> ApiError:
    return ApiError(403, "FORBIDDEN", msg)


def conflict(code: str, msg: str, details: dict | None = None) -> ApiError:
    return ApiError(409, code, msg, details)


def bad_request(code: str, msg: str, details: dict | None = None) -> ApiError:
    return ApiError(400, code, msg, details)


def register_exception_handlers(app):
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content=err(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=err("VALIDATION_ERROR", "Request failed validation", {"errors": exc.errors()}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content=err("HTTP_ERROR", str(exc.detail)))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        # Last line of defence: never leak a stack trace, never crash.
        return JSONResponse(status_code=500, content=err("INTERNAL_ERROR", "Something went wrong"))
