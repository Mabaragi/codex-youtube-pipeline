from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
from codex_sdk_cli.domains.codex.ports import CodexRuntimePort
from codex_sdk_cli.domains.codex_usage.ports import (
    CodexUsageRecorderPort,
    CodexUsageRepositoryPort,
)
from codex_sdk_cli.domains.codex_usage.recorder import BestEffortCodexUsageRecorder
from codex_sdk_cli.domains.domain_knowledge.ports import DomainKnowledgeRepositoryPort
from codex_sdk_cli.domains.external_api_calls.ports import ExternalApiCallRecorderPort
from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventExtractionRepositoryPort,
    MicroEventExtractorPort,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventRecorderPort,
    OperationEventRepositoryPort,
)
from codex_sdk_cli.domains.operation_events.recorder import BestEffortOperationEventRecorder
from codex_sdk_cli.domains.ops.ports import OpsRepositoryPort
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobRepositoryPort
from codex_sdk_cli.domains.prompts.cache import PromptCache
from codex_sdk_cli.domains.prompts.ports import PromptRepositoryPort
from codex_sdk_cli.domains.streamers.ports import StreamerRepositoryPort
from codex_sdk_cli.domains.timelines.ports import (
    TimelineComposerPort,
    TimelineCompositionRepositoryPort,
)
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueRepositoryPort
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.domains.videos.ports import VideoRepositoryPort
from codex_sdk_cli.domains.youtube_data.exceptions import YouTubeDataConfigurationError
from codex_sdk_cli.domains.youtube_data.ports import YouTubeDataClientPort
from codex_sdk_cli.domains.youtube_transcripts.exceptions import YouTubeTranscriptStorageError
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptPort,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptStoragePort,
)
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.codex.client import CodexRuntimeClient
from codex_sdk_cli.infra.codex.recording import RecordingCodexRuntime
from codex_sdk_cli.infra.codex_usage.repository import (
    SessionFactoryCodexUsageRepository,
    SqlAlchemyCodexUsageRepository,
)
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.domain_knowledge.repository import (
    SqlAlchemyDomainKnowledgeRepository,
)
from codex_sdk_cli.infra.external_api_calls.recorder import ExternalApiCallRecorder
from codex_sdk_cli.infra.external_api_calls.repository import SqlAlchemyExternalApiCallRepository
from codex_sdk_cli.infra.external_api_calls.storage import MinioExternalApiCallStorage
from codex_sdk_cli.infra.micro_events.extractor import CodexMicroEventExtractor
from codex_sdk_cli.infra.micro_events.repository import (
    SqlAlchemyMicroEventExtractionRepository,
)
from codex_sdk_cli.infra.operation_events.repository import SQLAlchemyOperationEventRepository
from codex_sdk_cli.infra.ops.repository import SqlAlchemyOpsRepository
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.prompts.repository import SqlAlchemyPromptRepository
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository
from codex_sdk_cli.infra.timelines.composer import CodexTimelineComposer
from codex_sdk_cli.infra.timelines.repository import (
    SqlAlchemyTimelineCompositionRepository,
)
from codex_sdk_cli.infra.transcript_cues.repository import SqlAlchemyTranscriptCueRepository
from codex_sdk_cli.infra.video_tasks.repository import SqlAlchemyVideoTaskRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.infra.youtube_data.client import YouTubeDataClient
from codex_sdk_cli.infra.youtube_transcripts.client import YouTubeTranscriptClient
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)
from codex_sdk_cli.infra.youtube_transcripts.storage import MinioTranscriptStorage
from codex_sdk_cli.settings import CliSettings

_PROMPT_CACHE = PromptCache()


@lru_cache
def get_settings() -> CliSettings:
    return CliSettings()


async def get_codex_runtime(
    settings: Annotated[CliSettings, Depends(get_settings)],
    usage_recorder: CodexUsageRecorderDep,
) -> CodexRuntimePort:
    return RecordingCodexRuntime(CodexRuntimeClient(settings), usage_recorder)


@lru_cache
def _get_database_engine(database_url: str, echo: bool) -> AsyncEngine:
    return create_database_engine(database_url, echo=echo)


def get_database_engine(settings: Annotated[CliSettings, Depends(get_settings)]) -> AsyncEngine:
    return _get_database_engine(settings.database_url, settings.database_echo)


def get_database_session_factory(
    engine: Annotated[AsyncEngine, Depends(get_database_engine)],
) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


async def get_database_session(
    session_factory: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_database_session_factory),
    ],
) -> AsyncGenerator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def get_youtube_transcript_client(
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> YouTubeTranscriptPort:
    return YouTubeTranscriptClient.from_settings(settings)


async def get_youtube_transcript_repository(
    session: DatabaseSessionDep,
) -> YouTubeTranscriptRepositoryPort:
    return SqlAlchemyYouTubeTranscriptRepository(session)


async def get_streamer_repository(
    session: DatabaseSessionDep,
) -> StreamerRepositoryPort:
    return SqlAlchemyStreamerRepository(session)


async def get_channel_repository(
    session: DatabaseSessionDep,
) -> ChannelRepositoryPort:
    return SqlAlchemyChannelRepository(session)


async def get_pipeline_job_repository(
    session: DatabaseSessionDep,
) -> PipelineJobRepositoryPort:
    return SqlAlchemyPipelineJobRepository(session)


async def get_video_repository(
    session: DatabaseSessionDep,
) -> VideoRepositoryPort:
    return SqlAlchemyVideoRepository(session)


async def get_video_task_repository(
    session: DatabaseSessionDep,
) -> VideoTaskRepositoryPort:
    return SqlAlchemyVideoTaskRepository(session)


async def get_micro_event_extraction_repository(
    session: DatabaseSessionDep,
) -> MicroEventExtractionRepositoryPort:
    return SqlAlchemyMicroEventExtractionRepository(session)


async def get_codex_usage_repository(
    session: DatabaseSessionDep,
) -> CodexUsageRepositoryPort:
    return SqlAlchemyCodexUsageRepository(session)


async def get_domain_knowledge_repository(
    session: DatabaseSessionDep,
) -> DomainKnowledgeRepositoryPort:
    return SqlAlchemyDomainKnowledgeRepository(session)


async def get_prompt_repository(
    session: DatabaseSessionDep,
) -> PromptRepositoryPort:
    return SqlAlchemyPromptRepository(session)


def get_prompt_cache() -> PromptCache:
    return _PROMPT_CACHE


async def get_codex_usage_recorder(
    session_factory: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_database_session_factory),
    ],
) -> CodexUsageRecorderPort:
    return BestEffortCodexUsageRecorder(
        SessionFactoryCodexUsageRepository(session_factory)
    )


async def get_micro_event_extractor(
    runtime: CodexRuntimeDep,
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> MicroEventExtractorPort:
    return CodexMicroEventExtractor(
        runtime,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
    )


async def get_timeline_composer(
    runtime: CodexRuntimeDep,
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> TimelineComposerPort:
    return CodexTimelineComposer(
        runtime,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
    )


async def get_transcript_cue_repository(
    session: DatabaseSessionDep,
) -> TranscriptCueRepositoryPort:
    return SqlAlchemyTranscriptCueRepository(session)


async def get_timeline_composition_repository(
    session: DatabaseSessionDep,
) -> TimelineCompositionRepositoryPort:
    return SqlAlchemyTimelineCompositionRepository(session)


async def get_ops_repository(
    session: DatabaseSessionDep,
) -> OpsRepositoryPort:
    return SqlAlchemyOpsRepository(session)


async def get_operation_event_repository(
    session: DatabaseSessionDep,
) -> OperationEventRepositoryPort:
    return SQLAlchemyOperationEventRepository(session)


async def get_operation_event_recorder(
    repository: OperationEventRepositoryDep,
) -> OperationEventRecorderPort:
    return BestEffortOperationEventRecorder(repository)


async def get_youtube_data_client(
    settings: Annotated[CliSettings, Depends(get_settings)],
    session: DatabaseSessionDep,
) -> AsyncGenerator[YouTubeDataClientPort]:
    api_key = settings.youtube_data_api_key_value()
    if api_key is None:
        raise YouTubeDataConfigurationError("YouTube Data API key is not configured.")
    api_call_recorder = _external_api_call_recorder(settings, session)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.youtube_data_timeout_seconds),
    ) as http_client:
        yield YouTubeDataClient(
            http_client,
            api_key=api_key,
            api_call_recorder=api_call_recorder,
        )


def _external_api_call_recorder(
    settings: CliSettings,
    session: AsyncSession,
) -> ExternalApiCallRecorderPort:
    return ExternalApiCallRecorder(
        SqlAlchemyExternalApiCallRepository(session),
        MinioExternalApiCallStorage.from_settings(settings),
        storage_prefix=settings.external_api_call_minio_prefix,
    )


async def get_youtube_transcript_storage(
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> YouTubeTranscriptStoragePort:
    if (
        settings.transcript_minio_endpoint is None
        or settings.transcript_minio_access_key is None
        or settings.transcript_minio_secret_key is None
        or settings.transcript_minio_bucket is None
    ):
        raise YouTubeTranscriptStorageError("Transcript MinIO storage is not configured.")
    return MinioTranscriptStorage.from_settings(settings)


SettingsDep = Annotated[CliSettings, Depends(get_settings)]
CodexRuntimeDep = Annotated[CodexRuntimePort, Depends(get_codex_runtime)]
DatabaseSessionDep = Annotated[AsyncSession, Depends(get_database_session)]
CodexUsageRepositoryDep = Annotated[
    CodexUsageRepositoryPort,
    Depends(get_codex_usage_repository),
]
DomainKnowledgeRepositoryDep = Annotated[
    DomainKnowledgeRepositoryPort,
    Depends(get_domain_knowledge_repository),
]
PromptRepositoryDep = Annotated[
    PromptRepositoryPort,
    Depends(get_prompt_repository),
]
PromptCacheDep = Annotated[
    PromptCache,
    Depends(get_prompt_cache),
]
CodexUsageRecorderDep = Annotated[
    CodexUsageRecorderPort,
    Depends(get_codex_usage_recorder),
]
YouTubeTranscriptClientDep = Annotated[
    YouTubeTranscriptPort,
    Depends(get_youtube_transcript_client),
]
YouTubeTranscriptRepositoryDep = Annotated[
    YouTubeTranscriptRepositoryPort,
    Depends(get_youtube_transcript_repository),
]
StreamerRepositoryDep = Annotated[
    StreamerRepositoryPort,
    Depends(get_streamer_repository),
]
ChannelRepositoryDep = Annotated[
    ChannelRepositoryPort,
    Depends(get_channel_repository),
]
PipelineJobRepositoryDep = Annotated[
    PipelineJobRepositoryPort,
    Depends(get_pipeline_job_repository),
]
VideoRepositoryDep = Annotated[
    VideoRepositoryPort,
    Depends(get_video_repository),
]
VideoTaskRepositoryDep = Annotated[
    VideoTaskRepositoryPort,
    Depends(get_video_task_repository),
]
MicroEventExtractionRepositoryDep = Annotated[
    MicroEventExtractionRepositoryPort,
    Depends(get_micro_event_extraction_repository),
]
MicroEventExtractorDep = Annotated[
    MicroEventExtractorPort,
    Depends(get_micro_event_extractor),
]
TimelineComposerDep = Annotated[
    TimelineComposerPort,
    Depends(get_timeline_composer),
]
TranscriptCueRepositoryDep = Annotated[
    TranscriptCueRepositoryPort,
    Depends(get_transcript_cue_repository),
]
TimelineCompositionRepositoryDep = Annotated[
    TimelineCompositionRepositoryPort,
    Depends(get_timeline_composition_repository),
]
OpsRepositoryDep = Annotated[
    OpsRepositoryPort,
    Depends(get_ops_repository),
]
OperationEventRepositoryDep = Annotated[
    OperationEventRepositoryPort,
    Depends(get_operation_event_repository),
]
OperationEventRecorderDep = Annotated[
    OperationEventRecorderPort,
    Depends(get_operation_event_recorder),
]
YouTubeDataClientDep = Annotated[
    YouTubeDataClientPort,
    Depends(get_youtube_data_client),
]
YouTubeTranscriptStorageDep = Annotated[
    YouTubeTranscriptStoragePort,
    Depends(get_youtube_transcript_storage),
]
