from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Annotated, Any, cast

from fastapi import Depends, Request

from codex_sdk_cli.api.dependencies import (
    ArchivePublishRepositoryDep,
    ChannelRepositoryDep,
    DomainKnowledgeRepositoryDep,
    MicroEventExtractionRepositoryDep,
    MicroEventExtractorDep,
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    SettingsDep,
    StreamerRepositoryDep,
    TimelineComposerDep,
    TimelineCompositionRepositoryDep,
    TranscriptCueRepositoryDep,
    VideoRepositoryDep,
    VideoTaskRepositoryDep,
    YouTubeDataClientDep,
    YouTubeTranscriptRepositoryDep,
    get_youtube_transcript_client,
    get_youtube_transcript_storage,
)
from codex_sdk_cli.api.use_case_dependencies.archive_publish import (
    archive_publish_storage_factory,
)
from codex_sdk_cli.api.use_case_dependencies.prompts import PromptResolverDep
from codex_sdk_cli.domains.archive_publish.constants import ARCHIVE_PUBLISH_TASK_NAME
from codex_sdk_cli.domains.archive_publish.ports import ArchivePublishRepositoryPort
from codex_sdk_cli.domains.archive_publish.use_cases import ArchivePublishUseCase
from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
from codex_sdk_cli.domains.channels.use_cases import ResolveYouTubeChannelUseCase
from codex_sdk_cli.domains.domain_knowledge.ports import DomainKnowledgeRepositoryPort
from codex_sdk_cli.domains.micro_events.constants import MICRO_EVENT_EXTRACT_TASK_NAME
from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventExtractionRepositoryPort,
    MicroEventExtractorPort,
)
from codex_sdk_cli.domains.micro_events.use_cases import ExtractVideoMicroEventsUseCase
from codex_sdk_cli.domains.operation_events.ports import OperationEventRecorderPort
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
)
from codex_sdk_cli.domains.pipeline_jobs.use_cases import (
    CHANNEL_RESOLVE_STEP,
    ChannelResolveRetryExecutor,
    GetPipelineJobUseCase,
    ListPipelineJobsUseCase,
    PipelineRetryExecutor,
    RetryPipelineJobUseCase,
    TranscriptCueGenerateRetryExecutor,
    VideoCollectRetryExecutor,
)
from codex_sdk_cli.domains.prompts.ports import PromptResolverPort
from codex_sdk_cli.domains.streamers.ports import StreamerRepositoryPort
from codex_sdk_cli.domains.timelines.ports import (
    TimelineComposerPort,
    TimelineCompositionRepositoryPort,
)
from codex_sdk_cli.domains.timelines.use_cases import ComposeTimelineUseCase
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueRepositoryPort
from codex_sdk_cli.domains.transcript_cues.use_cases import (
    TRANSCRIPT_CUE_GENERATE_STEP,
    GenerateTranscriptCuesUseCase,
)
from codex_sdk_cli.domains.video_tasks.constants import TIMELINE_COMPOSE_TASK_NAME
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.domains.video_tasks.transcript_cue_tasks import (
    GenerateTranscriptCueTasksUseCase,
)
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

FetchTranscriptUseCaseFactory = Callable[[], Awaitable[FetchYouTubeTranscriptUseCase]]
GenerateTranscriptCuesUseCaseFactory = Callable[[], Awaitable[GenerateTranscriptCuesUseCase]]


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


def get_generate_transcript_cues_use_case_factory(
    request: Request,
    transcripts: YouTubeTranscriptRepositoryDep,
    cues: TranscriptCueRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
    settings: SettingsDep,
    events: OperationEventRecorderDep,
) -> GenerateTranscriptCuesUseCaseFactory:
    async def factory() -> GenerateTranscriptCuesUseCase:
        return GenerateTranscriptCuesUseCase(
            transcripts=transcripts,
            storage=await _transcript_storage(request, settings),
            cues=cues,
            pipeline_jobs=pipeline_jobs,
            events=events,
        )

    return factory


def get_retry_pipeline_job_use_case(
    pipeline_jobs: PipelineJobRepositoryDep,
    client: YouTubeDataClientDep,
    channels: ChannelRepositoryDep,
    streamers: StreamerRepositoryDep,
    videos: VideoRepositoryDep,
    video_tasks: VideoTaskRepositoryDep,
    micro_events: MicroEventExtractionRepositoryDep,
    timelines: TimelineCompositionRepositoryDep,
    archive: ArchivePublishRepositoryDep,
    domain_knowledge: DomainKnowledgeRepositoryDep,
    micro_event_extractor: MicroEventExtractorDep,
    timeline_composer: TimelineComposerDep,
    prompt_resolver: PromptResolverDep,
    transcript_cues: TranscriptCueRepositoryDep,
    transcripts: YouTubeTranscriptRepositoryDep,
    fetch_transcript_factory: Annotated[
        FetchTranscriptUseCaseFactory,
        Depends(get_fetch_youtube_transcript_use_case_factory),
    ],
    generate_cues_factory: Annotated[
        GenerateTranscriptCuesUseCaseFactory,
        Depends(get_generate_transcript_cues_use_case_factory),
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
                generate_cues_factory=generate_cues_factory,
                settings=settings,
                events=events,
            ),
            TRANSCRIPT_CUE_GENERATE_STEP: _LazyTranscriptCueGenerateRetryExecutor(
                channels=channels,
                videos=videos,
                video_tasks=video_tasks,
                pipeline_jobs=pipeline_jobs,
                transcripts=transcripts,
                generate_cues_factory=generate_cues_factory,
                settings=settings,
                events=events,
            ),
            MICRO_EVENT_EXTRACT_TASK_NAME: _LazyMicroEventExtractRetryExecutor(
                videos=videos,
                video_tasks=video_tasks,
                pipeline_jobs=pipeline_jobs,
                transcripts=transcripts,
                transcript_cues=transcript_cues,
                channels=channels,
                streamers=streamers,
                domain_knowledge=domain_knowledge,
                micro_events=micro_events,
                extractor=micro_event_extractor,
                prompt_resolver=prompt_resolver,
                settings=settings,
                events=events,
            ),
            TIMELINE_COMPOSE_TASK_NAME: _LazyTimelineComposeRetryExecutor(
                videos=videos,
                video_tasks=video_tasks,
                channels=channels,
                streamers=streamers,
                domain_knowledge=domain_knowledge,
                micro_events=micro_events,
                timelines=timelines,
                pipeline_jobs=pipeline_jobs,
                composer=timeline_composer,
                prompt_resolver=prompt_resolver,
                settings=settings,
                events=events,
            ),
            ARCHIVE_PUBLISH_TASK_NAME: _LazyArchivePublishRetryExecutor(
                videos=videos,
                video_tasks=video_tasks,
                timelines=timelines,
                micro_events=micro_events,
                transcript_cues=transcript_cues,
                pipeline_jobs=pipeline_jobs,
                archive=archive,
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
        generate_cues_factory: GenerateTranscriptCuesUseCaseFactory,
        settings: CliSettings,
        events: OperationEventRecorderPort,
    ) -> None:
        self._channels = channels
        self._videos = videos
        self._video_tasks = video_tasks
        self._pipeline_jobs = pipeline_jobs
        self._transcripts = transcripts
        self._fetch_transcript_factory = fetch_transcript_factory
        self._generate_cues_factory = generate_cues_factory
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
            generate_cues=GenerateTranscriptCueTasksUseCase(
                channels=self._channels,
                videos=self._videos,
                video_tasks=self._video_tasks,
                transcripts=self._transcripts,
                pipeline_jobs=self._pipeline_jobs,
                generate_cues=await self._generate_cues_factory(),
                timeout_seconds=self._settings.transcript_cue_generate_timeout_seconds,
                concurrency_limit=(self._settings.transcript_cue_generate_concurrency_limit),
                events=self._events,
            ),
            timeout_seconds=self._settings.transcript_collect_timeout_seconds,
            concurrency_limit=self._settings.transcript_collect_concurrency_limit,
            delay_seconds=self._settings.transcript_collect_delay_seconds,
            events=self._events,
        )
        return await use_case.execute_retry_job_attempt(job, attempt)


class _LazyTranscriptCueGenerateRetryExecutor(PipelineRetryExecutor):
    def __init__(
        self,
        *,
        channels: ChannelRepositoryPort,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        transcripts: YouTubeTranscriptRepositoryPort,
        generate_cues_factory: GenerateTranscriptCuesUseCaseFactory,
        settings: CliSettings,
        events: OperationEventRecorderPort,
    ) -> None:
        self._channels = channels
        self._videos = videos
        self._video_tasks = video_tasks
        self._pipeline_jobs = pipeline_jobs
        self._transcripts = transcripts
        self._generate_cues_factory = generate_cues_factory
        self._settings = settings
        self._events = events

    async def execute(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        use_case = await self._generate_cues_factory()
        if "videoTaskId" not in job.input_json:
            return await TranscriptCueGenerateRetryExecutor(use_case).execute(job, attempt)
        task_use_case = GenerateTranscriptCueTasksUseCase(
            channels=self._channels,
            videos=self._videos,
            video_tasks=self._video_tasks,
            transcripts=self._transcripts,
            pipeline_jobs=self._pipeline_jobs,
            generate_cues=use_case,
            timeout_seconds=self._settings.transcript_cue_generate_timeout_seconds,
            concurrency_limit=self._settings.transcript_cue_generate_concurrency_limit,
            events=self._events,
        )
        return await task_use_case.execute_retry_job_attempt(job, attempt)


class _LazyMicroEventExtractRetryExecutor(PipelineRetryExecutor):
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        transcripts: YouTubeTranscriptRepositoryPort,
        transcript_cues: TranscriptCueRepositoryPort,
        channels: ChannelRepositoryPort,
        streamers: StreamerRepositoryPort,
        domain_knowledge: DomainKnowledgeRepositoryPort,
        micro_events: MicroEventExtractionRepositoryPort,
        extractor: MicroEventExtractorPort,
        prompt_resolver: PromptResolverPort,
        settings: CliSettings,
        events: OperationEventRecorderPort,
    ) -> None:
        self._videos = videos
        self._video_tasks = video_tasks
        self._pipeline_jobs = pipeline_jobs
        self._transcripts = transcripts
        self._transcript_cues = transcript_cues
        self._channels = channels
        self._streamers = streamers
        self._domain_knowledge = domain_knowledge
        self._micro_events = micro_events
        self._extractor = extractor
        self._prompt_resolver = prompt_resolver
        self._settings = settings
        self._events = events

    async def execute(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        use_case = ExtractVideoMicroEventsUseCase(
            videos=self._videos,
            video_tasks=self._video_tasks,
            transcripts=self._transcripts,
            transcript_cues=self._transcript_cues,
            channels=self._channels,
            streamers=self._streamers,
            domain_knowledge=self._domain_knowledge,
            pipeline_jobs=self._pipeline_jobs,
            micro_events=self._micro_events,
            extractor=self._extractor,
            prompt_resolver=self._prompt_resolver,
            timeout_seconds=self._settings.micro_event_extract_timeout_seconds,
            concurrency_limit=self._settings.micro_event_extract_concurrency_limit,
            model=self._settings.model,
            reasoning_effort=self._settings.reasoning_effort,
            events=self._events,
        )
        return await use_case.execute_retry_job_attempt(job, attempt)


class _LazyTimelineComposeRetryExecutor(PipelineRetryExecutor):
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        channels: ChannelRepositoryPort,
        streamers: StreamerRepositoryPort,
        domain_knowledge: DomainKnowledgeRepositoryPort,
        micro_events: MicroEventExtractionRepositoryPort,
        timelines: TimelineCompositionRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        composer: TimelineComposerPort,
        prompt_resolver: PromptResolverPort,
        settings: CliSettings,
        events: OperationEventRecorderPort,
    ) -> None:
        self._videos = videos
        self._video_tasks = video_tasks
        self._channels = channels
        self._streamers = streamers
        self._domain_knowledge = domain_knowledge
        self._micro_events = micro_events
        self._timelines = timelines
        self._pipeline_jobs = pipeline_jobs
        self._composer = composer
        self._prompt_resolver = prompt_resolver
        self._settings = settings
        self._events = events

    async def execute(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        use_case = ComposeTimelineUseCase(
            videos=self._videos,
            video_tasks=self._video_tasks,
            channels=self._channels,
            streamers=self._streamers,
            domain_knowledge=self._domain_knowledge,
            micro_events=self._micro_events,
            timelines=self._timelines,
            pipeline_jobs=self._pipeline_jobs,
            composer=self._composer,
            prompt_resolver=self._prompt_resolver,
            timeout_seconds=self._settings.timeline_compose_timeout_seconds,
            model=self._settings.model,
            reasoning_effort=self._settings.reasoning_effort,
            events=self._events,
        )
        return await use_case.execute_retry_job_attempt(job, attempt)


class _LazyArchivePublishRetryExecutor(PipelineRetryExecutor):
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        timelines: TimelineCompositionRepositoryPort,
        micro_events: MicroEventExtractionRepositoryPort,
        transcript_cues: TranscriptCueRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        archive: ArchivePublishRepositoryPort,
        settings: CliSettings,
        events: OperationEventRecorderPort,
    ) -> None:
        self._videos = videos
        self._video_tasks = video_tasks
        self._timelines = timelines
        self._micro_events = micro_events
        self._transcript_cues = transcript_cues
        self._pipeline_jobs = pipeline_jobs
        self._archive = archive
        self._settings = settings
        self._events = events

    async def execute(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        use_case = ArchivePublishUseCase(
            videos=self._videos,
            video_tasks=self._video_tasks,
            timelines=self._timelines,
            micro_events=self._micro_events,
            transcript_cues=self._transcript_cues,
            pipeline_jobs=self._pipeline_jobs,
            archive=self._archive,
            events=self._events,
            timeout_seconds=self._settings.archive_publish_timeout_seconds,
            public_base_url=self._settings.archive_publish_public_base_url,
            prefix=self._settings.archive_publish_prefix,
            default_environment=self._settings.archive_publish_environment,
            default_schema_version=1,
            storage_factory=archive_publish_storage_factory(self._settings),
            storage_bucket=self._settings.archive_publish_r2_bucket,
            storage_endpoint=self._settings.archive_publish_r2_endpoint,
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
