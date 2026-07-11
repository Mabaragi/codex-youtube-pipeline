from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_sdk_cli.application.operations.results import OperationBatchResult
from codex_sdk_cli.application.operations.selection import (
    ChannelVideos,
    FilteredVideos,
    NextEligibleVideos,
    SelectedVideos,
    VideoSelection,
)


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


class TranscriptCueOperationRequest(BaseModel):
    selection: VideoSelectionRequest
    retry_failed: bool = Field(default=False, alias="retryFailed")
    rerun_succeeded: bool = Field(default=False, alias="rerunSucceeded")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")
    timeout_seconds: int = Field(default=600, alias="timeoutSeconds", ge=1, le=3600)

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
