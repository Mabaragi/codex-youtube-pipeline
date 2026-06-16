from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

JsonObject = dict[str, object]
VideoTaskStatus = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "skipped",
    "canceled",
]


@dataclass(frozen=True, slots=True)
class VideoTaskCreate:
    video_id: int
    task_name: str
    task_version: str
    input_hash: str
    timeout_seconds: int
    status: VideoTaskStatus = "pending"


@dataclass(frozen=True, slots=True)
class VideoTaskRecord:
    id: int
    video_id: int
    task_name: str
    task_version: str
    input_hash: str
    status: VideoTaskStatus
    worker_id: str | None
    timeout_seconds: int
    job_id: int | None
    job_attempt_id: int | None
    output_transcript_id: int | None
    output_json: JsonObject | None
    error_type: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class VideoTaskListRecord:
    task: VideoTaskRecord
    youtube_video_id: str


@dataclass(frozen=True, slots=True)
class VideoTaskListQuery:
    channel_id: int
    task_name: str | None = None
    status: VideoTaskStatus | None = None
    limit: int = 50
    offset: int = 0


class VideoTaskRepositoryPort(Protocol):
    async def get_task(self, task_id: int) -> VideoTaskRecord | None:
        """Return one video task by internal ID."""

    async def get_task_for_input(
        self,
        *,
        video_id: int,
        task_name: str,
        task_version: str,
        input_hash: str,
    ) -> VideoTaskRecord | None:
        """Return one task matching the idempotency key."""

    async def get_or_create_task(self, task: VideoTaskCreate) -> VideoTaskRecord:
        """Return an existing matching task or create one."""

    async def list_tasks(self, query: VideoTaskListQuery) -> list[VideoTaskListRecord]:
        """List video tasks for a channel."""

    async def count_running(self, *, task_name: str) -> int:
        """Count currently running tasks by type."""

    async def mark_task_running(
        self,
        task_id: int,
        *,
        worker_id: str,
        timeout_seconds: int,
        job_id: int,
        job_attempt_id: int,
    ) -> VideoTaskRecord:
        """Mark a task as running and attach execution IDs."""

    async def mark_task_succeeded(
        self,
        task_id: int,
        *,
        output_transcript_id: int | None,
        output_json: JsonObject,
    ) -> VideoTaskRecord:
        """Mark a task as succeeded."""

    async def mark_task_failed(
        self,
        task_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        """Mark a task as failed."""

    async def mark_task_timed_out(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        """Mark a task as timed out."""
