from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ChannelRepositoryDep,
    DomainKnowledgeRepositoryDep,
    LlmTraceRecorderDep,
    MicroEventExtractionRepositoryDep,
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    SettingsDep,
    StreamerRepositoryDep,
    TimelineComposerDep,
    TimelineCompositionRepositoryDep,
    TranscriptCueRepositoryDep,
    VideoRepositoryDep,
    VideoTaskRepositoryDep,
)
from codex_sdk_cli.api.use_case_dependencies.archive_publish import ArchivePublishUseCaseDep
from codex_sdk_cli.api.use_case_dependencies.prompts import PromptResolverDep
from codex_sdk_cli.domains.timelines.patch_use_cases import PatchTimelineUseCase
from codex_sdk_cli.domains.timelines.use_cases import ComposeTimelineUseCase


def get_compose_timeline_use_case(
    videos: VideoRepositoryDep,
    video_tasks: VideoTaskRepositoryDep,
    channels: ChannelRepositoryDep,
    streamers: StreamerRepositoryDep,
    domain_knowledge: DomainKnowledgeRepositoryDep,
    micro_events: MicroEventExtractionRepositoryDep,
    timelines: TimelineCompositionRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
    composer: TimelineComposerDep,
    prompt_resolver: PromptResolverDep,
    settings: SettingsDep,
    events: OperationEventRecorderDep,
    llm_traces: LlmTraceRecorderDep,
) -> ComposeTimelineUseCase:
    return ComposeTimelineUseCase(
        videos=videos,
        video_tasks=video_tasks,
        channels=channels,
        streamers=streamers,
        domain_knowledge=domain_knowledge,
        micro_events=micro_events,
        timelines=timelines,
        pipeline_jobs=pipeline_jobs,
        composer=composer,
        prompt_resolver=prompt_resolver,
        timeout_seconds=settings.timeline_compose_timeout_seconds,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
        events=events,
        llm_traces=llm_traces,
    )


ComposeTimelineUseCaseDep = Annotated[
    ComposeTimelineUseCase,
    Depends(get_compose_timeline_use_case),
]


def get_patch_timeline_use_case(
    videos: VideoRepositoryDep,
    timelines: TimelineCompositionRepositoryDep,
    micro_events: MicroEventExtractionRepositoryDep,
    transcript_cues: TranscriptCueRepositoryDep,
    events: OperationEventRecorderDep,
    archive_publish: ArchivePublishUseCaseDep,
) -> PatchTimelineUseCase:
    return PatchTimelineUseCase(
        videos=videos,
        timelines=timelines,
        micro_events=micro_events,
        transcript_cues=transcript_cues,
        events=events,
        archive_publish=archive_publish,
    )


PatchTimelineUseCaseDep = Annotated[
    PatchTimelineUseCase,
    Depends(get_patch_timeline_use_case),
]
