from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ChannelRepositoryDep,
    DomainKnowledgeRepositoryDep,
    MicroEventExtractionRepositoryDep,
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    SettingsDep,
    StreamerRepositoryDep,
    TimelineComposerDep,
    TimelineCompositionRepositoryDep,
    VideoRepositoryDep,
    VideoTaskRepositoryDep,
)
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
    settings: SettingsDep,
    events: OperationEventRecorderDep,
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
        timeout_seconds=settings.timeline_compose_timeout_seconds,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
        events=events,
    )


ComposeTimelineUseCaseDep = Annotated[
    ComposeTimelineUseCase,
    Depends(get_compose_timeline_use_case),
]
