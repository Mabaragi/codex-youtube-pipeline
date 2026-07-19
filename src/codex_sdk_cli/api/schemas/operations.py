from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_sdk_cli.application.channels.commands import ResolveChannelResult
from codex_sdk_cli.application.operations.results import (
    ChannelOperationBatchResult,
    OperationBatchResult,
)
from codex_sdk_cli.application.operations.selection import (
    ChannelVideos,
    FilteredVideos,
    NextEligibleVideos,
    SelectedVideos,
    VideoSelection,
)
from codex_sdk_cli.application.workflows.models import WorkflowBatchResult
from codex_sdk_cli.domains.codex.choices import (
    DEFAULT_MICRO_EVENT_MODEL,
    DEFAULT_MICRO_EVENT_REASONING_EFFORT,
    DEFAULT_TIMELINE_MODEL,
    DEFAULT_TIMELINE_REASONING_EFFORT,
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.timelines.ports import CopyStyle


class SelectedVideoSelectionRequest(BaseModel):
    type: Literal["selected"]
    video_ids: tuple[int, ...] = Field(alias="videoIds", min_length=1, max_length=200)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ChannelVideoSelectionRequest(BaseModel):
    type: Literal["channel"]
    channel_id: int = Field(alias="channelId", ge=1)
    limit: int = Field(default=50, ge=1, le=200)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class FilterVideoSelectionRequest(BaseModel):
    type: Literal["filter"]
    channel_id: int | None = Field(default=None, alias="channelId", ge=1)
    search: str | None = Field(default=None, min_length=1, max_length=200)
    limit: int = Field(default=50, ge=1, le=200)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class NextEligibleVideoSelectionRequest(BaseModel):
    type: Literal["nextEligible"]
    limit: int = Field(default=20, ge=1, le=200)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


VideoSelectionRequest = Annotated[
    SelectedVideoSelectionRequest
    | ChannelVideoSelectionRequest
    | FilterVideoSelectionRequest
    | NextEligibleVideoSelectionRequest,
    Field(discriminator="type"),
]


class TranscriptCollectOperationRequest(BaseModel):
    selection: VideoSelectionRequest
    languages: tuple[str, ...] = Field(default=("ko", "en"), min_length=1, max_length=10)
    preserve_formatting: bool = Field(default=False, alias="preserveFormatting")
    retry_failed: bool = Field(default=False, alias="retryFailed")
    recheck_no_transcript: bool = Field(default=False, alias="recheckNoTranscript")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")
    timeout_seconds: int = Field(default=600, alias="timeoutSeconds", ge=1, le=3600)

    @model_validator(mode="after")
    def normalize_languages(self) -> TranscriptCollectOperationRequest:
        normalized = tuple(dict.fromkeys(language.strip() for language in self.languages))
        if not all(normalized):
            raise ValueError("languages must contain non-empty values.")
        self.languages = normalized
        return self

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class VideoCollectOperationRequest(BaseModel):
    channel_ids: tuple[int, ...] = Field(alias="channelIds", min_length=1, max_length=200)
    retry_failed: bool = Field(default=False, alias="retryFailed")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    timeout_seconds: int = Field(default=600, alias="timeoutSeconds", ge=1, le=3600)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ChannelResolveOperationRequest(BaseModel):
    streamer_id: int = Field(alias="streamerId", ge=1)
    handle: str = Field(min_length=1, max_length=255)
    retry_failed: bool = Field(default=False, alias="retryFailed")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    timeout_seconds: int = Field(default=120, alias="timeoutSeconds", ge=1, le=600)

    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)


class TranscriptCueOperationRequest(BaseModel):
    selection: VideoSelectionRequest
    retry_failed: bool = Field(default=False, alias="retryFailed")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")
    timeout_seconds: int = Field(default=600, alias="timeoutSeconds", ge=1, le=3600)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class MicroEventOperationRequest(BaseModel):
    selection: VideoSelectionRequest
    window_minutes: int = Field(default=30, alias="windowMinutes", ge=1, le=240)
    overlap_minutes: int = Field(default=5, alias="overlapMinutes", ge=0, le=239)
    model: CodexModelChoice = DEFAULT_MICRO_EVENT_MODEL
    reasoning_effort: ReasoningEffortChoice = Field(
        default=DEFAULT_MICRO_EVENT_REASONING_EFFORT,
        alias="reasoningEffort",
    )
    prompt_version_id: int | None = Field(default=None, alias="promptVersionId", ge=1)
    retry_failed: bool = Field(default=False, alias="retryFailed")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")
    timeout_seconds: int = Field(default=3600, alias="timeoutSeconds", ge=1, le=7200)

    @model_validator(mode="after")
    def validate_overlap(self) -> MicroEventOperationRequest:
        if self.overlap_minutes >= self.window_minutes:
            raise ValueError("overlapMinutes must be shorter than windowMinutes.")
        return self

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TimelineOperationRequest(BaseModel):
    selection: VideoSelectionRequest
    model: CodexModelChoice = DEFAULT_TIMELINE_MODEL
    reasoning_effort: ReasoningEffortChoice = Field(
        default=DEFAULT_TIMELINE_REASONING_EFFORT,
        alias="reasoningEffort",
    )
    copy_style: Annotated[CopyStyle, Field(alias="copyStyle")] = "LIGHT_FANDOM_V1"
    prompt_version_id: int | None = Field(default=None, alias="promptVersionId", ge=1)
    retry_failed: bool = Field(default=False, alias="retryFailed")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")
    timeout_seconds: int = Field(default=3600, alias="timeoutSeconds", ge=1, le=7200)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TranscriptFallbackRequest(BaseModel):
    mode: Literal["disabled", "asr_after_grace"] = "asr_after_grace"
    grace_seconds: int = Field(default=21600, alias="graceSeconds", ge=0, le=604800)
    recheck_interval_seconds: int = Field(
        default=1800,
        alias="recheckIntervalSeconds",
        ge=60,
        le=604800,
    )
    model: str = Field(default="turbo", min_length=1, max_length=64)
    language: str = Field(default="ko", min_length=2, max_length=16)
    device: Literal["cuda", "cpu", "auto"] = "cuda"
    compute_type: str = Field(default="auto", alias="computeType", min_length=1, max_length=32)
    chunk_minutes: int = Field(default=15, alias="chunkMinutes", ge=1, le=60)
    overlap_seconds: int = Field(default=3, alias="overlapSeconds", ge=0, le=30)
    beam_size: int = Field(default=5, alias="beamSize", ge=1, le=20)
    vad_filter: bool = Field(default=True, alias="vadFilter")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ProcessToPublishOperationRequest(BaseModel):
    selection: VideoSelectionRequest
    languages: tuple[str, ...] = Field(default=("ko", "en"), min_length=1, max_length=10)
    preserve_formatting: bool = Field(default=False, alias="preserveFormatting")
    micro_window_minutes: int = Field(default=30, alias="microWindowMinutes", ge=1, le=240)
    micro_overlap_minutes: int = Field(default=5, alias="microOverlapMinutes", ge=0, le=239)
    micro_model: Annotated[CodexModelChoice, Field(alias="microModel")] = (
        DEFAULT_MICRO_EVENT_MODEL
    )
    micro_reasoning_effort: ReasoningEffortChoice = Field(
        default=DEFAULT_MICRO_EVENT_REASONING_EFFORT,
        alias="microReasoningEffort",
    )
    micro_prompt_version_id: int | None = Field(
        default=None, alias="microPromptVersionId", ge=1
    )
    timeline_model: Annotated[CodexModelChoice, Field(alias="timelineModel")] = (
        DEFAULT_TIMELINE_MODEL
    )
    timeline_reasoning_effort: ReasoningEffortChoice = Field(
        default=DEFAULT_TIMELINE_REASONING_EFFORT,
        alias="timelineReasoningEffort",
    )
    timeline_prompt_version_id: int | None = Field(
        default=None, alias="timelinePromptVersionId", ge=1
    )
    transcript_fallback: TranscriptFallbackRequest = Field(
        default_factory=TranscriptFallbackRequest,
        alias="transcriptFallback",
    )
    publish_mode: Literal["prod", "dev"] = Field(default="prod", alias="publishMode")
    environment: str = Field(default="prod", min_length=1, max_length=64)
    variant: str = Field(default="control", min_length=1, max_length=64)
    schema_version: int = Field(default=1, alias="schemaVersion", ge=1, le=100)
    retry_failed: bool = Field(default=False, alias="retryFailed")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")

    @model_validator(mode="after")
    def validate_window_and_mode(self) -> ProcessToPublishOperationRequest:
        if self.micro_overlap_minutes >= self.micro_window_minutes:
            raise ValueError("microOverlapMinutes must be shorter than microWindowMinutes.")
        if self.publish_mode == "dev" and self.environment == "prod":
            raise ValueError("publishMode=dev cannot publish to environment=prod.")
        return self

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ArchivePublishOperationRequest(BaseModel):
    selection: VideoSelectionRequest
    publish_mode: Literal["prod", "dev"] = Field(default="prod", alias="publishMode")
    environment: str = Field(default="prod", min_length=1, max_length=64)
    variant: str = Field(default="control", min_length=1, max_length=64)
    schema_version: int = Field(default=1, alias="schemaVersion", ge=1, le=100)
    retry_failed: bool = Field(default=False, alias="retryFailed")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")
    timeout_seconds: int = Field(default=600, alias="timeoutSeconds", ge=1, le=3600)

    @model_validator(mode="after")
    def validate_publish_mode(self) -> ArchivePublishOperationRequest:
        if self.publish_mode == "dev" and self.environment == "prod":
            raise ValueError("publishMode=dev cannot publish to environment=prod.")
        return self

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class OperationItemResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str | None = Field(alias="youtubeVideoId")
    status: str
    reason: str
    work_item_id: int | None = Field(alias="workItemId")
    error_code: str | None = Field(default=None, alias="errorCode")
    error_message: str | None = Field(default=None, alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class OperationBatchResponse(BaseModel):
    batch_id: int = Field(alias="batchId")
    requested_count: int = Field(alias="requestedCount")
    created_count: int = Field(alias="createdCount")
    reused_count: int = Field(alias="reusedCount")
    skipped_count: int = Field(alias="skippedCount")
    items: tuple[OperationItemResponse, ...]

    model_config = ConfigDict(populate_by_name=True)


class WorkflowSelectionItemResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str | None = Field(alias="youtubeVideoId")
    status: str
    reason: str
    workflow_run_id: int | None = Field(alias="workflowRunId")

    model_config = ConfigDict(populate_by_name=True)


class WorkflowBatchResponse(BaseModel):
    batch_id: int = Field(alias="batchId")
    requested_count: int = Field(alias="requestedCount")
    created_count: int = Field(alias="createdCount")
    reused_count: int = Field(alias="reusedCount")
    skipped_count: int = Field(alias="skippedCount")
    items: tuple[WorkflowSelectionItemResponse, ...]

    model_config = ConfigDict(populate_by_name=True)


class ChannelOperationItemResponse(BaseModel):
    channel_id: int = Field(alias="channelId")
    status: str
    reason: str
    work_item_id: int | None = Field(alias="workItemId")
    output: dict[str, object] | None
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class ChannelOperationBatchResponse(BaseModel):
    batch_id: int = Field(alias="batchId")
    requested_count: int = Field(alias="requestedCount")
    succeeded_count: int = Field(alias="succeededCount")
    failed_count: int = Field(alias="failedCount")
    skipped_count: int = Field(alias="skippedCount")
    items: tuple[ChannelOperationItemResponse, ...]

    model_config = ConfigDict(populate_by_name=True)


class ChannelResolveOperationResponse(BaseModel):
    batch_id: int = Field(alias="batchId")
    work_item_id: int = Field(alias="workItemId")
    status: str
    reason: str
    output: dict[str, object] | None
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


def to_selection(request: VideoSelectionRequest) -> VideoSelection:
    if isinstance(request, SelectedVideoSelectionRequest):
        return SelectedVideos(request.video_ids)
    if isinstance(request, ChannelVideoSelectionRequest):
        return ChannelVideos(request.channel_id, request.limit)
    if isinstance(request, FilterVideoSelectionRequest):
        return FilteredVideos(request.channel_id, request.search, request.limit)
    return NextEligibleVideos(request.limit)


def operation_response(result: OperationBatchResult) -> OperationBatchResponse:
    return OperationBatchResponse.model_validate(result, from_attributes=True)


def workflow_batch_response(result: WorkflowBatchResult) -> WorkflowBatchResponse:
    return WorkflowBatchResponse.model_validate(result, from_attributes=True)


def channel_operation_response(
    result: ChannelOperationBatchResult,
) -> ChannelOperationBatchResponse:
    return ChannelOperationBatchResponse.model_validate(result, from_attributes=True)


def channel_resolve_response(
    result: ResolveChannelResult,
) -> ChannelResolveOperationResponse:
    return ChannelResolveOperationResponse.model_validate(result, from_attributes=True)
