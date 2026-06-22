from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .ports import JsonObject, PipelineJobAttemptStatus, PipelineJobStatus


class PipelineJobSummaryResponse(BaseModel):
    job_id: int = Field(alias="jobId")
    step: str
    status: PipelineJobStatus
    subject_type: str | None = Field(alias="subjectType")
    subject_id: int | None = Field(alias="subjectId")
    external_key: str | None = Field(alias="externalKey")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    completed_at: datetime | None = Field(alias="completedAt")
    latest_attempt_id: int | None = Field(alias="latestAttemptId")
    latest_attempt_status: PipelineJobAttemptStatus | None = Field(alias="latestAttemptStatus")
    attempt_count: int = Field(alias="attemptCount")

    model_config = ConfigDict(populate_by_name=True)


class ListPipelineJobsResponse(BaseModel):
    items: list[PipelineJobSummaryResponse]
    next_cursor: int | None = Field(alias="nextCursor")

    model_config = ConfigDict(populate_by_name=True)


class PipelineJobAttemptResponse(BaseModel):
    job_attempt_id: int = Field(alias="jobAttemptId")
    attempt_no: int = Field(alias="attemptNo")
    status: PipelineJobAttemptStatus
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    worker_id: str | None = Field(alias="workerId")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")
    output_json: JsonObject | None = Field(alias="outputJson")

    model_config = ConfigDict(populate_by_name=True)


class ExternalApiCallSummaryResponse(BaseModel):
    external_api_call_id: int = Field(alias="externalApiCallId")
    job_attempt_id: int | None = Field(alias="jobAttemptId")
    provider: str
    operation: str
    response_status_code: int | None = Field(alias="responseStatusCode")
    validation_status: str = Field(alias="validationStatus")
    response_storage_uri: str | None = Field(alias="responseStorageUri")
    duration_ms: int = Field(alias="durationMs")
    quota_cost: int | None = Field(alias="quotaCost")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class PipelineChannelOutputResponse(BaseModel):
    channel_id: int = Field(alias="channelId")
    streamer_id: int = Field(alias="streamerId")
    handle: str
    name: str
    youtube_channel_id: str | None = Field(alias="youtubeChannelId")
    uploads_playlist_id: str | None = Field(alias="uploadsPlaylistId")
    source_api_call_id: int | None = Field(alias="sourceApiCallId")
    source_job_id: int | None = Field(alias="sourceJobId")

    model_config = ConfigDict(populate_by_name=True)


class PipelineVideoOutputResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    published_at: datetime = Field(alias="publishedAt")
    source_listing_api_call_id: int | None = Field(alias="sourceListingApiCallId")
    source_details_api_call_id: int | None = Field(alias="sourceDetailsApiCallId")
    source_job_id: int | None = Field(alias="sourceJobId")

    model_config = ConfigDict(populate_by_name=True)


class PipelineTranscriptOutputResponse(BaseModel):
    transcript_id: int = Field(alias="transcriptId")
    video_task_id: int = Field(alias="videoTaskId")
    video_id: int = Field(alias="videoId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    language_code: str = Field(alias="languageCode")
    storage_uri: str = Field(alias="storageUri")

    model_config = ConfigDict(populate_by_name=True)


class PipelineTranscriptCueOutputResponse(BaseModel):
    transcript_id: int = Field(alias="transcriptId")
    cue_count: int = Field(alias="cueCount")
    first_cue_id: str | None = Field(alias="firstCueId")
    last_cue_id: str | None = Field(alias="lastCueId")
    source_job_id: int | None = Field(alias="sourceJobId")

    model_config = ConfigDict(populate_by_name=True)


class PipelineJobDetailResponse(BaseModel):
    job_id: int = Field(alias="jobId")
    step: str
    status: PipelineJobStatus
    subject_type: str | None = Field(alias="subjectType")
    subject_id: int | None = Field(alias="subjectId")
    external_key: str | None = Field(alias="externalKey")
    input_json: JsonObject = Field(alias="inputJson")
    input_hash: str = Field(alias="inputHash")
    parent_job_id: int | None = Field(alias="parentJobId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    completed_at: datetime | None = Field(alias="completedAt")
    attempts: list[PipelineJobAttemptResponse]
    external_api_calls: list[ExternalApiCallSummaryResponse] = Field(alias="externalApiCalls")
    channels: list[PipelineChannelOutputResponse]
    videos: list[PipelineVideoOutputResponse]
    transcripts: list[PipelineTranscriptOutputResponse]
    transcript_cues: list[PipelineTranscriptCueOutputResponse] = Field(alias="transcriptCues")

    model_config = ConfigDict(populate_by_name=True)


class RetryPipelineJobResponse(BaseModel):
    job_id: int = Field(alias="jobId")
    job_attempt_id: int = Field(alias="jobAttemptId")
    step: str
    status: PipelineJobStatus
    result: JsonObject

    model_config = ConfigDict(populate_by_name=True)
