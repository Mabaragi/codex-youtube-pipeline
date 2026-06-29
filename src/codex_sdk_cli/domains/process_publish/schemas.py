from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from codex_sdk_cli.domains.codex.choices import ReasoningEffortChoice


class ProcessToPublishRequest(BaseModel):
    video_ids: list[int] = Field(alias="videoIds", min_length=1, max_length=200)
    micro_reasoning: ReasoningEffortChoice | None = Field(
        default=None,
        alias="microReasoning",
    )
    timeline_reasoning: ReasoningEffortChoice | None = Field(
        default=None,
        alias="timelineReasoning",
    )
    retry_failed: bool = Field(default=False, alias="retryFailed")
    wait_timeout_minutes: int = Field(
        default=30,
        ge=1,
        le=240,
        alias="waitTimeoutMinutes",
    )
    poll_interval_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        alias="pollIntervalSeconds",
    )
    environment: str | None = Field(default=None, min_length=1, max_length=64)
    variant: str | None = Field(default=None, min_length=1, max_length=64)
    schema_version: int | None = Field(default=None, ge=1, le=100, alias="schemaVersion")

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "videoIds": [1, 2, 3],
                    "microReasoning": "medium",
                    "timelineReasoning": "high",
                    "retryFailed": True,
                    "waitTimeoutMinutes": 30,
                    "pollIntervalSeconds": 10,
                    "environment": "prod",
                    "variant": "control",
                    "schemaVersion": 1,
                }
            ]
        },
    )


class ProcessToPublishStageResponse(BaseModel):
    video_task_id: int | None = Field(default=None, alias="videoTaskId")
    job_id: int | None = Field(default=None, alias="jobId")
    job_attempt_id: int | None = Field(default=None, alias="jobAttemptId")
    status: str | None = None
    reason: str | None = None
    error_type: str | None = Field(default=None, alias="errorType")
    error_message: str | None = Field(default=None, alias="errorMessage")
    source_micro_event_task_id: int | None = Field(
        default=None,
        alias="sourceMicroEventTaskId",
    )
    source_timeline_task_id: int | None = Field(
        default=None,
        alias="sourceTimelineTaskId",
    )
    source_timeline_composition_id: int | None = Field(
        default=None,
        alias="sourceTimelineCompositionId",
    )
    artifact_id: int | None = Field(default=None, alias="artifactId")
    public_url: str | None = Field(default=None, alias="publicUrl")

    model_config = ConfigDict(populate_by_name=True)


class ProcessToPublishItemResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str | None = Field(alias="youtubeVideoId")
    status: str
    reason: str
    micro: ProcessToPublishStageResponse | None = None
    timeline: ProcessToPublishStageResponse | None = None
    publish: ProcessToPublishStageResponse | None = None

    model_config = ConfigDict(populate_by_name=True)


class ProcessToPublishResponse(BaseModel):
    requested_count: int = Field(alias="requestedCount")
    micro_succeeded_count: int = Field(alias="microSucceededCount")
    timeline_succeeded_count: int = Field(alias="timelineSucceededCount")
    published_count: int = Field(alias="publishedCount")
    failed_count: int = Field(alias="failedCount")
    skipped_count: int = Field(alias="skippedCount")
    items: list[ProcessToPublishItemResponse]

    model_config = ConfigDict(populate_by_name=True)
