from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject
from codex_sdk_cli.domains.youtube_transcripts.schemas import TranscriptMetadataResponse

OpsCandidateCategoryLiteral = Literal[
    "readyNoHistory",
    "retryableCanceled",
    "failed",
    "active",
    "blocked",
]


class OpsStatusCountResponse(BaseModel):
    status: str
    count: int


class OpsSummaryCountsResponse(BaseModel):
    streamers: int
    channels: int
    videos: int
    transcripts: int
    video_tasks: list[OpsStatusCountResponse] = Field(alias="videoTasks")
    pipeline_jobs: list[OpsStatusCountResponse] = Field(alias="pipelineJobs")

    model_config = ConfigDict(populate_by_name=True)


class OpsRecentFailureResponse(BaseModel):
    kind: Literal["pipeline_job", "video_task"]
    id: int
    status: str
    label: str
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class OpsSummaryResponse(BaseModel):
    api_status: Literal["ok"] = Field(alias="apiStatus")
    s3: dict[str, object]
    counts: OpsSummaryCountsResponse
    recent_failures: list[OpsRecentFailureResponse] = Field(alias="recentFailures")

    model_config = ConfigDict(populate_by_name=True)


class OpsChannelResponse(BaseModel):
    channel_id: int = Field(alias="channelId")
    streamer_id: int = Field(alias="streamerId")
    streamer_name: str = Field(alias="streamerName")
    handle: str
    name: str
    youtube_channel_id: str | None = Field(alias="youtubeChannelId")
    uploads_playlist_id: str | None = Field(alias="uploadsPlaylistId")
    video_count: int = Field(alias="videoCount")
    transcript_succeeded_count: int = Field(alias="transcriptSucceededCount")
    task_no_transcript_count: int = Field(alias="taskNoTranscriptCount")
    task_failed_count: int = Field(alias="taskFailedCount")
    task_running_count: int = Field(alias="taskRunningCount")
    latest_video_published_at: datetime | None = Field(alias="latestVideoPublishedAt")
    latest_task_updated_at: datetime | None = Field(alias="latestTaskUpdatedAt")

    model_config = ConfigDict(populate_by_name=True)


class OpsChannelListResponse(BaseModel):
    items: list[OpsChannelResponse]


class OpsVideoCueGenerationResponse(BaseModel):
    generated: bool
    transcript_id: int | None = Field(alias="transcriptId")
    cue_count: int = Field(alias="cueCount")
    latest_task_id: int | None = Field(alias="latestTaskId")
    latest_task_status: str | None = Field(alias="latestTaskStatus")
    latest_task_updated_at: datetime | None = Field(alias="latestTaskUpdatedAt")

    model_config = ConfigDict(populate_by_name=True)


class OpsVideoMicroEventGenerationResponse(BaseModel):
    generated: bool
    video_task_id: int | None = Field(alias="videoTaskId")
    window_count: int = Field(alias="windowCount")
    micro_event_count: int = Field(alias="microEventCount")
    latest_task_id: int | None = Field(alias="latestTaskId")
    latest_task_status: str | None = Field(alias="latestTaskStatus")
    latest_task_updated_at: datetime | None = Field(alias="latestTaskUpdatedAt")

    model_config = ConfigDict(populate_by_name=True)


class OpsVideoTimelineGenerationResponse(BaseModel):
    generated: bool
    composition_id: int | None = Field(alias="compositionId")
    video_task_id: int | None = Field(alias="videoTaskId")
    episode_count: int = Field(alias="episodeCount")
    latest_task_id: int | None = Field(alias="latestTaskId")
    latest_task_status: str | None = Field(alias="latestTaskStatus")
    latest_task_updated_at: datetime | None = Field(alias="latestTaskUpdatedAt")

    model_config = ConfigDict(populate_by_name=True)


class OpsVideoGenerationResponse(BaseModel):
    cues: OpsVideoCueGenerationResponse
    micro_events: OpsVideoMicroEventGenerationResponse = Field(alias="microEvents")
    timeline: OpsVideoTimelineGenerationResponse

    model_config = ConfigDict(populate_by_name=True)


class OpsVideoResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    channel_name: str = Field(alias="channelName")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    published_at: datetime = Field(alias="publishedAt")
    duration: str | None
    is_embeddable: bool | None = Field(alias="isEmbeddable")
    embed_status_checked_at: datetime | None = Field(alias="embedStatusCheckedAt")
    thumbnail_url: str | None = Field(alias="thumbnailUrl")
    latest_task_id: int | None = Field(alias="latestTaskId")
    latest_task_name: str | None = Field(alias="latestTaskName")
    latest_task_status: str | None = Field(alias="latestTaskStatus")
    latest_task_updated_at: datetime | None = Field(alias="latestTaskUpdatedAt")
    transcript_id: int | None = Field(alias="transcriptId")
    generation: OpsVideoGenerationResponse

    model_config = ConfigDict(populate_by_name=True)


class OpsVideoListResponse(BaseModel):
    items: list[OpsVideoResponse]
    total: int
    limit: int
    offset: int


class OpsRefreshVideoEmbedStatusRequest(BaseModel):
    video_ids: list[int] | None = Field(default=None, alias="videoIds")
    limit: int = Field(default=200, ge=1, le=500)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class OpsRefreshVideoEmbedStatusItemResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    status: Literal["updated", "failed"]
    is_embeddable: bool | None = Field(alias="isEmbeddable")
    source_api_call_id: int | None = Field(alias="sourceApiCallId")
    canceled_pending_task_count: int = Field(alias="canceledPendingTaskCount")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class OpsRefreshVideoEmbedStatusResponse(BaseModel):
    scanned_count: int = Field(alias="scannedCount")
    updated_count: int = Field(alias="updatedCount")
    failed_count: int = Field(alias="failedCount")
    items: list[OpsRefreshVideoEmbedStatusItemResponse]

    model_config = ConfigDict(populate_by_name=True)


class OpsVideoTaskResponse(BaseModel):
    video_task_id: int = Field(alias="videoTaskId")
    video_id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    channel_name: str = Field(alias="channelName")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    task_name: str = Field(alias="taskName")
    task_version: str = Field(alias="taskVersion")
    status: str
    worker_id: str | None = Field(alias="workerId")
    timeout_seconds: int = Field(alias="timeoutSeconds")
    job_id: int | None = Field(alias="jobId")
    job_attempt_id: int | None = Field(alias="jobAttemptId")
    output_transcript_id: int | None = Field(alias="outputTranscriptId")
    output_json: JsonObject | None = Field(alias="outputJson")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")
    started_at: datetime | None = Field(alias="startedAt")
    completed_at: datetime | None = Field(alias="completedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class OpsVideoTaskListResponse(BaseModel):
    items: list[OpsVideoTaskResponse]
    total: int
    limit: int
    offset: int


class OpsTaskSummaryResponse(BaseModel):
    video_task_id: int = Field(alias="videoTaskId")
    status: str
    worker_id: str | None = Field(alias="workerId")
    job_id: int | None = Field(alias="jobId")
    job_attempt_id: int | None = Field(alias="jobAttemptId")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class OpsCandidateRecommendedEnqueueResponse(BaseModel):
    target: Literal["selected_videos"] = Field(default="selected_videos")
    video_ids: list[int] = Field(alias="videoIds")
    retry_failed: bool = Field(alias="retryFailed")

    model_config = ConfigDict(populate_by_name=True)


class OpsMicroEventReadyCandidateResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    channel_name: str = Field(alias="channelName")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    published_at: datetime = Field(alias="publishedAt")
    transcript_id: int | None = Field(alias="transcriptId")
    cue_count: int = Field(alias="cueCount")
    latest_cue_task: OpsTaskSummaryResponse | None = Field(alias="latestCueTask")
    latest_micro_task: OpsTaskSummaryResponse | None = Field(alias="latestMicroTask")
    category: OpsCandidateCategoryLiteral
    recommended_enqueue: OpsCandidateRecommendedEnqueueResponse = Field(
        alias="recommendedEnqueue"
    )

    model_config = ConfigDict(populate_by_name=True)


class OpsMicroEventReadyCandidateListResponse(BaseModel):
    items: list[OpsMicroEventReadyCandidateResponse]
    total: int
    limit: int
    offset: int


class OpsTimelineReadyCandidateResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    channel_name: str = Field(alias="channelName")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    published_at: datetime = Field(alias="publishedAt")
    source_micro_event_task_id: int = Field(alias="sourceMicroEventTaskId")
    micro_event_count: int = Field(alias="microEventCount")
    window_count: int = Field(alias="windowCount")
    latest_timeline_task: OpsTaskSummaryResponse | None = Field(alias="latestTimelineTask")
    category: OpsCandidateCategoryLiteral
    recommended_enqueue: OpsCandidateRecommendedEnqueueResponse = Field(
        alias="recommendedEnqueue"
    )

    model_config = ConfigDict(populate_by_name=True)


class OpsTimelineReadyCandidateListResponse(BaseModel):
    items: list[OpsTimelineReadyCandidateResponse]
    total: int
    limit: int
    offset: int


class OpsLatestEventResponse(BaseModel):
    operation_event_id: int = Field(alias="operationEventId")
    occurred_at: datetime = Field(alias="occurredAt")
    event_type: str = Field(alias="eventType")
    severity: str
    message: str
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class OpsStuckTaskResponse(BaseModel):
    video_task_id: int = Field(alias="videoTaskId")
    video_id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    channel_name: str = Field(alias="channelName")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    task_name: str = Field(alias="taskName")
    status: str
    worker_id: str | None = Field(alias="workerId")
    worker_pid: int | None = Field(alias="workerPid")
    job_id: int | None = Field(alias="jobId")
    job_attempt_id: int | None = Field(alias="jobAttemptId")
    job_attempt_status: str | None = Field(alias="jobAttemptStatus")
    started_at: datetime | None = Field(alias="startedAt")
    updated_at: datetime = Field(alias="updatedAt")
    stale_since: datetime = Field(alias="staleSince")
    stale_age_seconds: int = Field(alias="staleAgeSeconds")
    latest_event: OpsLatestEventResponse | None = Field(alias="latestEvent")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class OpsStuckTaskListResponse(BaseModel):
    items: list[OpsStuckTaskResponse]
    total: int
    task_name: str = Field(alias="taskName")
    minutes: int

    model_config = ConfigDict(populate_by_name=True)


class OpsVideoDetailResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    channel_name: str = Field(alias="channelName")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    description: str
    published_at: datetime = Field(alias="publishedAt")
    duration: str | None
    is_embeddable: bool | None = Field(alias="isEmbeddable")
    embed_status_checked_at: datetime | None = Field(alias="embedStatusCheckedAt")
    thumbnail_url: str | None = Field(alias="thumbnailUrl")
    source_listing_api_call_id: int | None = Field(alias="sourceListingApiCallId")
    source_details_api_call_id: int | None = Field(alias="sourceDetailsApiCallId")
    source_embed_status_api_call_id: int | None = Field(alias="sourceEmbedStatusApiCallId")
    source_job_id: int | None = Field(alias="sourceJobId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    latest_task_id: int | None = Field(alias="latestTaskId")
    latest_task_name: str | None = Field(alias="latestTaskName")
    latest_task_status: str | None = Field(alias="latestTaskStatus")
    latest_task_updated_at: datetime | None = Field(alias="latestTaskUpdatedAt")
    transcript_id: int | None = Field(alias="transcriptId")
    tasks: list[OpsVideoTaskResponse]
    transcripts: list[TranscriptMetadataResponse]

    model_config = ConfigDict(populate_by_name=True)


class OpsSchemaColumnResponse(BaseModel):
    id: str
    name: str
    type: str
    nullable: bool
    primary_key: bool = Field(alias="primaryKey")
    unique: bool
    index: bool
    default: str | None
    foreign_keys: list[str] = Field(alias="foreignKeys")
    constraint_names: list[str] = Field(alias="constraintNames")

    model_config = ConfigDict(populate_by_name=True)


class OpsSchemaIndexResponse(BaseModel):
    name: str
    column_names: list[str] = Field(alias="columnNames")
    unique: bool

    model_config = ConfigDict(populate_by_name=True)


class OpsSchemaUniqueConstraintResponse(BaseModel):
    name: str
    column_names: list[str] = Field(alias="columnNames")

    model_config = ConfigDict(populate_by_name=True)


class OpsSchemaForeignKeyConstraintResponse(BaseModel):
    name: str
    column_names: list[str] = Field(alias="columnNames")
    target_table: str = Field(alias="targetTable")
    target_column_names: list[str] = Field(alias="targetColumnNames")

    model_config = ConfigDict(populate_by_name=True)


class OpsSchemaTableResponse(BaseModel):
    id: str
    name: str
    columns: list[OpsSchemaColumnResponse]
    indexes: list[OpsSchemaIndexResponse]
    unique_constraints: list[OpsSchemaUniqueConstraintResponse] = Field(
        alias="uniqueConstraints"
    )
    foreign_key_constraints: list[OpsSchemaForeignKeyConstraintResponse] = Field(
        alias="foreignKeyConstraints"
    )

    model_config = ConfigDict(populate_by_name=True)


class OpsSchemaRelationResponse(BaseModel):
    id: str
    constraint_name: str = Field(alias="constraintName")
    source_table: str = Field(alias="sourceTable")
    source_column: str = Field(alias="sourceColumn")
    target_table: str = Field(alias="targetTable")
    target_column: str = Field(alias="targetColumn")
    source_nullable: bool = Field(alias="sourceNullable")
    target_primary_key: bool = Field(alias="targetPrimaryKey")
    relation_kind: Literal[
        "one_to_many",
        "one_to_one",
        "optional_one_to_many",
        "optional_one_to_one",
    ] = Field(alias="relationKind")

    model_config = ConfigDict(populate_by_name=True)


class OpsSchemaGraphResponse(BaseModel):
    tables: list[OpsSchemaTableResponse]
    relations: list[OpsSchemaRelationResponse]
