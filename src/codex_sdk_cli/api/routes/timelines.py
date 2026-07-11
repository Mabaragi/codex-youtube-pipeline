from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from codex_sdk_cli.api.use_case_dependencies.timelines import ComposeTimelineUseCaseDep
from codex_sdk_cli.domains.timelines.schemas import TimelineCompositionResponse

router = APIRouter()


@router.get(
    "/ops/videos/{video_id}/timelines/latest",
    response_model=TimelineCompositionResponse,
)
async def get_latest_video_timeline(
    video_id: Annotated[int, Path(ge=1)],
    use_case: ComposeTimelineUseCaseDep,
) -> TimelineCompositionResponse:
    return await use_case.get_latest(video_id)


@router.get(
    "/ops/videos/{video_id}/timelines/{result_id}",
    response_model=TimelineCompositionResponse,
)
async def get_video_timeline(
    video_id: Annotated[int, Path(ge=1)],
    result_id: Annotated[int, Path(ge=1)],
    use_case: ComposeTimelineUseCaseDep,
) -> TimelineCompositionResponse:
    return await use_case.get_detail(video_id=video_id, video_task_id=result_id)
