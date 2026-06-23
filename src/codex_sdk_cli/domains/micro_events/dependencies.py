from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ChannelRepositoryDep,
    DomainKnowledgeRepositoryDep,
    MicroEventExtractionRepositoryDep,
    MicroEventExtractorDep,
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    SettingsDep,
    TranscriptCueRepositoryDep,
    VideoRepositoryDep,
    VideoTaskRepositoryDep,
    YouTubeTranscriptRepositoryDep,
)

from .use_cases import ExtractVideoMicroEventsUseCase


def get_extract_video_micro_events_use_case(
    videos: VideoRepositoryDep,
    video_tasks: VideoTaskRepositoryDep,
    transcripts: YouTubeTranscriptRepositoryDep,
    transcript_cues: TranscriptCueRepositoryDep,
    channels: ChannelRepositoryDep,
    domain_knowledge: DomainKnowledgeRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
    micro_events: MicroEventExtractionRepositoryDep,
    extractor: MicroEventExtractorDep,
    settings: SettingsDep,
    events: OperationEventRecorderDep,
) -> ExtractVideoMicroEventsUseCase:
    return ExtractVideoMicroEventsUseCase(
        videos=videos,
        video_tasks=video_tasks,
        transcripts=transcripts,
        transcript_cues=transcript_cues,
        channels=channels,
        domain_knowledge=domain_knowledge,
        pipeline_jobs=pipeline_jobs,
        micro_events=micro_events,
        extractor=extractor,
        timeout_seconds=settings.micro_event_extract_timeout_seconds,
        concurrency_limit=settings.micro_event_extract_concurrency_limit,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
        events=events,
    )


ExtractVideoMicroEventsUseCaseDep = Annotated[
    ExtractVideoMicroEventsUseCase,
    Depends(get_extract_video_micro_events_use_case),
]
