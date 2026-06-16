from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

JsonObject = dict[str, object]
PipelineJobStatus = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "canceled",
]
PipelineJobAttemptStatus = Literal["running", "succeeded", "failed", "canceled"]


@dataclass(frozen=True, slots=True)
class PipelineJobCreate:
    step: str
    status: PipelineJobStatus
    subject_type: str | None
    subject_id: int | None
    external_key: str | None
    input_json: JsonObject
    input_hash: str
    parent_job_id: int | None = None


@dataclass(frozen=True, slots=True)
class PipelineJobRecord:
    id: int
    step: str
    status: PipelineJobStatus
    subject_type: str | None
    subject_id: int | None
    external_key: str | None
    input_json: JsonObject
    input_hash: str
    parent_job_id: int | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PipelineJobAttemptRecord:
    id: int
    job_id: int
    attempt_no: int
    status: PipelineJobAttemptStatus
    started_at: datetime
    finished_at: datetime | None
    worker_id: str | None
    error_type: str | None
    error_message: str | None
    output_json: JsonObject | None


class PipelineJobRepositoryPort(Protocol):
    async def create_job(self, job: PipelineJobCreate) -> PipelineJobRecord:
        """Create one logical pipeline job."""

    async def create_attempt(
        self,
        *,
        job_id: int,
        worker_id: str | None = None,
    ) -> PipelineJobAttemptRecord:
        """Create one running attempt for a job."""

    async def mark_attempt_succeeded(
        self,
        attempt_id: int,
        *,
        output_json: JsonObject,
    ) -> PipelineJobAttemptRecord:
        """Mark one attempt as succeeded."""

    async def mark_attempt_failed(
        self,
        attempt_id: int,
        *,
        error_type: str,
        error_message: str,
    ) -> PipelineJobAttemptRecord:
        """Mark one attempt as failed."""

    async def mark_job_succeeded(self, job_id: int) -> PipelineJobRecord:
        """Mark one job as succeeded."""

    async def mark_job_failed(self, job_id: int) -> PipelineJobRecord:
        """Mark one job as failed."""
