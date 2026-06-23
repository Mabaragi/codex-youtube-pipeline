from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_sdk_cli.settings import CodexModelChoice, ReasoningEffortChoice

from .ports import (
    Activity,
    ApplyScope,
    ContentKind,
    CorrectionType,
    ExcludedRangeReason,
    JsonObject,
    ProgramMode,
    RelationToPrevious,
    SupportLevel,
    VideoTaskStatus,
    WindowStatus,
)

MicroEventExtractItemStatus = WindowStatus | VideoTaskStatus


class MicroEventExtractRequest(BaseModel):
    retry_failed: bool = Field(default=False, alias="retryFailed")
    regenerate_succeeded: bool = Field(default=False, alias="regenerateSucceeded")
    window_minutes: int = Field(default=30, ge=1, le=240, alias="windowMinutes")
    overlap_minutes: int = Field(default=5, ge=0, le=239, alias="overlapMinutes")
    model: CodexModelChoice | None = Field(default=None)
    reasoning_effort: ReasoningEffortChoice | None = Field(
        default=None,
        alias="reasoningEffort",
    )

    @model_validator(mode="after")
    def _overlap_must_be_shorter_than_window(self) -> MicroEventExtractRequest:
        if self.overlap_minutes >= self.window_minutes:
            raise ValueError("overlapMinutes must be shorter than windowMinutes.")
        return self

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "retryFailed": False,
                    "regenerateSucceeded": False,
                    "windowMinutes": 30,
                    "overlapMinutes": 5,
                    "model": "gpt-5.5",
                    "reasoningEffort": "medium",
                }
            ]
        },
    )


class MicroEventBatchExtractRequest(MicroEventExtractRequest):
    limit: int = Field(default=1, ge=1, le=5)

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "limit": 1,
                    "retryFailed": False,
                    "regenerateSucceeded": False,
                    "windowMinutes": 30,
                    "overlapMinutes": 5,
                    "model": "gpt-5.5",
                    "reasoningEffort": "medium",
                }
            ]
        },
    )


class MicroEventExtractResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    video_task_id: int | None = Field(alias="videoTaskId")
    status: str
    reason: str
    model: str | None
    reasoning_effort: str | None = Field(alias="reasoningEffort")
    job_id: int | None = Field(alias="jobId")
    job_attempt_id: int | None = Field(alias="jobAttemptId")
    transcript_id: int | None = Field(alias="transcriptId")
    window_count: int | None = Field(alias="windowCount")
    micro_event_count: int | None = Field(alias="microEventCount")
    asr_correction_candidate_count: int | None = Field(
        alias="asrCorrectionCandidateCount"
    )
    first_cue_id: str | None = Field(alias="firstCueId")
    last_cue_id: str | None = Field(alias="lastCueId")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class MicroEventBatchExtractResponse(BaseModel):
    requested_count: int = Field(alias="requestedCount")
    processed_count: int = Field(alias="processedCount")
    succeeded_count: int = Field(alias="succeededCount")
    failed_count: int = Field(alias="failedCount")
    skipped_count: int = Field(alias="skippedCount")
    timed_out_count: int = Field(alias="timedOutCount")
    scanned_count: int = Field(alias="scannedCount")
    already_satisfied_count: int = Field(alias="alreadySatisfiedCount")
    ineligible_count: int = Field(alias="ineligibleCount")
    items: list[MicroEventExtractResponse]

    model_config = ConfigDict(populate_by_name=True)


class MicroEventCandidateResponse(BaseModel):
    micro_event_candidate_id: int = Field(alias="microEventCandidateId")
    candidate_index: int = Field(alias="candidateIndex")
    activity: Activity
    event: str
    start_cue_id: str = Field(alias="startCueId")
    end_cue_id: str = Field(alias="endCueId")
    evidence_cue_ids: list[str] = Field(alias="evidenceCueIds")
    boundary_before: bool = Field(alias="boundaryBefore")
    boundary_after: bool = Field(alias="boundaryAfter")
    confidence: float
    program_mode: ProgramMode | None = Field(default=None, alias="programMode")
    content_kind: ContentKind | None = Field(default=None, alias="contentKind")
    topics: list[str] | None = None
    relation_to_previous: RelationToPrevious | None = Field(
        default=None,
        alias="relationToPrevious",
    )
    continues_to_next: bool | None = Field(default=None, alias="continuesToNext")
    support_level: SupportLevel | None = Field(default=None, alias="supportLevel")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class AsrCorrectionCandidateResponse(BaseModel):
    asr_correction_candidate_id: int = Field(alias="asrCorrectionCandidateId")
    candidate_index: int = Field(alias="candidateIndex")
    original: str
    suggested: str
    correction_type: CorrectionType = Field(alias="correctionType")
    apply_scope: ApplyScope = Field(alias="applyScope")
    evidence_cue_ids: list[str] = Field(alias="evidenceCueIds")
    confidence: float
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class MicroEventExcludedRangeResponse(BaseModel):
    excluded_range_id: int = Field(alias="excludedRangeId")
    range_index: int = Field(alias="rangeIndex")
    start_cue_id: str = Field(alias="startCueId")
    end_cue_id: str = Field(alias="endCueId")
    reason: ExcludedRangeReason
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class MicroEventExtractionWindowResponse(BaseModel):
    window_id: int = Field(alias="windowId")
    window_index: int = Field(alias="windowIndex")
    start_cue_id: str = Field(alias="startCueId")
    end_cue_id: str = Field(alias="endCueId")
    cue_count: int = Field(alias="cueCount")
    status: WindowStatus
    carry_out_unfinished: bool = Field(alias="carryOutUnfinished")
    codex_thread_id: str | None = Field(alias="codexThreadId")
    codex_turn_id: str | None = Field(alias="codexTurnId")
    raw_response_text: str | None = Field(alias="rawResponseText")
    parsed_response_json: JsonObject | None = Field(alias="parsedResponseJson")
    validation_error: str | None = Field(alias="validationError")
    source_job_id: int | None = Field(alias="sourceJobId")
    source_job_attempt_id: int | None = Field(alias="sourceJobAttemptId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    micro_events: list[MicroEventCandidateResponse] = Field(alias="microEvents")
    excluded_ranges: list[MicroEventExcludedRangeResponse] = Field(
        alias="excludedRanges"
    )
    asr_correction_candidates: list[AsrCorrectionCandidateResponse] = Field(
        alias="asrCorrectionCandidates"
    )

    model_config = ConfigDict(populate_by_name=True)


class MicroEventExtractionDetailResponse(BaseModel):
    video_task_id: int = Field(alias="videoTaskId")
    video_id: int = Field(alias="videoId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    model: str | None
    reasoning_effort: str | None = Field(alias="reasoningEffort")
    transcript_id: int | None = Field(alias="transcriptId")
    status: str
    job_id: int | None = Field(alias="jobId")
    job_attempt_id: int | None = Field(alias="jobAttemptId")
    window_count: int = Field(alias="windowCount")
    micro_event_count: int = Field(alias="microEventCount")
    asr_correction_candidate_count: int = Field(alias="asrCorrectionCandidateCount")
    first_cue_id: str | None = Field(alias="firstCueId")
    last_cue_id: str | None = Field(alias="lastCueId")
    output_json: JsonObject | None = Field(alias="outputJson")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")
    started_at: datetime | None = Field(alias="startedAt")
    completed_at: datetime | None = Field(alias="completedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    windows: list[MicroEventExtractionWindowResponse]

    model_config = ConfigDict(populate_by_name=True)
