from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, status

from codex_sdk_cli.api.use_case_dependencies.video_tasks import (
    CancelVideoTasksUseCaseDep,
    CollectChannelTranscriptTasksUseCaseDep,
    GenerateTranscriptCueTasksUseCaseDep,
    ListChannelVideoTasksUseCaseDep,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskStatus
from codex_sdk_cli.domains.video_tasks.schemas import (
    CancelVideoTasksRequest,
    CancelVideoTasksResponse,
    CollectAllTranscriptTasksRequest,
    CollectAllTranscriptTasksResponse,
    CollectChannelTranscriptTasksRequest,
    CollectChannelTranscriptTasksResponse,
    GenerateAllTranscriptCueTasksResponse,
    GenerateChannelTranscriptCueTasksResponse,
    GenerateTranscriptCueTasksRequest,
    VideoTaskResponse,
)

router = APIRouter()


@router.post("/video-tasks/cancel", response_model=CancelVideoTasksResponse)
async def cancel_video_tasks(
    use_case: CancelVideoTasksUseCaseDep,
    request: CancelVideoTasksRequest,
) -> CancelVideoTasksResponse:
    return await use_case.execute(request)


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
    "/video-tasks/transcript-cue-generate",
    response_model=GenerateAllTranscriptCueTasksResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_all_transcript_cue_tasks(
    use_case: GenerateTranscriptCueTasksUseCaseDep,
    request: Annotated[
        GenerateTranscriptCueTasksRequest | None,
        Body(),
    ] = None,
) -> GenerateAllTranscriptCueTasksResponse:
    return await use_case.execute_all(request or GenerateTranscriptCueTasksRequest())


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


@router.post(
    "/channels/{channel_id}/video-tasks/transcript-cue-generate",
    response_model=GenerateChannelTranscriptCueTasksResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_channel_transcript_cue_tasks(
    channel_id: Annotated[int, Path(ge=1)],
    use_case: GenerateTranscriptCueTasksUseCaseDep,
    request: Annotated[
        GenerateTranscriptCueTasksRequest | None,
        Body(),
    ] = None,
) -> GenerateChannelTranscriptCueTasksResponse:
    return await use_case.execute(
        channel_id,
        request or GenerateTranscriptCueTasksRequest(),
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
