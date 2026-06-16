from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from codex_sdk_cli.api.exception_handlers import add_exception_handlers
from codex_sdk_cli.api.s3_mount import get_s3_mount_status
from codex_sdk_cli.domains.codex.router import router as codex_router
from codex_sdk_cli.domains.pipeline_jobs.router import router as pipeline_jobs_router
from codex_sdk_cli.domains.streamers.router import router as streamers_router
from codex_sdk_cli.domains.youtube_data.router import router as youtube_data_router
from codex_sdk_cli.domains.youtube_transcripts.router import router as youtube_transcripts_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Codex SDK CLI API",
        version="0.1.0",
        description="REST API wrapper for Codex SDK run/account/logout workflows.",
    )
    add_exception_handlers(app)
    app.include_router(codex_router, prefix="/codex", tags=["codex"])
    app.include_router(pipeline_jobs_router, prefix="/pipeline", tags=["pipeline-jobs"])
    app.include_router(streamers_router, tags=["streamers"])
    app.include_router(youtube_data_router, prefix="/youtube-data", tags=["youtube-data"])
    app.include_router(
        youtube_transcripts_router,
        prefix="/youtube-transcripts",
        tags=["youtube-transcripts"],
    )

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
