from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from codex_sdk_cli.api.use_case_dependencies.micro_events import ExtractVideoMicroEventsUseCaseDep
from codex_sdk_cli.domains.micro_events.schemas import MicroEventExtractionDetailResponse

router = APIRouter()


@router.get(
    "/ops/videos/{video_id}/micro-events/latest",
    response_model=MicroEventExtractionDetailResponse,
)
async def get_latest_video_micro_event_extraction(
    video_id: Annotated[int, Path(ge=1)],
    use_case: ExtractVideoMicroEventsUseCaseDep,
) -> MicroEventExtractionDetailResponse:
    return await use_case.get_latest(video_id)


@router.get(
    "/ops/videos/{video_id}/micro-events/{result_id}",
    response_model=MicroEventExtractionDetailResponse,
)
async def get_video_micro_event_extraction(
    video_id: Annotated[int, Path(ge=1)],
    result_id: Annotated[int, Path(ge=1)],
    use_case: ExtractVideoMicroEventsUseCaseDep,
) -> MicroEventExtractionDetailResponse:
    return await use_case.get_detail(video_id=video_id, video_task_id=result_id)
