from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ports import ArchivePublishStatusFilter, ArchivePublishTarget

ArchivePublishModeLiteral = Literal["prod", "dev"]


class ArchivePublishRequest(BaseModel):
    target: ArchivePublishTarget = "next_eligible"
    video_ids: list[int] = Field(default_factory=list, max_length=200, alias="videoIds")
    channel_id: int | None = Field(default=None, ge=1, alias="channelId")
    search: str | None = Field(default=None, min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=200)
    publish_mode: ArchivePublishModeLiteral = Field(default="prod", alias="publishMode")
    environment: str = Field(default="prod", min_length=1, max_length=64)
    variant: str = Field(default="control", min_length=1, max_length=64)
    schema_version: int = Field(default=1, ge=1, le=100, alias="schemaVersion")
    retry_failed: bool = Field(default=False, alias="retryFailed")
    regenerate_succeeded: bool = Field(default=False, alias="regenerateSucceeded")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")

    @model_validator(mode="before")
    @classmethod
    def _dev_defaults(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        mode = normalized.get("publishMode", normalized.get("publish_mode", "prod"))
        if mode == "dev":
            if "environment" not in normalized:
                normalized["environment"] = "dev"
            if "variant" not in normalized:
                normalized["variant"] = "dev-preview"
        return normalized

    @model_validator(mode="after")
    def _selected_videos_require_ids(self) -> ArchivePublishRequest:
        if self.target == "selected_videos" and not self.video_ids:
            raise ValueError("videoIds is required when target is selected_videos.")
        if self.publish_mode == "dev" and self.environment == "prod":
            raise ValueError("publishMode=dev cannot publish to environment=prod.")
        return self

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "target": "next_eligible",
                    "limit": 20,
                    "publishMode": "prod",
                    "environment": "prod",
                    "variant": "control",
                    "schemaVersion": 1,
                    "retryFailed": False,
                    "regenerateSucceeded": False,
                    "includeNonEmbeddable": False,
                }
            ]
        },
    )


class ArchivePublishItemResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str | None = Field(alias="youtubeVideoId")
    video_task_id: int | None = Field(alias="videoTaskId")
    status: str
    reason: str
    source_timeline_task_id: int | None = Field(alias="sourceTimelineTaskId")
    source_timeline_composition_id: int | None = Field(alias="sourceTimelineCompositionId")
    publish_mode: ArchivePublishModeLiteral = Field(default="prod", alias="publishMode")
    environment: str
    variant: str
    schema_version: int = Field(alias="schemaVersion")
    artifact_id: int | None = Field(alias="artifactId")
    public_url: str | None = Field(alias="publicUrl")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class ArchivePublishResponse(BaseModel):
    requested_count: int = Field(alias="requestedCount")
    scanned_count: int = Field(alias="scannedCount")
    processed_count: int = Field(alias="processedCount")
    published_count: int = Field(alias="publishedCount")
    already_published_count: int = Field(alias="alreadyPublishedCount")
    regenerated_count: int = Field(alias="regeneratedCount")
    failed_count: int = Field(alias="failedCount")
    failed_skipped_count: int = Field(alias="failedSkippedCount")
    ineligible_count: int = Field(alias="ineligibleCount")
    items: list[ArchivePublishItemResponse]

    model_config = ConfigDict(populate_by_name=True)


class ArchiveStorageConfigResponse(BaseModel):
    configured: bool
    bucket: str | None
    endpoint: str | None
    public_base_url: str | None = Field(alias="publicBaseUrl")
    prefix: str

    model_config = ConfigDict(populate_by_name=True)


class ArchiveIndexPublicationResponse(BaseModel):
    publication_id: int = Field(alias="publicationId")
    environment: str
    schema_version: int = Field(alias="schemaVersion")
    version: str
    pointer_key: str = Field(alias="pointerKey")
    index_key: str = Field(alias="indexKey")
    public_url: str = Field(alias="publicUrl")
    sha256: str
    byte_size: int = Field(alias="byteSize")
    video_count: int = Field(alias="videoCount")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class ArchiveCurrentResponse(BaseModel):
    publish_mode: ArchivePublishModeLiteral = Field(alias="publishMode")
    environment: str
    storage: ArchiveStorageConfigResponse
    latest_publication: ArchiveIndexPublicationResponse | None = Field(alias="latestPublication")

    model_config = ConfigDict(populate_by_name=True)


class ArchiveVideoArtifactResponse(BaseModel):
    artifact_id: int = Field(alias="artifactId")
    source_timeline_composition_id: int = Field(alias="sourceTimelineCompositionId")
    source_timeline_task_id: int = Field(alias="sourceTimelineTaskId")
    source_micro_event_task_id: int = Field(alias="sourceMicroEventTaskId")
    publish_task_id: int = Field(alias="publishTaskId")
    publish_job_id: int = Field(alias="publishJobId")
    environment: str
    variant: str
    schema_version: int = Field(alias="schemaVersion")
    version: str
    object_key: str = Field(alias="objectKey")
    public_url: str = Field(alias="publicUrl")
    sha256: str
    byte_size: int = Field(alias="byteSize")
    block_count: int = Field(alias="blockCount")
    episode_count: int = Field(alias="episodeCount")
    topic_cluster_count: int = Field(alias="topicClusterCount")
    review_flag_count: int = Field(alias="reviewFlagCount")
    micro_event_count: int = Field(alias="microEventCount")
    public_catalog_synced_at: datetime | None = Field(alias="publicCatalogSyncedAt")
    public_catalog_sync_error: str | None = Field(alias="publicCatalogSyncError")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class ArchiveVideoTaskSummaryResponse(BaseModel):
    video_task_id: int = Field(alias="videoTaskId")
    status: str
    job_id: int | None = Field(alias="jobId")
    job_attempt_id: int | None = Field(alias="jobAttemptId")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class ArchiveOpsVideoResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    channel_name: str = Field(alias="channelName")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    published_at: datetime = Field(alias="publishedAt")
    duration: str | None
    thumbnail_url: str | None = Field(alias="thumbnailUrl")
    is_embeddable: bool | None = Field(alias="isEmbeddable")
    timeline_ready: bool = Field(alias="timelineReady")
    timeline_composition_id: int | None = Field(alias="timelineCompositionId")
    timeline_task_id: int | None = Field(alias="timelineTaskId")
    timeline_episode_count: int = Field(alias="timelineEpisodeCount")
    latest_task: ArchiveVideoTaskSummaryResponse | None = Field(alias="latestTask")
    latest_artifact: ArchiveVideoArtifactResponse | None = Field(alias="latestArtifact")

    model_config = ConfigDict(populate_by_name=True)


class ArchiveOpsVideoListResponse(BaseModel):
    items: list[ArchiveOpsVideoResponse]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(populate_by_name=True)


ArchivePublishTargetLiteral = Literal["selected_videos", "current_filters", "next_eligible"]
ArchivePublishStatusFilterLiteral = ArchivePublishStatusFilter
