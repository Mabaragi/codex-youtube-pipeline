from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from codex_sdk_cli.api.use_case_dependencies.ops import (
    ListOpsChannelsUseCaseDep,
    ListOpsVideosUseCaseDep,
    ListOpsVideoTasksUseCaseDep,
    OpsSchemaGraphUseCaseDep,
    OpsSummaryUseCaseDep,
    OpsVideoDetailUseCaseDep,
)
from codex_sdk_cli.domains.ops.schemas import (
    OpsChannelListResponse,
    OpsSchemaGraphResponse,
    OpsSummaryResponse,
    OpsVideoDetailResponse,
    OpsVideoListResponse,
    OpsVideoTaskListResponse,
)

router = APIRouter()


@router.get("/summary", response_model=OpsSummaryResponse)
async def get_ops_summary(use_case: OpsSummaryUseCaseDep) -> OpsSummaryResponse:
    return await use_case.execute()


@router.get("/channels", response_model=OpsChannelListResponse)
async def list_ops_channels(
    use_case: ListOpsChannelsUseCaseDep,
) -> OpsChannelListResponse:
    return await use_case.execute()


@router.get("/videos", response_model=OpsVideoListResponse)
async def list_ops_videos(
    use_case: ListOpsVideosUseCaseDep,
    channel_id: int | None = Query(default=None, alias="channelId", ge=1),
    task_status: str | None = Query(default=None, alias="taskStatus", min_length=1),
    search: str | None = Query(default=None, min_length=1, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> OpsVideoListResponse:
    return await use_case.execute(
        channel_id=channel_id,
        task_status=task_status,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/videos/{video_id}", response_model=OpsVideoDetailResponse)
async def get_ops_video_detail(
    video_id: Annotated[int, Path(ge=1)],
    use_case: OpsVideoDetailUseCaseDep,
) -> OpsVideoDetailResponse:
    return await use_case.execute(video_id)


@router.get("/video-tasks", response_model=OpsVideoTaskListResponse)
async def list_ops_video_tasks(
    use_case: ListOpsVideoTasksUseCaseDep,
    channel_id: int | None = Query(default=None, alias="channelId", ge=1),
    task_name: str | None = Query(default=None, alias="taskName", min_length=1),
    status: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> OpsVideoTaskListResponse:
    return await use_case.execute(
        channel_id=channel_id,
        task_name=task_name,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/schema-graph", response_model=OpsSchemaGraphResponse)
async def get_ops_schema_graph(
    use_case: OpsSchemaGraphUseCaseDep,
) -> OpsSchemaGraphResponse:
    return await use_case.execute()
