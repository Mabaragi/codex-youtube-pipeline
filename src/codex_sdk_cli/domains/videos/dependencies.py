from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ChannelRepositoryDep,
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    VideoRepositoryDep,
    YouTubeDataClientDep,
)

from .use_cases import CollectChannelVideosUseCase, ListChannelVideosUseCase


def get_list_channel_videos_use_case(
    channels: ChannelRepositoryDep,
    videos: VideoRepositoryDep,
) -> ListChannelVideosUseCase:
    return ListChannelVideosUseCase(channels, videos)


def get_collect_channel_videos_use_case(
    client: YouTubeDataClientDep,
    channels: ChannelRepositoryDep,
    videos: VideoRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
    events: OperationEventRecorderDep,
) -> CollectChannelVideosUseCase:
    return CollectChannelVideosUseCase(client, channels, videos, pipeline_jobs, events)


ListChannelVideosUseCaseDep = Annotated[
    ListChannelVideosUseCase,
    Depends(get_list_channel_videos_use_case),
]
CollectChannelVideosUseCaseDep = Annotated[
    CollectChannelVideosUseCase,
    Depends(get_collect_channel_videos_use_case),
]
