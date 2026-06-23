from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Path, status

from .dependencies import ExtractVideoMicroEventsUseCaseDep
from .schemas import (
    MicroEventBatchExtractRequest,
    MicroEventBatchExtractResponse,
    MicroEventEnqueueRequest,
    MicroEventEnqueueResponse,
    MicroEventExtractionDetailResponse,
    MicroEventExtractRequest,
    MicroEventExtractResponse,
)

router = APIRouter()


@router.post(
    "/videos/{video_id}/video-tasks/micro-event-extract",
    response_model=MicroEventExtractResponse,
    status_code=status.HTTP_201_CREATED,
)
async def extract_video_micro_events(
    video_id: Annotated[int, Path(ge=1)],
    use_case: ExtractVideoMicroEventsUseCaseDep,
    request: Annotated[MicroEventExtractRequest | None, Body()] = None,
) -> MicroEventExtractResponse:
    return await use_case.execute(video_id, request or MicroEventExtractRequest())


@router.post(
    "/video-tasks/micro-event-extract",
    response_model=MicroEventBatchExtractResponse,
    status_code=status.HTTP_201_CREATED,
)
async def extract_all_video_micro_events(
    use_case: ExtractVideoMicroEventsUseCaseDep,
    request: Annotated[MicroEventBatchExtractRequest | None, Body()] = None,
) -> MicroEventBatchExtractResponse:
    return await use_case.execute_all(request or MicroEventBatchExtractRequest())


@router.post(
    "/video-tasks/micro-event-extract/enqueue",
    response_model=MicroEventEnqueueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def enqueue_video_micro_events(
    use_case: ExtractVideoMicroEventsUseCaseDep,
    request: Annotated[MicroEventEnqueueRequest | None, Body()] = None,
) -> MicroEventEnqueueResponse:
    return await use_case.enqueue(request or MicroEventEnqueueRequest())


@router.get(
    "/videos/{video_id}/micro-event-extractions/latest",
    response_model=MicroEventExtractionDetailResponse,
)
async def get_latest_video_micro_event_extraction(
    video_id: Annotated[int, Path(ge=1)],
    use_case: ExtractVideoMicroEventsUseCaseDep,
) -> MicroEventExtractionDetailResponse:
    return await use_case.get_latest(video_id)


@router.get(
    "/videos/{video_id}/micro-event-extractions/{video_task_id}",
    response_model=MicroEventExtractionDetailResponse,
)
async def get_video_micro_event_extraction(
    video_id: Annotated[int, Path(ge=1)],
    video_task_id: Annotated[int, Path(ge=1)],
    use_case: ExtractVideoMicroEventsUseCaseDep,
) -> MicroEventExtractionDetailResponse:
    return await use_case.get_detail(video_id=video_id, video_task_id=video_task_id)
