from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from codex_sdk_cli.api.exception_handlers import add_exception_handlers
from codex_sdk_cli.api.s3_mount import get_s3_mount_status
from codex_sdk_cli.domains.codex.router import router as codex_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Codex SDK CLI API",
        version="0.1.0",
        description="REST API wrapper for Codex SDK run/account/logout workflows.",
    )
    add_exception_handlers(app)
    app.include_router(codex_router, prefix="/codex", tags=["codex"])

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/s3", tags=["system"])
    async def s3_health() -> dict[str, object]:
        return get_s3_mount_status().to_api_dict()

    return app


app = create_app()


def run() -> None:
    uvicorn.run("codex_sdk_cli.api.main:app", host="0.0.0.0", port=8000)
