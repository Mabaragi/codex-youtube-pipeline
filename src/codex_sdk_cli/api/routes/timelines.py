from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Path, status

from codex_sdk_cli.api.use_case_dependencies.timelines import ComposeTimelineUseCaseDep
from codex_sdk_cli.domains.timelines.schemas import (
    TimelineComposeEnqueueRequest,
    TimelineComposeEnqueueResponse,
    TimelineCompositionResponse,
)

router = APIRouter()


@router.post(
    "/video-tasks/timeline-compose/enqueue",
    response_model=TimelineComposeEnqueueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def enqueue_timeline_compose(
    use_case: ComposeTimelineUseCaseDep,
    request: Annotated[TimelineComposeEnqueueRequest | None, Body()] = None,
) -> TimelineComposeEnqueueResponse:
    return await use_case.enqueue(request or TimelineComposeEnqueueRequest())


@router.get(
    "/videos/{video_id}/timelines/latest",
    response_model=TimelineCompositionResponse,
)
async def get_latest_video_timeline(
    video_id: Annotated[int, Path(ge=1)],
    use_case: ComposeTimelineUseCaseDep,
) -> TimelineCompositionResponse:
    return await use_case.get_latest(video_id)


@router.get(
    "/videos/{video_id}/timelines/{video_task_id}",
    response_model=TimelineCompositionResponse,
)
async def get_video_timeline(
    video_id: Annotated[int, Path(ge=1)],
    video_task_id: Annotated[int, Path(ge=1)],
    use_case: ComposeTimelineUseCaseDep,
) -> TimelineCompositionResponse:
    return await use_case.get_detail(video_id=video_id, video_task_id=video_task_id)
