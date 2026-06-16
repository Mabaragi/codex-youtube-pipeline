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


@dataclass(frozen=True, slots=True)
class PipelineJobListQuery:
    step: str | None = None
    status: PipelineJobStatus | None = None
    subject_type: str | None = None
    subject_id: int | None = None
    external_key: str | None = None
    cursor: int | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class PipelineJobSummaryRecord:
    job: PipelineJobRecord
    latest_attempt_id: int | None
    latest_attempt_status: PipelineJobAttemptStatus | None
    attempt_count: int


@dataclass(frozen=True, slots=True)
class ExternalApiCallSummaryRecord:
    id: int
    pipeline_job_attempt_id: int | None
    provider: str
    operation: str
    response_status_code: int | None
    validation_status: str
    response_storage_uri: str | None
    duration_ms: int
    quota_cost: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PipelineChannelOutputRecord:
    id: int
    streamer_id: int
    handle: str
    name: str
    youtube_channel_id: str | None
    source_api_call_id: int | None
    source_job_id: int | None


@dataclass(frozen=True, slots=True)
class PipelineVideoOutputRecord:
    id: int
    channel_id: int
    youtube_video_id: str
    title: str
    published_at: datetime
    source_search_api_call_id: int | None
    source_details_api_call_id: int | None
    source_job_id: int | None


@dataclass(frozen=True, slots=True)
class PipelineJobDetailRecord:
    job: PipelineJobRecord
    attempts: list[PipelineJobAttemptRecord]
    external_api_calls: list[ExternalApiCallSummaryRecord]
    channels: list[PipelineChannelOutputRecord]
    videos: list[PipelineVideoOutputRecord]


class PipelineJobRepositoryPort(Protocol):
    async def create_job(self, job: PipelineJobCreate) -> PipelineJobRecord:
        """Create one logical pipeline job."""

    async def get_job(self, job_id: int) -> PipelineJobRecord | None:
        """Return one logical pipeline job by internal ID."""

    async def list_job_summaries(
        self,
        query: PipelineJobListQuery,
    ) -> list[PipelineJobSummaryRecord]:
        """List pipeline jobs with operational summary fields."""

    async def get_job_detail(self, job_id: int) -> PipelineJobDetailRecord | None:
        """Return one pipeline job with attempts and linked outputs."""

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

    async def mark_job_running(self, job_id: int) -> PipelineJobRecord:
        """Mark one job as running."""
