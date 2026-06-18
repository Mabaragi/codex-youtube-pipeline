from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    task_failed_count: int = Field(alias="taskFailedCount")
    task_running_count: int = Field(alias="taskRunningCount")
    latest_video_published_at: datetime | None = Field(alias="latestVideoPublishedAt")
    latest_task_updated_at: datetime | None = Field(alias="latestTaskUpdatedAt")

    model_config = ConfigDict(populate_by_name=True)


class OpsChannelListResponse(BaseModel):
    items: list[OpsChannelResponse]


class OpsVideoResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    channel_name: str = Field(alias="channelName")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    published_at: datetime = Field(alias="publishedAt")
    duration: str | None
    thumbnail_url: str | None = Field(alias="thumbnailUrl")
    latest_task_id: int | None = Field(alias="latestTaskId")
    latest_task_name: str | None = Field(alias="latestTaskName")
    latest_task_status: str | None = Field(alias="latestTaskStatus")
    latest_task_updated_at: datetime | None = Field(alias="latestTaskUpdatedAt")
    transcript_id: int | None = Field(alias="transcriptId")

    model_config = ConfigDict(populate_by_name=True)


class OpsVideoListResponse(BaseModel):
    items: list[OpsVideoResponse]
    total: int
    limit: int
    offset: int


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


class OpsSchemaColumnResponse(BaseModel):
    id: str
    name: str
    type: str
    nullable: bool
    primary_key: bool = Field(alias="primaryKey")
    unique: bool
    index: bool
    foreign_keys: list[str] = Field(alias="foreignKeys")

    model_config = ConfigDict(populate_by_name=True)


class OpsSchemaTableResponse(BaseModel):
    id: str
    name: str
    columns: list[OpsSchemaColumnResponse]


class OpsSchemaRelationResponse(BaseModel):
    id: str
    source_table: str = Field(alias="sourceTable")
    source_column: str = Field(alias="sourceColumn")
    target_table: str = Field(alias="targetTable")
    target_column: str = Field(alias="targetColumn")

    model_config = ConfigDict(populate_by_name=True)


class OpsSchemaGraphResponse(BaseModel):
    tables: list[OpsSchemaTableResponse]
    relations: list[OpsSchemaRelationResponse]

