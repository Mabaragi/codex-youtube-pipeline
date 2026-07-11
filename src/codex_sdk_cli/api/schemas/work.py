from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from codex_sdk_cli.application.work.queries import WorkItemDetail, WorkItemListResult
from codex_sdk_cli.domains.work.models import JsonObject, WorkAttempt, WorkItem


class WorkAttemptResponse(BaseModel):
    id: int
    work_item_id: int = Field(alias="workItemId")
    attempt_no: int = Field(alias="attemptNo")
    status: str
    worker_id: str | None = Field(alias="workerId")
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    output: JsonObject | None
    error_code: str | None = Field(alias="errorCode")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class WorkItemResponse(BaseModel):
    id: int
    task_type: str = Field(alias="taskType")
    subject_type: str = Field(alias="subjectType")
    subject_id: int | None = Field(alias="subjectId")
    external_key: str | None = Field(alias="externalKey")
    task_version: str = Field(alias="taskVersion")
    input_hash: str = Field(alias="inputHash")
    execution_mode: str = Field(alias="executionMode")
    status: str
    outcome_code: str | None = Field(alias="outcomeCode")
    priority: int
    timeout_seconds: int = Field(alias="timeoutSeconds")
    input: JsonObject
    output: JsonObject | None
    output_transcript_id: int | None = Field(alias="outputTranscriptId")
    error_code: str | None = Field(alias="errorCode")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")
    lease_owner: str | None = Field(alias="leaseOwner")
    lease_expires_at: datetime | None = Field(alias="leaseExpiresAt")
    available_at: datetime = Field(alias="availableAt")
    started_at: datetime | None = Field(alias="startedAt")
    completed_at: datetime | None = Field(alias="completedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class WorkItemDetailResponse(WorkItemResponse):
    attempts: tuple[WorkAttemptResponse, ...]


class WorkItemListResponse(BaseModel):
    items: tuple[WorkItemResponse, ...]
    next_cursor: int | None = Field(alias="nextCursor")

    model_config = ConfigDict(populate_by_name=True)


class RetryWorkItemRequest(BaseModel):
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CancelWorkItemRequest(BaseModel):
    reason: str = Field(default="Canceled by operator.", min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid")


def work_item_response(item: WorkItem) -> WorkItemResponse:
    return WorkItemResponse(
        id=item.id,
        taskType=item.task_type,
        subjectType=item.subject_type,
        subjectId=item.subject_id,
        externalKey=item.external_key,
        taskVersion=item.task_version,
        inputHash=item.input_hash,
        executionMode=item.execution_mode.value,
        status=item.status.value,
        outcomeCode=item.outcome_code,
        priority=item.priority,
        timeoutSeconds=item.timeout_seconds,
        input=item.input_json,
        output=item.output_json,
        outputTranscriptId=item.output_transcript_id,
        errorCode=item.error_code,
        errorType=item.error_type,
        errorMessage=item.error_message,
        leaseOwner=item.lease_owner,
        leaseExpiresAt=item.lease_expires_at,
        availableAt=item.available_at,
        startedAt=item.started_at,
        completedAt=item.completed_at,
        createdAt=item.created_at,
        updatedAt=item.updated_at,
    )


def work_item_list_response(result: WorkItemListResult) -> WorkItemListResponse:
    return WorkItemListResponse(
        items=tuple(work_item_response(item) for item in result.items),
        nextCursor=result.next_cursor,
    )


def work_item_detail_response(result: WorkItemDetail) -> WorkItemDetailResponse:
    item = work_item_response(result.item)
    return WorkItemDetailResponse(
        **item.model_dump(),
        attempts=tuple(_attempt_response(attempt) for attempt in result.attempts),
    )


def _attempt_response(attempt: WorkAttempt) -> WorkAttemptResponse:
    return WorkAttemptResponse(
        id=attempt.id,
        workItemId=attempt.work_item_id,
        attemptNo=attempt.attempt_no,
        status=attempt.status.value,
        workerId=attempt.worker_id,
        startedAt=attempt.started_at,
        finishedAt=attempt.finished_at,
        output=attempt.output_json,
        errorCode=attempt.error_code,
        errorType=attempt.error_type,
        errorMessage=attempt.error_message,
    )
