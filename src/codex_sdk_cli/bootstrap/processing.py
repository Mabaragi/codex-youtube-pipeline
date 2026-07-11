from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.domains.codex_usage.recorder import BestEffortCodexUsageRecorder
from codex_sdk_cli.domains.micro_events.use_cases import ExtractVideoMicroEventsUseCase
from codex_sdk_cli.domains.operation_events.recorder import (
    BestEffortOperationEventRecorder,
)
from codex_sdk_cli.domains.prompts.cache import PromptCache
from codex_sdk_cli.domains.prompts.use_cases import PromptResolver
from codex_sdk_cli.domains.timelines.use_cases import ComposeTimelineUseCase
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.codex.client import CodexRuntimeClient
from codex_sdk_cli.infra.codex.recording import RecordingCodexRuntime
from codex_sdk_cli.infra.codex_usage.repository import (
    SessionFactoryCodexUsageRepository,
)
from codex_sdk_cli.infra.domain_knowledge.repository import (
    SqlAlchemyDomainKnowledgeRepository,
)
from codex_sdk_cli.infra.llm_traces.factory import create_llm_trace_recorder
from codex_sdk_cli.infra.micro_events.extractor import CodexMicroEventExtractor
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
from codex_sdk_cli.infra.transcript_cues.repository import (
    SqlAlchemyTranscriptCueRepository,
)
from codex_sdk_cli.infra.video_tasks.repository import SqlAlchemyVideoTaskRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)
from codex_sdk_cli.settings import CliSettings

_PROMPT_CACHE = PromptCache()


def micro_event_use_case(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    settings: CliSettings,
) -> ExtractVideoMicroEventsUseCase:
    runtime = _recording_runtime(session_factory, settings)
    return ExtractVideoMicroEventsUseCase(
        videos=SqlAlchemyVideoRepository(session),
        video_tasks=SqlAlchemyVideoTaskRepository(session),
        transcripts=SqlAlchemyYouTubeTranscriptRepository(session),
        transcript_cues=SqlAlchemyTranscriptCueRepository(session),
        channels=SqlAlchemyChannelRepository(session),
        streamers=SqlAlchemyStreamerRepository(session),
        domain_knowledge=SqlAlchemyDomainKnowledgeRepository(session),
        pipeline_jobs=SqlAlchemyPipelineJobRepository(session),
        micro_events=SqlAlchemyMicroEventExtractionRepository(session),
        extractor=CodexMicroEventExtractor(
            runtime,
            model=settings.model,
            reasoning_effort=settings.reasoning_effort,
        ),
        prompt_resolver=_prompt_resolver(session, settings),
        timeout_seconds=settings.micro_event_extract_timeout_seconds,
        concurrency_limit=settings.micro_event_extract_concurrency_limit,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
        events=_event_recorder(session),
        llm_traces=create_llm_trace_recorder(settings),
    )


def timeline_use_case(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    settings: CliSettings,
) -> ComposeTimelineUseCase:
    runtime = _recording_runtime(session_factory, settings)
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
        prompt_resolver=_prompt_resolver(session, settings),
        timeout_seconds=settings.timeline_compose_timeout_seconds,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
        events=_event_recorder(session),
        llm_traces=create_llm_trace_recorder(settings),
    )


def _recording_runtime(
    session_factory: async_sessionmaker[AsyncSession],
    settings: CliSettings,
) -> RecordingCodexRuntime:
    return RecordingCodexRuntime(
        CodexRuntimeClient(settings),
        BestEffortCodexUsageRecorder(SessionFactoryCodexUsageRepository(session_factory)),
    )


def _prompt_resolver(
    session: AsyncSession,
    settings: CliSettings,
) -> PromptResolver:
    return PromptResolver(
        SqlAlchemyPromptRepository(session),
        cache=_PROMPT_CACHE,
        ttl_seconds=settings.prompt_cache_ttl_seconds,
    )


def _event_recorder(session: AsyncSession) -> BestEffortOperationEventRecorder:
    return BestEffortOperationEventRecorder(SQLAlchemyOperationEventRepository(session))
