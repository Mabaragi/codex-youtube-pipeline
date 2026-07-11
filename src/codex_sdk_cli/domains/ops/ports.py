from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
)

OpsFailureKind = Literal["pipeline_job", "video_task"]
OpsCandidateCategory = Literal[
    "readyNoHistory",
    "retryableCanceled",
    "failed",
    "active",
    "blocked",
]
OpsEmbedStatusFilter = Literal["embeddable", "no_embed", "unknown"]
OpsSchemaRelationKind = Literal[
    "one_to_many",
    "one_to_one",
    "optional_one_to_many",
    "optional_one_to_one",
]


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


class OpsPendingWorkCancelerPort(Protocol):
    async def execute(
        self,
        *,
        subject_type: str,
        subject_id: int,
        task_types: tuple[str, ...],
        outcome_code: str,
        reason: str,
    ) -> int: ...


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
    task_no_transcript_count: int
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
    embed_status: OpsEmbedStatusFilter | None = None


@dataclass(frozen=True)
class OpsVideoCueGenerationRecord:
    generated: bool
    transcript_id: int | None
    cue_count: int
    latest_task_id: int | None
    latest_task_status: str | None
    latest_task_updated_at: datetime | None


@dataclass(frozen=True)
class OpsVideoMicroEventGenerationRecord:
    generated: bool
    video_task_id: int | None
    window_count: int
    micro_event_count: int
    latest_task_id: int | None
    latest_task_status: str | None
    latest_task_updated_at: datetime | None


@dataclass(frozen=True)
class OpsVideoTimelineGenerationRecord:
    generated: bool
    composition_id: int | None
    video_task_id: int | None
    episode_count: int
    latest_task_id: int | None
    latest_task_status: str | None
    latest_task_updated_at: datetime | None


@dataclass(frozen=True)
class OpsVideoGenerationRecord:
    cues: OpsVideoCueGenerationRecord
    micro_events: OpsVideoMicroEventGenerationRecord
    timeline: OpsVideoTimelineGenerationRecord


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
    generation: OpsVideoGenerationRecord
    is_embeddable: bool | None = None
    embed_status_checked_at: datetime | None = None


@dataclass(frozen=True)
class OpsVideoDetailRecord:
    video_id: int
    channel_id: int
    channel_name: str
    youtube_video_id: str
    title: str
    description: str
    published_at: datetime
    duration: str | None
    thumbnail_url: str | None
    source_listing_api_call_id: int | None
    source_details_api_call_id: int | None
    source_job_id: int | None
    created_at: datetime
    updated_at: datetime
    latest_task_id: int | None
    latest_task_name: str | None
    latest_task_status: str | None
    latest_task_updated_at: datetime | None
    transcript_id: int | None
    tasks: tuple[OpsVideoTaskRecord, ...]
    transcripts: tuple[YouTubeTranscriptMetadataRecord, ...]
    is_embeddable: bool | None = None
    embed_status_checked_at: datetime | None = None
    source_embed_status_api_call_id: int | None = None


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
    output_json: JsonObject | None
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


@dataclass(frozen=True)
class OpsCandidateListQuery:
    channel_id: int | None
    search: str | None
    category: OpsCandidateCategory | None
    limit: int
    offset: int


@dataclass(frozen=True)
class OpsTaskSummaryRecord:
    video_task_id: int
    status: str
    worker_id: str | None
    job_id: int | None
    job_attempt_id: int | None
    error_type: str | None
    error_message: str | None
    updated_at: datetime


@dataclass(frozen=True)
class OpsMicroEventReadyCandidateRecord:
    video_id: int
    channel_id: int
    channel_name: str
    youtube_video_id: str
    title: str
    published_at: datetime
    transcript_id: int | None
    cue_count: int
    latest_cue_task: OpsTaskSummaryRecord | None
    latest_micro_task: OpsTaskSummaryRecord | None
    category: OpsCandidateCategory
    recommended_retry_failed: bool


@dataclass(frozen=True)
class OpsMicroEventReadyCandidateListResult:
    items: tuple[OpsMicroEventReadyCandidateRecord, ...]
    total: int


@dataclass(frozen=True)
class OpsTimelineReadyCandidateRecord:
    video_id: int
    channel_id: int
    channel_name: str
    youtube_video_id: str
    title: str
    published_at: datetime
    source_micro_event_task_id: int
    micro_event_count: int
    window_count: int
    latest_timeline_task: OpsTaskSummaryRecord | None
    category: OpsCandidateCategory
    recommended_retry_failed: bool


@dataclass(frozen=True)
class OpsTimelineReadyCandidateListResult:
    items: tuple[OpsTimelineReadyCandidateRecord, ...]
    total: int


@dataclass(frozen=True)
class OpsLatestEventRecord:
    operation_event_id: int
    occurred_at: datetime
    event_type: str
    severity: str
    message: str
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class OpsStuckTaskQuery:
    task_name: str
    older_than: datetime


@dataclass(frozen=True)
class OpsStuckTaskRecord:
    video_task_id: int
    video_id: int
    channel_id: int
    channel_name: str
    youtube_video_id: str
    title: str
    task_name: str
    status: str
    worker_id: str | None
    worker_pid: int | None
    job_id: int | None
    job_attempt_id: int | None
    job_attempt_status: str | None
    started_at: datetime | None
    updated_at: datetime
    stale_since: datetime
    latest_event: OpsLatestEventRecord | None
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class OpsStuckTaskListResult:
    items: tuple[OpsStuckTaskRecord, ...]
    total: int


@dataclass(frozen=True)
class OpsSchemaColumnRecord:
    id: str
    name: str
    type: str
    nullable: bool
    primary_key: bool
    unique: bool
    index: bool
    default: str | None
    foreign_keys: tuple[str, ...]
    constraint_names: tuple[str, ...]


@dataclass(frozen=True)
class OpsSchemaIndexRecord:
    name: str
    column_names: tuple[str, ...]
    unique: bool


@dataclass(frozen=True)
class OpsSchemaUniqueConstraintRecord:
    name: str
    column_names: tuple[str, ...]


@dataclass(frozen=True)
class OpsSchemaForeignKeyConstraintRecord:
    name: str
    column_names: tuple[str, ...]
    target_table: str
    target_column_names: tuple[str, ...]


@dataclass(frozen=True)
class OpsSchemaTableRecord:
    id: str
    name: str
    columns: tuple[OpsSchemaColumnRecord, ...]
    indexes: tuple[OpsSchemaIndexRecord, ...]
    unique_constraints: tuple[OpsSchemaUniqueConstraintRecord, ...]
    foreign_key_constraints: tuple[OpsSchemaForeignKeyConstraintRecord, ...]


@dataclass(frozen=True)
class OpsSchemaRelationRecord:
    id: str
    constraint_name: str
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    source_nullable: bool
    target_primary_key: bool
    relation_kind: OpsSchemaRelationKind


@dataclass(frozen=True)
class OpsSchemaGraphRecord:
    tables: tuple[OpsSchemaTableRecord, ...]
    relations: tuple[OpsSchemaRelationRecord, ...]


class OpsRepositoryPort(Protocol):
    async def get_summary_counts(self) -> OpsSummaryCountsRecord:
        ...

    async def list_recent_failures(self, *, limit: int) -> list[OpsRecentFailureRecord]:
        ...

    async def list_channels(self) -> list[OpsChannelRecord]:
        ...

    async def list_videos(self, query: OpsVideoListQuery) -> OpsVideoListResult:
        ...

    async def get_video_detail(self, video_id: int) -> OpsVideoDetailRecord | None:
        ...

    async def list_video_tasks(
        self,
        query: OpsVideoTaskListQuery,
    ) -> OpsVideoTaskListResult:
        ...

    async def list_micro_event_ready_candidates(
        self,
        query: OpsCandidateListQuery,
    ) -> OpsMicroEventReadyCandidateListResult:
        ...

    async def list_timeline_ready_candidates(
        self,
        query: OpsCandidateListQuery,
    ) -> OpsTimelineReadyCandidateListResult:
        ...

    async def detect_stuck_tasks(
        self,
        query: OpsStuckTaskQuery,
    ) -> OpsStuckTaskListResult:
        ...

    async def get_schema_graph(self) -> OpsSchemaGraphRecord:
        ...
