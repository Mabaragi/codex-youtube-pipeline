from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import OpsRepositoryDep
from codex_sdk_cli.api.s3_mount import get_s3_mount_status
from codex_sdk_cli.domains.ops.use_cases import (
    GetOpsSchemaGraphUseCase,
    GetOpsSummaryUseCase,
    GetOpsVideoDetailUseCase,
    ListOpsChannelsUseCase,
    ListOpsVideosUseCase,
    ListOpsVideoTasksUseCase,
)


def get_ops_summary_use_case(
    repository: OpsRepositoryDep,
) -> GetOpsSummaryUseCase:
    return GetOpsSummaryUseCase(
        repository,
        lambda: get_s3_mount_status().to_api_dict(),
    )


def get_list_ops_channels_use_case(
    repository: OpsRepositoryDep,
) -> ListOpsChannelsUseCase:
    return ListOpsChannelsUseCase(repository)


def get_list_ops_videos_use_case(
    repository: OpsRepositoryDep,
) -> ListOpsVideosUseCase:
    return ListOpsVideosUseCase(repository)


def get_ops_video_detail_use_case(
    repository: OpsRepositoryDep,
) -> GetOpsVideoDetailUseCase:
    return GetOpsVideoDetailUseCase(repository)


def get_list_ops_video_tasks_use_case(
    repository: OpsRepositoryDep,
) -> ListOpsVideoTasksUseCase:
    return ListOpsVideoTasksUseCase(repository)


def get_ops_schema_graph_use_case(
    repository: OpsRepositoryDep,
) -> GetOpsSchemaGraphUseCase:
    return GetOpsSchemaGraphUseCase(repository)


OpsSummaryUseCaseDep = Annotated[
    GetOpsSummaryUseCase,
    Depends(get_ops_summary_use_case),
]
ListOpsChannelsUseCaseDep = Annotated[
    ListOpsChannelsUseCase,
    Depends(get_list_ops_channels_use_case),
]
ListOpsVideosUseCaseDep = Annotated[
    ListOpsVideosUseCase,
    Depends(get_list_ops_videos_use_case),
]
OpsVideoDetailUseCaseDep = Annotated[
    GetOpsVideoDetailUseCase,
    Depends(get_ops_video_detail_use_case),
]
ListOpsVideoTasksUseCaseDep = Annotated[
    ListOpsVideoTasksUseCase,
    Depends(get_list_ops_video_tasks_use_case),
]
OpsSchemaGraphUseCaseDep = Annotated[
    GetOpsSchemaGraphUseCase,
    Depends(get_ops_schema_graph_use_case),
]
