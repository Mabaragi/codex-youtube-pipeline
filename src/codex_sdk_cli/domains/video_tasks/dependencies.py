from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ChannelRepositoryDep,
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    SettingsDep,
    VideoRepositoryDep,
    VideoTaskRepositoryDep,
    YouTubeTranscriptRepositoryDep,
)
from codex_sdk_cli.domains.youtube_transcripts.dependencies import (
    FetchYouTubeTranscriptUseCaseDep,
)

from .use_cases import CollectChannelTranscriptTasksUseCase, ListChannelVideoTasksUseCase


def get_collect_channel_transcript_tasks_use_case(
    channels: ChannelRepositoryDep,
    videos: VideoRepositoryDep,
    video_tasks: VideoTaskRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
    transcripts: YouTubeTranscriptRepositoryDep,
    fetch_transcript: FetchYouTubeTranscriptUseCaseDep,
    settings: SettingsDep,
    events: OperationEventRecorderDep,
) -> CollectChannelTranscriptTasksUseCase:
    return CollectChannelTranscriptTasksUseCase(
        channels=channels,
        videos=videos,
        video_tasks=video_tasks,
        pipeline_jobs=pipeline_jobs,
        transcripts=transcripts,
        fetch_transcript=fetch_transcript,
        timeout_seconds=settings.transcript_collect_timeout_seconds,
        concurrency_limit=settings.transcript_collect_concurrency_limit,
        delay_seconds=settings.transcript_collect_delay_seconds,
        events=events,
    )


def get_list_channel_video_tasks_use_case(
    channels: ChannelRepositoryDep,
    video_tasks: VideoTaskRepositoryDep,
) -> ListChannelVideoTasksUseCase:
    return ListChannelVideoTasksUseCase(channels=channels, video_tasks=video_tasks)


CollectChannelTranscriptTasksUseCaseDep = Annotated[
    CollectChannelTranscriptTasksUseCase,
    Depends(get_collect_channel_transcript_tasks_use_case),
]
ListChannelVideoTasksUseCaseDep = Annotated[
    ListChannelVideoTasksUseCase,
    Depends(get_list_channel_video_tasks_use_case),
]
