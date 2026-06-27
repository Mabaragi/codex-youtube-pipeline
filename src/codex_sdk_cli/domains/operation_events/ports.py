"""Ports and DTOs for operation event timelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

JsonObject = dict[str, object]
OperationEventSeverity = Literal["info", "warning", "error"]
OperationEventActorType = Literal["manual_api", "retry_executor", "system"]


@dataclass(frozen=True, slots=True)
class OperationEventCreate:
    event_type: str
    severity: OperationEventSeverity
    message: str
    actor_type: OperationEventActorType
    source: str
    metadata_json: JsonObject = field(default_factory=dict)
    job_id: int | None = None
    job_attempt_id: int | None = None
    video_task_id: int | None = None
    channel_id: int | None = None
    video_id: int | None = None
    external_api_call_id: int | None = None
    subject_type: str | None = None
    subject_id: int | None = None
    external_key: str | None = None
    correlation_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class OperationEventRecord:
    id: int
    occurred_at: datetime
    event_type: str
    severity: OperationEventSeverity
    message: str
    actor_type: OperationEventActorType
    source: str
    metadata_json: JsonObject
    job_id: int | None
    job_attempt_id: int | None
    video_task_id: int | None
    channel_id: int | None
    video_id: int | None
    external_api_call_id: int | None
    subject_type: str | None
    subject_id: int | None
    external_key: str | None
    correlation_id: str | None
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class OperationEventListQuery:
    limit: int
    severity: OperationEventSeverity | None = None
    event_type: str | None = None
    subject_type: str | None = None
    subject_id: int | None = None
    job_id: int | None = None
    video_task_id: int | None = None
    channel_id: int | None = None
    video_id: int | None = None
    cursor: int | None = None


class OperationEventRepositoryPort(Protocol):
    async def create_event(self, event: OperationEventCreate) -> OperationEventRecord:
        """Persist an operation event."""

    async def list_events(self, query: OperationEventListQuery) -> list[OperationEventRecord]:
        """List operation events newest first."""


class OperationEventRecorderPort(Protocol):
    async def record_event(self, event: OperationEventCreate) -> None:
        """Record an operation event without changing the caller outcome."""

