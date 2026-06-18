from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, status

from .dependencies import (
    CollectChannelTranscriptTasksUseCaseDep,
    ListChannelVideoTasksUseCaseDep,
)
from .ports import VideoTaskStatus
from .schemas import (
    CollectAllTranscriptTasksRequest,
    CollectAllTranscriptTasksResponse,
    CollectChannelTranscriptTasksRequest,
    CollectChannelTranscriptTasksResponse,
    VideoTaskResponse,
)

router = APIRouter()


@router.post(
    "/video-tasks/transcript-collect",
    response_model=CollectAllTranscriptTasksResponse,
    status_code=status.HTTP_201_CREATED,
)
async def collect_all_transcript_tasks(
    use_case: CollectChannelTranscriptTasksUseCaseDep,
    request: Annotated[
        CollectAllTranscriptTasksRequest | None,
        Body(),
    ] = None,
) -> CollectAllTranscriptTasksResponse:
    return await use_case.execute_all(request or CollectAllTranscriptTasksRequest())


@router.post(
    "/channels/{channel_id}/video-tasks/transcript-collect",
    response_model=CollectChannelTranscriptTasksResponse,
    status_code=status.HTTP_201_CREATED,
)
async def collect_channel_transcript_tasks(
    channel_id: Annotated[int, Path(ge=1)],
    use_case: CollectChannelTranscriptTasksUseCaseDep,
    request: Annotated[
        CollectChannelTranscriptTasksRequest | None,
        Body(),
    ] = None,
) -> CollectChannelTranscriptTasksResponse:
    return await use_case.execute(
        channel_id,
        request or CollectChannelTranscriptTasksRequest(),
    )


@router.get("/channels/{channel_id}/video-tasks", response_model=list[VideoTaskResponse])
async def list_channel_video_tasks(
    channel_id: Annotated[int, Path(ge=1)],
    use_case: ListChannelVideoTasksUseCaseDep,
    task_name: Annotated[str | None, Query(alias="taskName", min_length=1)] = None,
    task_status: Annotated[VideoTaskStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[VideoTaskResponse]:
    return await use_case.execute(
        channel_id=channel_id,
        task_name=task_name,
        status=task_status,
        limit=limit,
        offset=offset,
    )
