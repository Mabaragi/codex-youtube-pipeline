from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.domains.codex_usage.recorder import BestEffortCodexUsageRecorder
from codex_sdk_cli.domains.operation_events.recorder import (
    BestEffortOperationEventRecorder,
)
from codex_sdk_cli.domains.prompts.cache import PromptCache
from codex_sdk_cli.domains.prompts.use_cases import PromptResolver
from codex_sdk_cli.domains.timelines.use_cases import ComposeTimelineUseCase
from codex_sdk_cli.domains.video_tasks.constants import TIMELINE_COMPOSE_TASK_NAME
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.codex.client import CodexRuntimeClient
from codex_sdk_cli.infra.codex.recording import RecordingCodexRuntime
from codex_sdk_cli.infra.codex_usage.repository import (
    SessionFactoryCodexUsageRepository,
)
from codex_sdk_cli.infra.database import models as database_models
from codex_sdk_cli.infra.database.recovery import recover_timed_out_worker_tasks
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.domain_knowledge.repository import (
    SqlAlchemyDomainKnowledgeRepository,
)
from codex_sdk_cli.infra.micro_events.repository import (
    SqlAlchemyMicroEventExtractionRepository,
)
from codex_sdk_cli.infra.operation_events.repository import (
    SQLAlchemyOperationEventRepository,
)
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.prompts.repository import SqlAlchemyPromptRepository
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository
from codex_sdk_cli.infra.timelines.composer import CodexTimelineComposer
from codex_sdk_cli.infra.timelines.repository import (
    SqlAlchemyTimelineCompositionRepository,
)
from codex_sdk_cli.infra.video_tasks.repository import SqlAlchemyVideoTaskRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.settings import CliSettings

logger = logging.getLogger(__name__)
Sleep = Callable[[float], Awaitable[None]]
_PROMPT_CACHE = PromptCache()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


async def run_worker(
    *,
    settings: CliSettings | None = None,
    stop_after_one: bool = False,
    sleep: Sleep = asyncio.sleep,
) -> None:
    resolved_settings = settings or CliSettings()
    engine = create_database_engine(
        resolved_settings.database_url,
        echo=resolved_settings.database_echo,
    )
    _load_database_models()
    session_factory = create_session_factory(engine)
    worker_id = _worker_id(resolved_settings)
    logger.info("Starting timeline compose worker id=%s", worker_id)
    try:
        while True:
            processed = await _run_once(
                session_factory,
                settings=resolved_settings,
                worker_id=worker_id,
            )
            if stop_after_one:
                return
            if not processed:
                await sleep(resolved_settings.timeline_compose_worker_poll_interval_seconds)
    finally:
        await engine.dispose()


async def _run_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: CliSettings,
    worker_id: str,
) -> bool:
    async with session_factory() as session:
        recovered = await recover_timed_out_worker_tasks(
            session,
            task_name=TIMELINE_COMPOSE_TASK_NAME,
            worker_id_prefix=_worker_recovery_prefix(worker_id),
        )
        if recovered:
            logger.warning("Recovered %s timed out timeline task(s)", recovered)
        video_tasks = SqlAlchemyVideoTaskRepository(session)
        task = await video_tasks.claim_next_pending_task_excluding_running_video(
            task_name=TIMELINE_COMPOSE_TASK_NAME,
            worker_id=worker_id,
        )
        if task is None:
            return False
        logger.info("Claimed timeline task id=%s video_id=%s", task.id, task.video_id)
        use_case = _use_case(
            session,
            session_factory,
            settings=settings,
        )
        try:
            await use_case.execute_claimed_task(task, worker_id=worker_id)
        except Exception as exc:
            logger.exception("Timeline task id=%s failed during worker execution", task.id)
            await _mark_worker_exception_failed(session_factory, task_id=task.id, exc=exc)
        return True


def _use_case(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: CliSettings,
) -> ComposeTimelineUseCase:
    usage_recorder = BestEffortCodexUsageRecorder(
        SessionFactoryCodexUsageRepository(session_factory)
    )
    runtime = RecordingCodexRuntime(CodexRuntimeClient(settings), usage_recorder)
    return ComposeTimelineUseCase(
        videos=SqlAlchemyVideoRepository(session),
        video_tasks=SqlAlchemyVideoTaskRepository(session),
        channels=SqlAlchemyChannelRepository(session),
        streamers=SqlAlchemyStreamerRepository(session),
        domain_knowledge=SqlAlchemyDomainKnowledgeRepository(session),
        micro_events=SqlAlchemyMicroEventExtractionRepository(session),
        timelines=SqlAlchemyTimelineCompositionRepository(session),
        pipeline_jobs=SqlAlchemyPipelineJobRepository(session),
        composer=CodexTimelineComposer(
            runtime,
            model=settings.model,
            reasoning_effort=settings.reasoning_effort,
        ),
        prompt_resolver=PromptResolver(
            SqlAlchemyPromptRepository(session),
            cache=_PROMPT_CACHE,
            ttl_seconds=settings.prompt_cache_ttl_seconds,
        ),
        timeout_seconds=settings.timeline_compose_timeout_seconds,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
        events=BestEffortOperationEventRecorder(
            SQLAlchemyOperationEventRepository(session)
        ),
    )


def _worker_id(settings: CliSettings) -> str:
    if settings.timeline_compose_worker_id is not None:
        return settings.timeline_compose_worker_id
    return f"timeline-compose-worker:{socket.gethostname()}:{os.getpid()}"


def _worker_recovery_prefix(worker_id: str) -> str:
    if worker_id.startswith("timeline-compose-worker:"):
        return "timeline-compose-worker:"
    return worker_id


def _load_database_models() -> None:
    # Ensure all FK target tables are registered when this worker runs standalone.
    _ = database_models.__all__


async def _mark_worker_exception_failed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_id: int,
    exc: Exception,
) -> None:
    async with session_factory() as session:
        video_tasks = SqlAlchemyVideoTaskRepository(session)
        task = await video_tasks.get_task(task_id)
        if task is None or task.status != "running":
            return
        await video_tasks.mark_task_failed(
            task_id,
            error_type=type(exc).__name__,
            error_message=str(exc) or "Timeline worker execution failed.",
        )
