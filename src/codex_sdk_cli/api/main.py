from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from codex_sdk_cli.api.dependencies import get_settings
from codex_sdk_cli.api.exception_handlers import add_exception_handlers
from codex_sdk_cli.api.routes.archive_publish import router as archive_publish_router
from codex_sdk_cli.api.routes.channels import router as channels_router
from codex_sdk_cli.api.routes.codex import router as codex_router
from codex_sdk_cli.api.routes.codex_usage import router as codex_usage_router
from codex_sdk_cli.api.routes.domain_knowledge import router as domain_knowledge_router
from codex_sdk_cli.api.routes.micro_events import router as micro_events_router
from codex_sdk_cli.api.routes.operation_events import router as operation_events_router
from codex_sdk_cli.api.routes.operations import router as operations_router
from codex_sdk_cli.api.routes.ops import router as ops_router
from codex_sdk_cli.api.routes.prompts import router as prompts_router
from codex_sdk_cli.api.routes.streamers import router as streamers_router
from codex_sdk_cli.api.routes.timelines import router as timelines_router
from codex_sdk_cli.api.routes.work_items import router as work_items_router
from codex_sdk_cli.api.routes.youtube_transcripts import router as youtube_transcripts_router
from codex_sdk_cli.api.s3_mount import get_s3_mount_status
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
                "work_items=%s work_attempts=%s",
                result.work_items,
                result.work_attempts,
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
    app.include_router(domain_knowledge_router, prefix="/ops", tags=["ops-domain-knowledge"])
    app.include_router(prompts_router, prefix="/ops", tags=["ops-prompts"])
    app.include_router(operation_events_router, prefix="/ops", tags=["ops"])
    app.include_router(operations_router, prefix="/ops", tags=["ops-operations"])
    app.include_router(work_items_router, prefix="/ops", tags=["ops-work"])
    app.include_router(streamers_router, prefix="/ops", tags=["ops-streamers"])
    app.include_router(channels_router, prefix="/ops", tags=["ops-channels"])
    app.include_router(micro_events_router, tags=["ops-micro-events"])
    app.include_router(timelines_router, tags=["ops-timelines"])
    app.include_router(archive_publish_router, tags=["ops-archive"])
    app.include_router(
        youtube_transcripts_router,
        prefix="/ops/transcripts",
        tags=["ops-transcripts"],
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
