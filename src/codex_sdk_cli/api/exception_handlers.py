from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from codex_sdk_cli.api.error_mapping import (
    DOMAIN_ERROR_TYPES,
    domain_error_code,
    domain_error_message,
    domain_error_status,
)
from codex_sdk_cli.application.errors import ApplicationError, ErrorKind


def add_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)
    for error_type in DOMAIN_ERROR_TYPES:
        app.add_exception_handler(error_type, domain_error_handler)
    app.add_exception_handler(ValidationError, pydantic_validation_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)


async def application_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApplicationError):
        raise TypeError("Application error handler received an unexpected exception.")
    descriptor = exc.descriptor
    return _error_response(
        status_code=_application_status(descriptor.kind),
        code=descriptor.code,
        message=descriptor.message,
        details=descriptor.details,
    )


async def domain_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    return _error_response(
        status_code=domain_error_status(exc),
        code=domain_error_code(exc),
        message=domain_error_message(exc),
    )


async def pydantic_validation_error_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, ValidationError):
        raise TypeError("Pydantic error handler received an unexpected exception.")
    return _validation_response(exc.errors(include_url=False))


async def request_validation_error_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise TypeError("Request validation handler received an unexpected exception.")
    return _validation_response(exc.errors())


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        raise TypeError("HTTP error handler received an unexpected exception.")
    if not isinstance(exc.detail, str):
        return cast(JSONResponse, await http_exception_handler(request, exc))
    return _error_response(
        status_code=exc.status_code,
        code=f"http_{exc.status_code}",
        message=exc.detail,
    )


def _validation_response(errors: Sequence[object]) -> JSONResponse:
    return _error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="request_validation_failed",
        message="Request validation failed.",
        details={"errors": jsonable_encoder(errors)},
    )


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: object | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


def _application_status(kind: ErrorKind) -> int:
    return {
        ErrorKind.NOT_FOUND: status.HTTP_404_NOT_FOUND,
        ErrorKind.CONFLICT: status.HTTP_409_CONFLICT,
        ErrorKind.VALIDATION: status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorKind.UPSTREAM: status.HTTP_502_BAD_GATEWAY,
        ErrorKind.UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorKind.INTERNAL: status.HTTP_500_INTERNAL_SERVER_ERROR,
    }[kind]
