from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .ports import CodexUsageStatus, JsonObject


class CodexUsageResponse(BaseModel):
    codex_usage_id: int = Field(alias="codexUsageId")
    source: str
    operation: str
    model: str | None
    reasoning_effort: str | None = Field(alias="reasoningEffort")
    status: CodexUsageStatus
    thread_id: str | None = Field(alias="threadId")
    turn_id: str | None = Field(alias="turnId")
    usage_json: JsonObject | None = Field(alias="usageJson")
    input_tokens: int | None = Field(alias="inputTokens")
    output_tokens: int | None = Field(alias="outputTokens")
    total_tokens: int | None = Field(alias="totalTokens")
    cached_input_tokens: int | None = Field(alias="cachedInputTokens")
    reasoning_output_tokens: int | None = Field(alias="reasoningOutputTokens")
    duration_ms: int = Field(alias="durationMs")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")
    video_id: int | None = Field(alias="videoId")
    video_task_id: int | None = Field(alias="videoTaskId")
    job_id: int | None = Field(alias="jobId")
    job_attempt_id: int | None = Field(alias="jobAttemptId")
    transcript_id: int | None = Field(alias="transcriptId")
    window_index: int | None = Field(alias="windowIndex")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class CodexUsageSummaryResponse(BaseModel):
    run_count: int = Field(alias="runCount")
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")
    total_tokens: int = Field(alias="totalTokens")
    cached_input_tokens: int = Field(alias="cachedInputTokens")
    reasoning_output_tokens: int = Field(alias="reasoningOutputTokens")

    model_config = ConfigDict(populate_by_name=True)


class CodexUsageListResponse(BaseModel):
    items: list[CodexUsageResponse]
    next_cursor: int | None = Field(alias="nextCursor")
    summary: CodexUsageSummaryResponse

    model_config = ConfigDict(populate_by_name=True)


class CodexUsageVideoSummaryResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str | None = Field(alias="youtubeVideoId")
    title: str | None
    latest_model: str | None = Field(alias="latestModel")
    latest_reasoning_effort: str | None = Field(alias="latestReasoningEffort")
    run_count: int = Field(alias="runCount")
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")
    total_tokens: int = Field(alias="totalTokens")
    cached_input_tokens: int = Field(alias="cachedInputTokens")
    reasoning_output_tokens: int = Field(alias="reasoningOutputTokens")
    latest_created_at: datetime = Field(alias="latestCreatedAt")

    model_config = ConfigDict(populate_by_name=True)


class CodexUsageByVideoResponse(BaseModel):
    items: list[CodexUsageVideoSummaryResponse]
    summary: CodexUsageSummaryResponse

    model_config = ConfigDict(populate_by_name=True)


class CodexUsageJobSummaryResponse(BaseModel):
    job_id: int | None = Field(alias="jobId")
    job_step: str | None = Field(alias="jobStep")
    job_status: str | None = Field(alias="jobStatus")
    subject_type: str | None = Field(alias="subjectType")
    subject_id: int | None = Field(alias="subjectId")
    external_key: str | None = Field(alias="externalKey")
    latest_model: str | None = Field(alias="latestModel")
    latest_reasoning_effort: str | None = Field(alias="latestReasoningEffort")
    run_count: int = Field(alias="runCount")
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")
    total_tokens: int = Field(alias="totalTokens")
    cached_input_tokens: int = Field(alias="cachedInputTokens")
    reasoning_output_tokens: int = Field(alias="reasoningOutputTokens")
    latest_created_at: datetime = Field(alias="latestCreatedAt")

    model_config = ConfigDict(populate_by_name=True)


class CodexUsageByJobResponse(BaseModel):
    items: list[CodexUsageJobSummaryResponse]
    summary: CodexUsageSummaryResponse

    model_config = ConfigDict(populate_by_name=True)
