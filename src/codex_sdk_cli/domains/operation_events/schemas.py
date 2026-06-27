"""API schemas for operation events."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from codex_sdk_cli.domains.operation_events.ports import (
    JsonObject,
    OperationEventActorType,
    OperationEventSeverity,
)


class OperationEventResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: int = Field(alias="eventId")
    occurred_at: datetime = Field(alias="occurredAt")
    event_type: str = Field(alias="eventType")
    severity: OperationEventSeverity
    message: str
    actor_type: OperationEventActorType = Field(alias="actorType")
    source: str
    job_id: int | None = Field(default=None, alias="jobId")
    job_attempt_id: int | None = Field(default=None, alias="jobAttemptId")
    video_task_id: int | None = Field(default=None, alias="videoTaskId")
    channel_id: int | None = Field(default=None, alias="channelId")
    video_id: int | None = Field(default=None, alias="videoId")
    external_api_call_id: int | None = Field(default=None, alias="externalApiCallId")
    subject_type: str | None = Field(default=None, alias="subjectType")
    subject_id: int | None = Field(default=None, alias="subjectId")
    external_key: str | None = Field(default=None, alias="externalKey")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    error_type: str | None = Field(default=None, alias="errorType")
    error_message: str | None = Field(default=None, alias="errorMessage")
    metadata_json: JsonObject = Field(alias="metadata")


class OperationEventListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[OperationEventResponse]
    next_cursor: int | None = Field(default=None, alias="nextCursor")

