from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

OpsFailureKind = Literal["pipeline_job", "video_task"]


@dataclass(frozen=True)
class OpsStatusCountRecord:
    status: str
    count: int


@dataclass(frozen=True)
class OpsSummaryCountsRecord:
    streamers: int
    channels: int
    videos: int
    transcripts: int
    video_tasks: tuple[OpsStatusCountRecord, ...]
    pipeline_jobs: tuple[OpsStatusCountRecord, ...]


@dataclass(frozen=True)
class OpsRecentFailureRecord:
    kind: OpsFailureKind
    id: int
    status: str
    label: str
    error_type: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OpsChannelRecord:
    channel_id: int
    streamer_id: int
    streamer_name: str
    handle: str
    name: str
    youtube_channel_id: str | None
    uploads_playlist_id: str | None
    video_count: int
    transcript_succeeded_count: int
    task_failed_count: int
    task_running_count: int
    latest_video_published_at: datetime | None
    latest_task_updated_at: datetime | None


@dataclass(frozen=True)
class OpsVideoListQuery:
    channel_id: int | None
    task_status: str | None
    search: str | None
    limit: int
    offset: int


@dataclass(frozen=True)
class OpsVideoRecord:
    video_id: int
    channel_id: int
    channel_name: str
    youtube_video_id: str
    title: str
    published_at: datetime
    duration: str | None
    thumbnail_url: str | None
    latest_task_id: int | None
    latest_task_name: str | None
    latest_task_status: str | None
    latest_task_updated_at: datetime | None
    transcript_id: int | None


@dataclass(frozen=True)
class OpsVideoListResult:
    items: tuple[OpsVideoRecord, ...]
    total: int


@dataclass(frozen=True)
class OpsVideoTaskListQuery:
    channel_id: int | None
    task_name: str | None
    status: str | None
    limit: int
    offset: int


@dataclass(frozen=True)
class OpsVideoTaskRecord:
    video_task_id: int
    video_id: int
    channel_id: int
    channel_name: str
    youtube_video_id: str
    task_name: str
    task_version: str
    status: str
    worker_id: str | None
    timeout_seconds: int
    job_id: int | None
    job_attempt_id: int | None
    output_transcript_id: int | None
    error_type: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OpsVideoTaskListResult:
    items: tuple[OpsVideoTaskRecord, ...]
    total: int


class OpsRepositoryPort(Protocol):
    async def get_summary_counts(self) -> OpsSummaryCountsRecord:
        ...

    async def list_recent_failures(self, *, limit: int) -> list[OpsRecentFailureRecord]:
        ...

    async def list_channels(self) -> list[OpsChannelRecord]:
        ...

    async def list_videos(self, query: OpsVideoListQuery) -> OpsVideoListResult:
        ...

    async def list_video_tasks(
        self,
        query: OpsVideoTaskListQuery,
    ) -> OpsVideoTaskListResult:
        ...
