from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from codex_sdk_cli.domains.timelines.ports import TimelineCompositionRecord
from codex_sdk_cli.domains.video_tasks.ports import JsonObject, VideoTaskRecord
from codex_sdk_cli.domains.videos.ports import VideoRecord

ArchivePublishTarget = Literal["selected_videos", "current_filters", "next_eligible"]
ArchivePublishStatusFilter = Literal[
    "not_ready",
    "ready",
    "pending",
    "running",
    "failed",
    "published",
]


@dataclass(frozen=True, slots=True)
class ArchiveObjectSaveRequest:
    object_key: str
    payload: bytes
    cache_control: str
    content_type: str = "application/json"


@dataclass(frozen=True, slots=True)
class ArchiveObjectLocation:
    bucket: str
    object_key: str
    public_url: str


class ArchivePublishStoragePort(Protocol):
    async def save_json(self, request: ArchiveObjectSaveRequest) -> ArchiveObjectLocation:
        """Persist one public JSON object."""


@dataclass(frozen=True, slots=True)
class ArchiveVideoArtifactCreate:
    video_id: int
    source_timeline_composition_id: int
    source_timeline_task_id: int
    source_micro_event_task_id: int
    publish_task_id: int
    publish_job_id: int
    environment: str
    variant: str
    schema_version: int
    version: str
    object_key: str
    public_url: str
    sha256: str
    byte_size: int
    block_count: int
    episode_count: int
    topic_cluster_count: int
    review_flag_count: int
    micro_event_count: int


@dataclass(frozen=True, slots=True)
class ArchiveVideoArtifactRecord(ArchiveVideoArtifactCreate):
    id: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ArchiveVideoArtifactWithVideoRecord:
    artifact: ArchiveVideoArtifactRecord
    video: VideoRecord


@dataclass(frozen=True, slots=True)
class ArchiveIndexPublicationCreate:
    environment: str
    schema_version: int
    version: str
    pointer_key: str
    index_key: str
    public_url: str
    sha256: str
    byte_size: int
    video_count: int


@dataclass(frozen=True, slots=True)
class ArchiveIndexPublicationRecord(ArchiveIndexPublicationCreate):
    id: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ArchivePublishCandidateRecord:
    video: VideoRecord
    composition: TimelineCompositionRecord | None
    latest_archive_task: VideoTaskRecord | None = None
    latest_artifact: ArchiveVideoArtifactRecord | None = None


@dataclass(frozen=True, slots=True)
class ArchivePublishCandidateQuery:
    channel_id: int | None
    search: str | None
    environment: str
    variant: str
    schema_version: int
    limit: int


@dataclass(frozen=True, slots=True)
class ArchiveOpsVideoQuery:
    environment: str
    channel_id: int | None
    publish_status: ArchivePublishStatusFilter | None
    search: str | None
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class ArchiveOpsVideoRecord:
    video: VideoRecord
    channel_name: str
    timeline_composition_id: int | None
    timeline_task_id: int | None
    timeline_episode_count: int
    latest_archive_task: VideoTaskRecord | None
    latest_artifact: ArchiveVideoArtifactRecord | None


@dataclass(frozen=True, slots=True)
class ArchiveOpsVideoListResult:
    items: tuple[ArchiveOpsVideoRecord, ...]
    total: int


class ArchivePublishRepositoryPort(Protocol):
    async def get_publish_candidate(
        self,
        *,
        video_id: int,
        environment: str,
        variant: str,
        schema_version: int,
    ) -> ArchivePublishCandidateRecord | None:
        """Return one video with latest timeline and archive state."""

    async def list_publish_candidates(
        self,
        query: ArchivePublishCandidateQuery,
    ) -> list[ArchivePublishCandidateRecord]:
        """Return timeline-ready publish candidates."""

    async def get_artifact_for_source(
        self,
        *,
        video_id: int,
        environment: str,
        variant: str,
        schema_version: int,
        source_timeline_task_id: int,
    ) -> ArchiveVideoArtifactRecord | None:
        """Return an artifact generated from the same source timeline task."""

    async def create_video_artifact(
        self,
        create: ArchiveVideoArtifactCreate,
    ) -> ArchiveVideoArtifactRecord:
        """Persist one per-video archive artifact."""

    async def list_latest_video_artifacts(
        self,
        *,
        environment: str,
        schema_version: int,
    ) -> list[ArchiveVideoArtifactWithVideoRecord]:
        """List latest artifact per video and variant for index generation."""

    async def create_index_publication(
        self,
        create: ArchiveIndexPublicationCreate,
    ) -> ArchiveIndexPublicationRecord:
        """Persist one index/pointer publication."""

    async def get_latest_index_publication(
        self,
        *,
        environment: str,
    ) -> ArchiveIndexPublicationRecord | None:
        """Return latest index publication for one environment."""

    async def list_ops_videos(
        self,
        query: ArchiveOpsVideoQuery,
    ) -> ArchiveOpsVideoListResult:
        """Return archive publish state for Ops UI."""


@dataclass(frozen=True, slots=True)
class ArchiveTimelineArtifact:
    object_key: str
    public_url: str
    payload: JsonObject
    payload_bytes: bytes
    sha256: str
    byte_size: int
    version: str
    block_count: int
    episode_count: int
    topic_cluster_count: int
    review_flag_count: int
    micro_event_count: int


@dataclass(frozen=True, slots=True)
class ArchiveIndexArtifact:
    object_key: str
    public_url: str
    payload: JsonObject
    payload_bytes: bytes
    sha256: str
    byte_size: int
    version: str
    video_count: int
    pointer_key: str
    pointer_payload: JsonObject
    pointer_payload_bytes: bytes
    pointer_sha256: str
    pointer_byte_size: int
    pointer_public_url: str
    artifact_ids: list[int] = field(default_factory=list)
