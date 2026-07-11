from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from codex_sdk_cli.application.unit_of_work import UnitOfWorkPort
from codex_sdk_cli.domains.work.models import (
    JsonObject,
    WorkAttempt,
    WorkBatch,
    WorkBatchItem,
    WorkExecutionMode,
    WorkflowRun,
    WorkflowStep,
    WorkItem,
    WorkItemStatus,
)


@dataclass(frozen=True, slots=True)
class CreateWorkItem:
    task_type: str
    subject_type: str
    subject_id: int | None
    external_key: str | None
    task_version: str
    input_hash: str
    idempotency_key: str
    execution_mode: WorkExecutionMode
    timeout_seconds: int
    input_json: JsonObject
    priority: int = 0
    available_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class WorkItemQuery:
    task_type: str | None = None
    status: WorkItemStatus | None = None
    subject_type: str | None = None
    subject_id: int | None = None
    cursor: int | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class CreateWorkBatch:
    operation_type: str
    actor_type: str
    selection_json: JsonObject
    options_json: JsonObject
    requested_count: int


@dataclass(frozen=True, slots=True)
class CreateWorkflowRun:
    workflow_type: str
    workflow_version: str
    video_id: int
    input_hash: str
    options_json: JsonObject


class WorkItemRepositoryPort(Protocol):
    async def get(self, work_item_id: int) -> WorkItem | None: ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> WorkItem | None: ...

    async def get_or_create(self, create: CreateWorkItem) -> tuple[WorkItem, bool]: ...

    async def list_items(self, query: WorkItemQuery) -> list[WorkItem]: ...

    async def find_latest(
        self,
        *,
        task_type: str,
        subject_type: str,
        subject_id: int,
        status: WorkItemStatus | None = None,
    ) -> WorkItem | None: ...

    async def list_outcome_due(
        self,
        *,
        task_type: str,
        outcome_code: str,
        completed_before: datetime,
        limit: int,
    ) -> list[WorkItem]: ...

    async def add_dependency(
        self,
        *,
        work_item_id: int,
        dependency_work_item_id: int,
        requires_successful_output: bool = True,
    ) -> None: ...

    async def start_inline(
        self,
        *,
        work_item_id: int,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> WorkItem | None: ...

    async def claim_next(
        self,
        *,
        task_types: tuple[str, ...],
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> WorkItem | None: ...

    async def heartbeat(
        self,
        *,
        work_item_id: int,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...

    async def mark_succeeded(
        self,
        *,
        work_item_id: int,
        now: datetime,
        output_json: JsonObject,
        output_transcript_id: int | None = None,
        outcome_code: str | None = None,
    ) -> WorkItem: ...

    async def mark_failed(
        self,
        *,
        work_item_id: int,
        now: datetime,
        error_code: str,
        error_type: str,
        error_message: str,
        timed_out: bool = False,
        output_json: JsonObject | None = None,
    ) -> WorkItem: ...

    async def reset_for_retry(
        self,
        *,
        work_item_id: int,
        now: datetime,
        allow_succeeded: bool,
    ) -> WorkItem: ...

    async def cancel(self, *, work_item_id: int, now: datetime, reason: str) -> WorkItem: ...

    async def mark_dependency_blocked(self, *, now: datetime) -> int: ...

    async def recover_expired_leases(self, *, now: datetime) -> int: ...


class WorkAttemptRepositoryPort(Protocol):
    async def list_for_work_item(self, work_item_id: int) -> list[WorkAttempt]: ...

    async def create(self, *, work_item_id: int, worker_id: str | None) -> WorkAttempt: ...

    async def mark_succeeded(
        self,
        *,
        attempt_id: int,
        now: datetime,
        output_json: JsonObject,
    ) -> WorkAttempt: ...

    async def mark_failed(
        self,
        *,
        attempt_id: int,
        now: datetime,
        error_code: str,
        error_type: str,
        error_message: str,
        timed_out: bool = False,
        output_json: JsonObject | None = None,
    ) -> WorkAttempt: ...


class WorkBatchRepositoryPort(Protocol):
    async def create(self, create: CreateWorkBatch) -> WorkBatch: ...

    async def get(self, batch_id: int) -> WorkBatch | None: ...

    async def list_items(self, batch_id: int) -> list[WorkBatchItem]: ...

    async def complete(
        self,
        *,
        batch_id: int,
        status: str,
        completed_at: datetime,
    ) -> WorkBatch: ...

    async def add_item(
        self,
        *,
        batch_id: int,
        position: int,
        video_id: int | None,
        work_item_id: int | None,
        workflow_run_id: int | None,
        selection_status: str,
        reason: str | None,
    ) -> None: ...


class WorkflowRepositoryPort(Protocol):
    async def create_or_get(self, create: CreateWorkflowRun) -> tuple[WorkflowRun, bool]: ...

    async def get(self, workflow_run_id: int) -> WorkflowRun | None: ...

    async def list_steps(self, workflow_run_id: int) -> list[WorkflowStep]: ...

    async def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> WorkflowRun | None: ...

    async def heartbeat(
        self,
        *,
        workflow_run_id: int,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...

    async def recover_expired_leases(self, *, now: datetime) -> int: ...

    async def add_step(
        self,
        *,
        workflow_run_id: int,
        stage_name: str,
        position: int,
        work_item_id: int | None,
        status: str,
        completed_at: datetime | None = None,
    ) -> None: ...

    async def set_waiting(
        self,
        *,
        workflow_run_id: int,
        current_stage: str,
        now: datetime,
    ) -> WorkflowRun: ...

    async def mark_succeeded(
        self,
        *,
        workflow_run_id: int,
        output_json: JsonObject,
        now: datetime,
    ) -> WorkflowRun: ...

    async def mark_failed(
        self,
        *,
        workflow_run_id: int,
        error_code: str,
        error_message: str,
        blocked: bool,
        now: datetime,
    ) -> WorkflowRun: ...


class WorkUnitOfWorkPort(UnitOfWorkPort, Protocol):
    work_items: WorkItemRepositoryPort
    work_attempts: WorkAttemptRepositoryPort
    work_batches: WorkBatchRepositoryPort
    workflows: WorkflowRepositoryPort
