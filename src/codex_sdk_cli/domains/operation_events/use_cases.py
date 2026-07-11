"""Use cases for operation event timelines."""

from __future__ import annotations

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventListQuery,
    OperationEventRepositoryPort,
    OperationEventSeverity,
)
from codex_sdk_cli.domains.operation_events.schemas import (
    OperationEventListResponse,
    OperationEventResponse,
)


class ListOperationEventsUseCase:
    def __init__(self, repository: OperationEventRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        limit: int,
        severity: OperationEventSeverity | None = None,
        event_type: str | None = None,
        subject_type: str | None = None,
        subject_id: int | None = None,
        job_id: int | None = None,
        video_task_id: int | None = None,
        work_item_id: int | None = None,
        work_attempt_id: int | None = None,
        work_batch_id: int | None = None,
        channel_id: int | None = None,
        video_id: int | None = None,
        cursor: int | None = None,
    ) -> OperationEventListResponse:
        records = await self._repository.list_events(
            OperationEventListQuery(
                limit=limit + 1,
                severity=severity,
                event_type=event_type,
                subject_type=subject_type,
                subject_id=subject_id,
                job_id=job_id,
                video_task_id=video_task_id,
                work_item_id=work_item_id,
                work_attempt_id=work_attempt_id,
                work_batch_id=work_batch_id,
                channel_id=channel_id,
                video_id=video_id,
                cursor=cursor,
            )
        )
        visible_records = records[:limit]
        next_cursor = visible_records[-1].id if len(records) > limit and visible_records else None
        return OperationEventListResponse(
            items=[_event_response(record) for record in visible_records],
            next_cursor=next_cursor,
        )


def _event_response(record) -> OperationEventResponse:
    return OperationEventResponse(
        eventId=record.id,
        occurredAt=record.occurred_at,
        eventType=record.event_type,
        severity=record.severity,
        message=record.message,
        actorType=record.actor_type,
        source=record.source,
        jobId=record.job_id,
        jobAttemptId=record.job_attempt_id,
        videoTaskId=record.video_task_id,
        workItemId=record.work_item_id,
        workAttemptId=record.work_attempt_id,
        workBatchId=record.work_batch_id,
        channelId=record.channel_id,
        videoId=record.video_id,
        externalApiCallId=record.external_api_call_id,
        subjectType=record.subject_type,
        subjectId=record.subject_id,
        externalKey=record.external_key,
        correlationId=record.correlation_id,
        errorType=record.error_type,
        errorMessage=record.error_message,
        metadata=record.metadata_json,
    )
