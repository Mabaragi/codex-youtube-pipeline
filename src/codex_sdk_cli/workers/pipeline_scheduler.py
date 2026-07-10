from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.domains.operation_events.recorder import (
    BestEffortOperationEventRecorder,
)
from codex_sdk_cli.domains.pipeline_scheduler.use_cases import (
    PipelineSchedulerConfig,
    RunPipelineSchedulerTickUseCase,
)
from codex_sdk_cli.domains.transcript_cues.use_cases import GenerateTranscriptCuesUseCase
from codex_sdk_cli.domains.video_tasks.transcript_cue_tasks import (
    GenerateTranscriptCueTasksUseCase,
)
from codex_sdk_cli.domains.video_tasks.use_cases import CollectChannelTranscriptTasksUseCase
from codex_sdk_cli.domains.videos.use_cases import CollectChannelVideosUseCase
from codex_sdk_cli.domains.youtube_data.exceptions import YouTubeDataConfigurationError
from codex_sdk_cli.domains.youtube_transcripts.use_cases import (
    FetchYouTubeTranscriptUseCase,
)
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.external_api_calls.recorder import ExternalApiCallRecorder
from codex_sdk_cli.infra.external_api_calls.repository import (
    SqlAlchemyExternalApiCallRepository,
)
from codex_sdk_cli.infra.external_api_calls.storage import MinioExternalApiCallStorage
from codex_sdk_cli.infra.operation_events.repository import (
    SQLAlchemyOperationEventRepository,
)
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.transcript_cues.repository import (
    SqlAlchemyTranscriptCueRepository,
)
from codex_sdk_cli.infra.video_tasks.repository import SqlAlchemyVideoTaskRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.infra.youtube_data.client import YouTubeDataClient
from codex_sdk_cli.infra.youtube_transcripts.client import YouTubeTranscriptClient
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)
from codex_sdk_cli.infra.youtube_transcripts.storage import MinioTranscriptStorage
from codex_sdk_cli.settings import CliSettings

logger = logging.getLogger(__name__)
Sleep = Callable[[float], Awaitable[None]]


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
    worker_id = _worker_id(resolved_settings)
    if not resolved_settings.pipeline_scheduler_enabled:
        logger.info("Pipeline scheduler is disabled id=%s", worker_id)
        return

    engine = create_database_engine(
        resolved_settings.database_url,
        echo=resolved_settings.database_echo,
    )
    session_factory = create_session_factory(engine)
    logger.info("Starting pipeline scheduler id=%s", worker_id)
    try:
        while True:
            try:
                await _run_once(
                    session_factory,
                    settings=resolved_settings,
                    worker_id=worker_id,
                )
            except Exception:
                logger.exception("Pipeline scheduler tick failed id=%s", worker_id)
            if stop_after_one:
                return
            await sleep(resolved_settings.pipeline_scheduler_poll_interval_seconds)
    finally:
        await engine.dispose()


async def _run_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: CliSettings,
    worker_id: str,
) -> None:
    async with session_factory() as session:
        api_key = settings.youtube_data_api_key_value()
        if api_key is None:
            raise YouTubeDataConfigurationError("YouTube Data API key is not configured.")
        api_call_recorder = ExternalApiCallRecorder(
            SqlAlchemyExternalApiCallRepository(session),
            MinioExternalApiCallStorage.from_settings(settings),
            storage_prefix=settings.external_api_call_minio_prefix,
        )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.youtube_data_timeout_seconds),
        ) as http_client:
            use_case = _use_case(
                session,
                settings=settings,
                youtube_data_client=YouTubeDataClient(
                    http_client,
                    api_key=api_key,
                    api_call_recorder=api_call_recorder,
                ),
            )
            result = await use_case.execute_once()
    logger.info(
        "Pipeline scheduler tick completed id=%s channels=%s processed=%s skipped=%s failed=%s",
        worker_id,
        result.channel_count,
        result.processed_channel_count,
        result.skipped_channel_count,
        result.failed_channel_count,
    )


def _use_case(
    session: AsyncSession,
    *,
    settings: CliSettings,
    youtube_data_client: YouTubeDataClient,
) -> RunPipelineSchedulerTickUseCase:
    channels = SqlAlchemyChannelRepository(session)
    videos = SqlAlchemyVideoRepository(session)
    video_tasks = SqlAlchemyVideoTaskRepository(session)
    pipeline_jobs = SqlAlchemyPipelineJobRepository(session)
    transcripts = SqlAlchemyYouTubeTranscriptRepository(session)
    transcript_storage = MinioTranscriptStorage.from_settings(settings)
    transcript_cues = SqlAlchemyTranscriptCueRepository(session)
    events = BestEffortOperationEventRecorder(SQLAlchemyOperationEventRepository(session))
    generate_cues = GenerateTranscriptCuesUseCase(
        transcripts=transcripts,
        storage=transcript_storage,
        cues=transcript_cues,
        pipeline_jobs=pipeline_jobs,
        events=events,
    )
    generate_cue_tasks = GenerateTranscriptCueTasksUseCase(
        channels=channels,
        videos=videos,
        video_tasks=video_tasks,
        transcripts=transcripts,
        pipeline_jobs=pipeline_jobs,
        generate_cues=generate_cues,
        timeout_seconds=settings.transcript_cue_generate_timeout_seconds,
        concurrency_limit=settings.transcript_cue_generate_concurrency_limit,
        events=events,
    )
    collect_transcripts = CollectChannelTranscriptTasksUseCase(
        channels=channels,
        videos=videos,
        video_tasks=video_tasks,
        pipeline_jobs=pipeline_jobs,
        transcripts=transcripts,
        fetch_transcript=FetchYouTubeTranscriptUseCase(
            YouTubeTranscriptClient.from_settings(settings),
            transcript_storage,
            transcripts,
            storage_prefix=settings.transcript_minio_prefix,
        ),
        generate_cues=generate_cue_tasks,
        timeout_seconds=settings.transcript_collect_timeout_seconds,
        concurrency_limit=settings.transcript_collect_concurrency_limit,
        delay_seconds=settings.transcript_collect_delay_seconds,
        events=events,
    )
    return RunPipelineSchedulerTickUseCase(
        channels=channels,
        video_tasks=video_tasks,
        pipeline_jobs=pipeline_jobs,
        collect_videos=CollectChannelVideosUseCase(
            youtube_data_client,
            channels,
            videos,
            pipeline_jobs,
            events,
        ),
        collect_transcripts=collect_transcripts,
        events=events,
        config=PipelineSchedulerConfig(
            channel_interval_seconds=settings.pipeline_scheduler_channel_interval_seconds,
            transcript_limit=settings.pipeline_scheduler_transcript_limit,
            no_transcript_recheck_interval_seconds=(
                settings.pipeline_scheduler_no_transcript_recheck_interval_seconds
            ),
            no_transcript_limit=settings.pipeline_scheduler_no_transcript_limit,
        ),
    )


def _worker_id(settings: CliSettings) -> str:
    if settings.pipeline_scheduler_id is not None:
        return settings.pipeline_scheduler_id
    return f"pipeline-scheduler:{socket.gethostname()}:{os.getpid()}"


if __name__ == "__main__":
    run()
