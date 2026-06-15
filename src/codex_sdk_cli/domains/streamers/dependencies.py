from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import StreamerRepositoryDep

from .use_cases import (
    CreateChannelUseCase,
    CreateStreamerUseCase,
    DeleteChannelUseCase,
    DeleteStreamerUseCase,
    GetChannelUseCase,
    GetStreamerUseCase,
    ListChannelsUseCase,
    ListStreamersUseCase,
    UpdateChannelUseCase,
    UpdateStreamerUseCase,
)


def get_create_streamer_use_case(repository: StreamerRepositoryDep) -> CreateStreamerUseCase:
    return CreateStreamerUseCase(repository)


def get_list_streamers_use_case(repository: StreamerRepositoryDep) -> ListStreamersUseCase:
    return ListStreamersUseCase(repository)


def get_get_streamer_use_case(repository: StreamerRepositoryDep) -> GetStreamerUseCase:
    return GetStreamerUseCase(repository)


def get_update_streamer_use_case(repository: StreamerRepositoryDep) -> UpdateStreamerUseCase:
    return UpdateStreamerUseCase(repository)


def get_delete_streamer_use_case(repository: StreamerRepositoryDep) -> DeleteStreamerUseCase:
    return DeleteStreamerUseCase(repository)


def get_create_channel_use_case(repository: StreamerRepositoryDep) -> CreateChannelUseCase:
    return CreateChannelUseCase(repository)


def get_list_channels_use_case(repository: StreamerRepositoryDep) -> ListChannelsUseCase:
    return ListChannelsUseCase(repository)


def get_get_channel_use_case(repository: StreamerRepositoryDep) -> GetChannelUseCase:
    return GetChannelUseCase(repository)


def get_update_channel_use_case(repository: StreamerRepositoryDep) -> UpdateChannelUseCase:
    return UpdateChannelUseCase(repository)


def get_delete_channel_use_case(repository: StreamerRepositoryDep) -> DeleteChannelUseCase:
    return DeleteChannelUseCase(repository)


CreateStreamerUseCaseDep = Annotated[
    CreateStreamerUseCase,
    Depends(get_create_streamer_use_case),
]
ListStreamersUseCaseDep = Annotated[
    ListStreamersUseCase,
    Depends(get_list_streamers_use_case),
]
GetStreamerUseCaseDep = Annotated[
    GetStreamerUseCase,
    Depends(get_get_streamer_use_case),
]
UpdateStreamerUseCaseDep = Annotated[
    UpdateStreamerUseCase,
    Depends(get_update_streamer_use_case),
]
DeleteStreamerUseCaseDep = Annotated[
    DeleteStreamerUseCase,
    Depends(get_delete_streamer_use_case),
]
CreateChannelUseCaseDep = Annotated[
    CreateChannelUseCase,
    Depends(get_create_channel_use_case),
]
ListChannelsUseCaseDep = Annotated[
    ListChannelsUseCase,
    Depends(get_list_channels_use_case),
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

