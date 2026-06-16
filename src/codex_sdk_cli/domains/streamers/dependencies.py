from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import StreamerRepositoryDep

from .use_cases import (
    CreateStreamerUseCase,
    DeleteStreamerUseCase,
    GetStreamerUseCase,
    ListStreamersUseCase,
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
