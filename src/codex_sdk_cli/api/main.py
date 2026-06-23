from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from codex_sdk_cli.api.dependencies import get_settings
from codex_sdk_cli.api.exception_handlers import add_exception_handlers
from codex_sdk_cli.api.s3_mount import get_s3_mount_status
from codex_sdk_cli.domains.channels.router import router as channels_router
from codex_sdk_cli.domains.codex.router import router as codex_router
from codex_sdk_cli.domains.codex_usage.router import router as codex_usage_router
from codex_sdk_cli.domains.domain_knowledge.router import router as domain_knowledge_router
from codex_sdk_cli.domains.micro_events.router import router as micro_events_router
from codex_sdk_cli.domains.operation_events.router import router as operation_events_router
from codex_sdk_cli.domains.ops.router import router as ops_router
from codex_sdk_cli.domains.pipeline_jobs.router import router as pipeline_jobs_router
from codex_sdk_cli.domains.streamers.router import router as streamers_router
from codex_sdk_cli.domains.video_tasks.router import router as video_tasks_router
from codex_sdk_cli.domains.videos.router import router as videos_router
from codex_sdk_cli.domains.youtube_transcripts.router import router as youtube_transcripts_router
from codex_sdk_cli.infra.database.recovery import recover_interrupted_running_work
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    await _recover_interrupted_work_on_startup()
    yield


async def _recover_interrupted_work_on_startup() -> None:
    settings = get_settings()
    engine = create_database_engine(settings.database_url, echo=settings.database_echo)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            result = await recover_interrupted_running_work(session)
        if result.total > 0:
            logger.warning(
                "Recovered interrupted running work on startup: "
                "pipeline_jobs=%s pipeline_job_attempts=%s video_tasks=%s",
                result.pipeline_jobs,
                result.pipeline_job_attempts,
                result.video_tasks,
            )
    except Exception:
        logger.exception("Failed to recover interrupted running work on startup.")
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Codex SDK CLI API",
        version="0.1.0",
        description="REST API wrapper for Codex SDK run/account/logout workflows.",
        lifespan=lifespan,
    )
    add_exception_handlers(app)
    app.include_router(codex_router, prefix="/codex", tags=["codex"])
    app.include_router(ops_router, prefix="/ops", tags=["ops"])
    app.include_router(codex_usage_router, prefix="/ops", tags=["ops"])
    app.include_router(domain_knowledge_router, tags=["domain-knowledge"])
    app.include_router(operation_events_router, prefix="/ops", tags=["ops"])
    app.include_router(pipeline_jobs_router, prefix="/pipeline", tags=["pipeline-jobs"])
    app.include_router(streamers_router, tags=["streamers"])
    app.include_router(channels_router, tags=["channels"])
    app.include_router(videos_router, tags=["videos"])
    app.include_router(video_tasks_router, tags=["video-tasks"])
    app.include_router(micro_events_router, tags=["micro-events"])
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
