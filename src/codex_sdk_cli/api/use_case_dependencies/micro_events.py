from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ChannelRepositoryDep,
    DomainKnowledgeRepositoryDep,
    LlmTraceRecorderDep,
    MicroEventExtractionRepositoryDep,
    MicroEventExtractorDep,
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    SettingsDep,
    StreamerRepositoryDep,
    TranscriptCueRepositoryDep,
    VideoRepositoryDep,
    VideoTaskRepositoryDep,
    YouTubeTranscriptRepositoryDep,
)
from codex_sdk_cli.api.use_case_dependencies.prompts import PromptResolverDep
from codex_sdk_cli.domains.micro_events.use_cases import ExtractVideoMicroEventsUseCase


def get_extract_video_micro_events_use_case(
    videos: VideoRepositoryDep,
    video_tasks: VideoTaskRepositoryDep,
    transcripts: YouTubeTranscriptRepositoryDep,
    transcript_cues: TranscriptCueRepositoryDep,
    channels: ChannelRepositoryDep,
    streamers: StreamerRepositoryDep,
    domain_knowledge: DomainKnowledgeRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
    micro_events: MicroEventExtractionRepositoryDep,
    extractor: MicroEventExtractorDep,
    prompt_resolver: PromptResolverDep,
    settings: SettingsDep,
    events: OperationEventRecorderDep,
    llm_traces: LlmTraceRecorderDep,
) -> ExtractVideoMicroEventsUseCase:
    return ExtractVideoMicroEventsUseCase(
        videos=videos,
        video_tasks=video_tasks,
        transcripts=transcripts,
        transcript_cues=transcript_cues,
        channels=channels,
        streamers=streamers,
        domain_knowledge=domain_knowledge,
        pipeline_jobs=pipeline_jobs,
        micro_events=micro_events,
        extractor=extractor,
        prompt_resolver=prompt_resolver,
        timeout_seconds=settings.micro_event_extract_timeout_seconds,
        concurrency_limit=settings.micro_event_extract_concurrency_limit,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
        events=events,
        llm_traces=llm_traces,
    )


ExtractVideoMicroEventsUseCaseDep = Annotated[
    ExtractVideoMicroEventsUseCase,
    Depends(get_extract_video_micro_events_use_case),
]
