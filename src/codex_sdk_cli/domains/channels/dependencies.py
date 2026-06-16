from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ChannelRepositoryDep,
    PipelineJobRepositoryDep,
    StreamerRepositoryDep,
    YouTubeDataClientDep,
)

from .use_cases import (
    CreateChannelUseCase,
    DeleteChannelUseCase,
    GetChannelUseCase,
    ListChannelsUseCase,
    ListStreamerChannelsUseCase,
    ResolveYouTubeChannelUseCase,
    UpdateChannelUseCase,
)


def get_create_channel_use_case(
    channels: ChannelRepositoryDep,
    streamers: StreamerRepositoryDep,
) -> CreateChannelUseCase:
    return CreateChannelUseCase(channels, streamers)


def get_list_channels_use_case(channels: ChannelRepositoryDep) -> ListChannelsUseCase:
    return ListChannelsUseCase(channels)


def get_list_streamer_channels_use_case(
    channels: ChannelRepositoryDep,
    streamers: StreamerRepositoryDep,
) -> ListStreamerChannelsUseCase:
    return ListStreamerChannelsUseCase(channels, streamers)


def get_get_channel_use_case(channels: ChannelRepositoryDep) -> GetChannelUseCase:
    return GetChannelUseCase(channels)


def get_update_channel_use_case(channels: ChannelRepositoryDep) -> UpdateChannelUseCase:
    return UpdateChannelUseCase(channels)


def get_delete_channel_use_case(channels: ChannelRepositoryDep) -> DeleteChannelUseCase:
    return DeleteChannelUseCase(channels)


def get_resolve_youtube_channel_use_case(
    client: YouTubeDataClientDep,
    channels: ChannelRepositoryDep,
    streamers: StreamerRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
) -> ResolveYouTubeChannelUseCase:
    return ResolveYouTubeChannelUseCase(client, channels, streamers, pipeline_jobs)


CreateChannelUseCaseDep = Annotated[
    CreateChannelUseCase,
    Depends(get_create_channel_use_case),
]
ListChannelsUseCaseDep = Annotated[
    ListChannelsUseCase,
    Depends(get_list_channels_use_case),
]
ListStreamerChannelsUseCaseDep = Annotated[
    ListStreamerChannelsUseCase,
    Depends(get_list_streamer_channels_use_case),
]
GetChannelUseCaseDep = Annotated[
    GetChannelUseCase,
    Depends(get_get_channel_use_case),
]
UpdateChannelUseCaseDep = Annotated[
    UpdateChannelUseCase,
    Depends(get_update_channel_use_case),
]
DeleteChannelUseCaseDep = Annotated[
    DeleteChannelUseCase,
    Depends(get_delete_channel_use_case),
]
ResolveYouTubeChannelUseCaseDep = Annotated[
    ResolveYouTubeChannelUseCase,
    Depends(get_resolve_youtube_channel_use_case),
]
