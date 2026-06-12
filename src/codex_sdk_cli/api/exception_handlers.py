from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from codex_sdk_cli.domains.codex.exceptions import CodexDomainError, CodexRuntimeError


def add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CodexDomainError)
    async def codex_domain_error_handler(
        _request: Request,
        exc: CodexDomainError,
    ) -> JSONResponse:
        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if isinstance(exc, CodexRuntimeError)
            else status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(ValidationError)
    async def pydantic_validation_error_handler(
        _request: Request,
        exc: ValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": exc.errors(include_url=False)},
        )
