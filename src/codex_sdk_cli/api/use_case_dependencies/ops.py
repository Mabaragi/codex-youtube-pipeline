from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    OperationEventRecorderDep,
    OpsRepositoryDep,
    VideoRepositoryDep,
    VideoTaskRepositoryDep,
    YouTubeDataClientDep,
)
from codex_sdk_cli.api.s3_mount import get_s3_mount_status
from codex_sdk_cli.api.use_case_dependencies.work import DatabaseSessionFactoryDep
from codex_sdk_cli.bootstrap.operations import cancel_pending_subject_work_use_case
from codex_sdk_cli.domains.ops.use_cases import (
    DetectOpsStuckTasksUseCase,
    GetOpsSchemaGraphUseCase,
    GetOpsSummaryUseCase,
    GetOpsVideoDetailUseCase,
    ListOpsChannelsUseCase,
    ListOpsMicroEventReadyCandidatesUseCase,
    ListOpsTimelineReadyCandidatesUseCase,
    ListOpsVideosUseCase,
    ListOpsVideoTasksUseCase,
    RefreshOpsVideoEmbedStatusUseCase,
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


def get_refresh_ops_video_embed_status_use_case(
    videos: VideoRepositoryDep,
    video_tasks: VideoTaskRepositoryDep,
    session_factory: DatabaseSessionFactoryDep,
    youtube_data: YouTubeDataClientDep,
    events: OperationEventRecorderDep,
) -> RefreshOpsVideoEmbedStatusUseCase:
    return RefreshOpsVideoEmbedStatusUseCase(
        videos=videos,
        video_tasks=video_tasks,
        pending_work=cancel_pending_subject_work_use_case(session_factory),
        youtube_data=youtube_data,
        events=events,
    )


def get_ops_video_detail_use_case(
    repository: OpsRepositoryDep,
) -> GetOpsVideoDetailUseCase:
    return GetOpsVideoDetailUseCase(repository)


def get_list_ops_video_tasks_use_case(
    repository: OpsRepositoryDep,
) -> ListOpsVideoTasksUseCase:
    return ListOpsVideoTasksUseCase(repository)


def get_list_ops_micro_event_ready_candidates_use_case(
    repository: OpsRepositoryDep,
) -> ListOpsMicroEventReadyCandidatesUseCase:
    return ListOpsMicroEventReadyCandidatesUseCase(repository)


def get_list_ops_timeline_ready_candidates_use_case(
    repository: OpsRepositoryDep,
) -> ListOpsTimelineReadyCandidatesUseCase:
    return ListOpsTimelineReadyCandidatesUseCase(repository)


def get_detect_ops_stuck_tasks_use_case(
    repository: OpsRepositoryDep,
) -> DetectOpsStuckTasksUseCase:
    return DetectOpsStuckTasksUseCase(repository)


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
RefreshOpsVideoEmbedStatusUseCaseDep = Annotated[
    RefreshOpsVideoEmbedStatusUseCase,
    Depends(get_refresh_ops_video_embed_status_use_case),
]
OpsVideoDetailUseCaseDep = Annotated[
    GetOpsVideoDetailUseCase,
    Depends(get_ops_video_detail_use_case),
]
ListOpsVideoTasksUseCaseDep = Annotated[
    ListOpsVideoTasksUseCase,
    Depends(get_list_ops_video_tasks_use_case),
]
ListOpsMicroEventReadyCandidatesUseCaseDep = Annotated[
    ListOpsMicroEventReadyCandidatesUseCase,
    Depends(get_list_ops_micro_event_ready_candidates_use_case),
]
ListOpsTimelineReadyCandidatesUseCaseDep = Annotated[
    ListOpsTimelineReadyCandidatesUseCase,
    Depends(get_list_ops_timeline_ready_candidates_use_case),
]
DetectOpsStuckTasksUseCaseDep = Annotated[
    DetectOpsStuckTasksUseCase,
    Depends(get_detect_ops_stuck_tasks_use_case),
]
OpsSchemaGraphUseCaseDep = Annotated[
    GetOpsSchemaGraphUseCase,
    Depends(get_ops_schema_graph_use_case),
]
