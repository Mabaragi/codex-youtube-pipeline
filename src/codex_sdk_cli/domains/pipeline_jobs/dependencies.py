from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Annotated, Any, cast

from fastapi import Depends, Request

from codex_sdk_cli.api.dependencies import (
    ChannelRepositoryDep,
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    SettingsDep,
    StreamerRepositoryDep,
    VideoRepositoryDep,
    VideoTaskRepositoryDep,
    YouTubeDataClientDep,
    YouTubeTranscriptRepositoryDep,
    get_youtube_transcript_client,
    get_youtube_transcript_storage,
)
from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
from codex_sdk_cli.domains.channels.use_cases import ResolveYouTubeChannelUseCase
from codex_sdk_cli.domains.operation_events.ports import OperationEventRecorderPort
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.domains.video_tasks.use_cases import (
    TRANSCRIPT_COLLECT_STEP,
    CollectChannelTranscriptTasksUseCase,
)
from codex_sdk_cli.domains.videos.ports import VideoRepositoryPort
from codex_sdk_cli.domains.videos.use_cases import (
    VIDEO_COLLECT_STEP,
    CollectChannelVideosUseCase,
)
from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    YouTubeTranscriptStorageError,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptPort,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptStoragePort,
)
from codex_sdk_cli.domains.youtube_transcripts.use_cases import FetchYouTubeTranscriptUseCase
from codex_sdk_cli.infra.youtube_transcripts.client import YouTubeTranscriptClient
from codex_sdk_cli.infra.youtube_transcripts.storage import MinioTranscriptStorage
from codex_sdk_cli.settings import CliSettings

from .ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
)
from .use_cases import (
    CHANNEL_RESOLVE_STEP,
    ChannelResolveRetryExecutor,
    GetPipelineJobUseCase,
    ListPipelineJobsUseCase,
    PipelineRetryExecutor,
    RetryPipelineJobUseCase,
    VideoCollectRetryExecutor,
)

FetchTranscriptUseCaseFactory = Callable[[], Awaitable[FetchYouTubeTranscriptUseCase]]


def get_list_pipeline_jobs_use_case(
    pipeline_jobs: PipelineJobRepositoryDep,
) -> ListPipelineJobsUseCase:
    return ListPipelineJobsUseCase(pipeline_jobs)


def get_pipeline_job_use_case(
    pipeline_jobs: PipelineJobRepositoryDep,
) -> GetPipelineJobUseCase:
    return GetPipelineJobUseCase(pipeline_jobs)


def get_fetch_youtube_transcript_use_case_factory(
    request: Request,
    transcripts: YouTubeTranscriptRepositoryDep,
    settings: SettingsDep,
) -> FetchTranscriptUseCaseFactory:
    async def factory() -> FetchYouTubeTranscriptUseCase:
        return FetchYouTubeTranscriptUseCase(
            await _transcript_client(request, settings),
            await _transcript_storage(request, settings),
            transcripts,
            storage_prefix=settings.transcript_minio_prefix,
        )

    return factory


def get_retry_pipeline_job_use_case(
    pipeline_jobs: PipelineJobRepositoryDep,
    client: YouTubeDataClientDep,
    channels: ChannelRepositoryDep,
    streamers: StreamerRepositoryDep,
    videos: VideoRepositoryDep,
    video_tasks: VideoTaskRepositoryDep,
    transcripts: YouTubeTranscriptRepositoryDep,
    fetch_transcript_factory: Annotated[
        FetchTranscriptUseCaseFactory,
        Depends(get_fetch_youtube_transcript_use_case_factory),
    ],
    settings: SettingsDep,
    events: OperationEventRecorderDep,
) -> RetryPipelineJobUseCase:
    return RetryPipelineJobUseCase(
        pipeline_jobs,
        {
            CHANNEL_RESOLVE_STEP: ChannelResolveRetryExecutor(
                ResolveYouTubeChannelUseCase(client, channels, streamers, pipeline_jobs)
            ),
            VIDEO_COLLECT_STEP: VideoCollectRetryExecutor(
                CollectChannelVideosUseCase(client, channels, videos, pipeline_jobs, events)
            ),
            TRANSCRIPT_COLLECT_STEP: _LazyTranscriptCollectRetryExecutor(
                channels=channels,
                videos=videos,
                video_tasks=video_tasks,
                pipeline_jobs=pipeline_jobs,
                transcripts=transcripts,
                fetch_transcript_factory=fetch_transcript_factory,
                settings=settings,
                events=events,
            ),
        },
        events,
    )


class _LazyTranscriptCollectRetryExecutor(PipelineRetryExecutor):
    def __init__(
        self,
        *,
        channels: ChannelRepositoryPort,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        transcripts: YouTubeTranscriptRepositoryPort,
        fetch_transcript_factory: FetchTranscriptUseCaseFactory,
        settings: CliSettings,
        events: OperationEventRecorderPort,
    ) -> None:
        self._channels = channels
        self._videos = videos
        self._video_tasks = video_tasks
        self._pipeline_jobs = pipeline_jobs
        self._transcripts = transcripts
        self._fetch_transcript_factory = fetch_transcript_factory
        self._settings = settings
        self._events = events

    async def execute(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        use_case = CollectChannelTranscriptTasksUseCase(
            channels=self._channels,
            videos=self._videos,
            video_tasks=self._video_tasks,
            pipeline_jobs=self._pipeline_jobs,
            transcripts=self._transcripts,
            fetch_transcript=await self._fetch_transcript_factory(),
            timeout_seconds=self._settings.transcript_collect_timeout_seconds,
            concurrency_limit=self._settings.transcript_collect_concurrency_limit,
            delay_seconds=self._settings.transcript_collect_delay_seconds,
            events=self._events,
        )
        return await use_case.execute_retry_job_attempt(job, attempt)


async def _transcript_client(
    request: Request,
    settings: CliSettings,
) -> YouTubeTranscriptPort:
    override = await _dependency_override(request, get_youtube_transcript_client)
    if override is not None:
        return cast(YouTubeTranscriptPort, override)
    return YouTubeTranscriptClient.from_settings(settings)


async def _transcript_storage(
    request: Request,
    settings: CliSettings,
) -> YouTubeTranscriptStoragePort:
    override = await _dependency_override(request, get_youtube_transcript_storage)
    if override is not None:
        return cast(YouTubeTranscriptStoragePort, override)
    if (
        settings.transcript_minio_endpoint is None
        or settings.transcript_minio_access_key is None
        or settings.transcript_minio_secret_key is None
        or settings.transcript_minio_bucket is None
    ):
        raise YouTubeTranscriptStorageError("Transcript MinIO storage is not configured.")
    return MinioTranscriptStorage.from_settings(settings)


async def _dependency_override(request: Request, dependency: Callable[..., Any]) -> Any | None:
    override = request.app.dependency_overrides.get(dependency)
    if override is None:
        return None
    value = override()
    if isawaitable(value):
        return await value
    return value


RetryPipelineJobUseCaseDep = Annotated[
    RetryPipelineJobUseCase,
    Depends(get_retry_pipeline_job_use_case),
]
ListPipelineJobsUseCaseDep = Annotated[
    ListPipelineJobsUseCase,
    Depends(get_list_pipeline_jobs_use_case),
]
GetPipelineJobUseCaseDep = Annotated[
    GetPipelineJobUseCase,
    Depends(get_pipeline_job_use_case),
]
