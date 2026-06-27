"""Operation event API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from codex_sdk_cli.api.use_case_dependencies.operation_events import (
    ListOperationEventsUseCaseDep,
)
from codex_sdk_cli.domains.operation_events.ports import OperationEventSeverity
from codex_sdk_cli.domains.operation_events.schemas import OperationEventListResponse

router = APIRouter()


@router.get("/events", response_model=OperationEventListResponse)
async def list_operation_events(
    use_case: ListOperationEventsUseCaseDep,
    severity: Annotated[OperationEventSeverity | None, Query()] = None,
    event_type: Annotated[str | None, Query(alias="eventType", max_length=128)] = None,
    subject_type: Annotated[str | None, Query(alias="subjectType", max_length=64)] = None,
    subject_id: Annotated[int | None, Query(alias="subjectId", ge=1)] = None,
    job_id: Annotated[int | None, Query(alias="jobId", ge=1)] = None,
    video_task_id: Annotated[int | None, Query(alias="videoTaskId", ge=1)] = None,
    channel_id: Annotated[int | None, Query(alias="channelId", ge=1)] = None,
    video_id: Annotated[int | None, Query(alias="videoId", ge=1)] = None,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> OperationEventListResponse:
    return await use_case.execute(
        limit=limit,
        severity=severity,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        job_id=job_id,
        video_task_id=video_task_id,
        channel_id=channel_id,
        video_id=video_id,
        cursor=cursor,
    )

