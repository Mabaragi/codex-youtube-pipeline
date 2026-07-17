from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

JsonObject = dict[str, object]


class WorkItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    BLOCKED = "blocked"
    CANCELED = "canceled"


class WorkAttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELED = "canceled"


class WorkExecutionMode(StrEnum):
    INLINE = "inline"
    WORKER = "worker"


class WorkBatchStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELED = "canceled"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELED = "canceled"


@dataclass(frozen=True, slots=True)
class WorkItem:
    id: int
    task_type: str
    subject_type: str
    subject_id: int | None
    external_key: str | None
    task_version: str
    input_hash: str
    idempotency_key: str
    execution_mode: WorkExecutionMode
    status: WorkItemStatus
    outcome_code: str | None
    priority: int
    timeout_seconds: int
    input_json: JsonObject
    output_json: JsonObject | None
    output_transcript_id: int | None
    error_code: str | None
    error_type: str | None
    error_message: str | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    available_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkAttempt:
    id: int
    work_item_id: int
    attempt_no: int
    status: WorkAttemptStatus
    worker_id: str | None
    started_at: datetime
    finished_at: datetime | None
    output_json: JsonObject | None
    error_code: str | None
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class WorkBatch:
    id: int
    operation_type: str
    status: WorkBatchStatus
    actor_type: str
    selection_json: JsonObject
    options_json: JsonObject
    requested_count: int
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkBatchItem:
    id: int
    batch_id: int
    position: int
    video_id: int | None
    work_item_id: int | None
    workflow_run_id: int | None
    selection_status: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    id: int
    workflow_type: str
    workflow_version: str
    video_id: int
    input_hash: str
    status: WorkflowStatus
    current_stage: str | None
    options_json: JsonObject
    output_json: JsonObject | None
    error_code: str | None
    error_message: str | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    id: int
    workflow_run_id: int
    stage_name: str
    position: int
    work_item_id: int | None
    status: str
    created_at: datetime
    completed_at: datetime | None


TERMINAL_WORK_ITEM_STATUSES = frozenset(
    {
        WorkItemStatus.SUCCEEDED,
        WorkItemStatus.FAILED,
        WorkItemStatus.TIMED_OUT,
        WorkItemStatus.BLOCKED,
        WorkItemStatus.CANCELED,
    }
)


def dependency_is_satisfied(item: WorkItem, *, requires_successful_output: bool) -> bool:
    if item.status is not WorkItemStatus.SUCCEEDED:
        return False
    return not requires_successful_output or item.outcome_code is None
