from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .ports import JsonObject, VideoTaskStatus

TranscriptCollectItemStatus = Literal[
    "succeeded",
    "failed",
    "timed_out",
    "no_transcript",
    "skipped",
]


class CollectChannelTranscriptTasksRequest(BaseModel):
    limit: int = Field(default=5, ge=1)
    languages: list[str] | None = Field(
        default=None,
        description="Preferred transcript language codes, tried in order.",
    )
    preserve_formatting: bool = Field(default=False, alias="preserveFormatting")
    collect_new: bool = Field(default=True, alias="collectNew")
    retry_failed: bool = Field(default=False, alias="retryFailed")
    recheck_no_transcript: bool = Field(default=False, alias="recheckNoTranscript")

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "limit": 5,
                    "languages": ["ko", "en"],
                    "preserveFormatting": False,
                    "collectNew": True,
                    "retryFailed": False,
                    "recheckNoTranscript": False,
                }
            ]
        },
    )


class CollectAllTranscriptTasksRequest(BaseModel):
    languages: list[str] | None = Field(
        default=None,
        description="Preferred transcript language codes, tried in order.",
    )
    preserve_formatting: bool = Field(default=False, alias="preserveFormatting")
    collect_new: bool = Field(default=True, alias="collectNew")
    retry_failed: bool = Field(default=False, alias="retryFailed")
    recheck_no_transcript: bool = Field(default=False, alias="recheckNoTranscript")

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "languages": ["ko", "en"],
                    "preserveFormatting": False,
                    "collectNew": True,
                    "retryFailed": False,
                    "recheckNoTranscript": False,
                }
            ]
        },
    )


class TranscriptCollectItemResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    video_task_id: int | None = Field(alias="videoTaskId")
    status: TranscriptCollectItemStatus
    reason: str
    job_id: int | None = Field(alias="jobId")
    job_attempt_id: int | None = Field(alias="jobAttemptId")
    transcript_id: int | None = Field(alias="transcriptId")
    cue_job_id: int | None = Field(default=None, alias="cueJobId")
    cue_job_attempt_id: int | None = Field(default=None, alias="cueJobAttemptId")
    cue_status: str | None = Field(default=None, alias="cueStatus")
    cue_count: int | None = Field(default=None, alias="cueCount")
    cue_error_type: str | None = Field(default=None, alias="cueErrorType")
    cue_error_message: str | None = Field(default=None, alias="cueErrorMessage")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class CollectChannelTranscriptTasksResponse(BaseModel):
    channel_id: int = Field(alias="channelId")
    requested_count: int = Field(alias="requestedCount")
    succeeded_count: int = Field(alias="succeededCount")
    skipped_count: int = Field(alias="skippedCount")
    failed_count: int = Field(alias="failedCount")
    timeout_count: int = Field(alias="timeoutCount")
    no_transcript_count: int = Field(alias="noTranscriptCount")
    items: list[TranscriptCollectItemResponse]

    model_config = ConfigDict(populate_by_name=True)


class CollectAllTranscriptTasksResponse(BaseModel):
    requested_count: int = Field(alias="requestedCount")
    succeeded_count: int = Field(alias="succeededCount")
    skipped_count: int = Field(alias="skippedCount")
    failed_count: int = Field(alias="failedCount")
    timeout_count: int = Field(alias="timeoutCount")
    no_transcript_count: int = Field(alias="noTranscriptCount")
    items: list[TranscriptCollectItemResponse]

    model_config = ConfigDict(populate_by_name=True)


class VideoTaskResponse(BaseModel):
    video_task_id: int = Field(alias="videoTaskId")
    video_id: int = Field(alias="videoId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    task_name: str = Field(alias="taskName")
    task_version: str = Field(alias="taskVersion")
    input_hash: str = Field(alias="inputHash")
    status: VideoTaskStatus
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
