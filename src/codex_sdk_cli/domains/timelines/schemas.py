from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_sdk_cli.domains.video_tasks.ports import VideoTaskStatus
from codex_sdk_cli.settings import CodexModelChoice, ReasoningEffortChoice

from .constants import TIMELINE_COMPOSE_DEFAULT_COPY_STYLE
from .ports import (
    CopyStyle,
    JsonObject,
    TimelineBlockType,
    TimelineContentKind,
    TimelineReviewFlagType,
    TimelineVisibility,
)

TimelineComposeEnqueueTarget = Literal["selected_videos", "current_filters", "next_eligible"]


class TimelineComposeEnqueueRequest(BaseModel):
    target: TimelineComposeEnqueueTarget = "next_eligible"
    video_ids: list[int] = Field(default_factory=list, max_length=200, alias="videoIds")
    channel_id: int | None = Field(default=None, ge=1, alias="channelId")
    task_status: VideoTaskStatus | None = Field(default=None, alias="taskStatus")
    search: str | None = Field(default=None, min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=200)
    retry_failed: bool = Field(default=False, alias="retryFailed")
    regenerate_succeeded: bool = Field(default=False, alias="regenerateSucceeded")
    model: CodexModelChoice | None = None
    reasoning_effort: ReasoningEffortChoice | None = Field(
        default=None,
        alias="reasoningEffort",
    )
    copy_style: CopyStyle = Field(
        default=TIMELINE_COMPOSE_DEFAULT_COPY_STYLE,
        alias="copyStyle",
    )

    @model_validator(mode="after")
    def _selected_videos_require_ids(self) -> TimelineComposeEnqueueRequest:
        if self.target == "selected_videos" and not self.video_ids:
            raise ValueError("videoIds is required when target is selected_videos.")
        return self

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "target": "next_eligible",
                    "limit": 5,
                    "retryFailed": False,
                    "regenerateSucceeded": False,
                    "copyStyle": "LIGHT_FANDOM_V1",
                    "model": "gpt-5.5",
                    "reasoningEffort": "medium",
                }
            ]
        },
    )


class TimelineComposeEnqueueItemResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str | None = Field(alias="youtubeVideoId")
    video_task_id: int | None = Field(alias="videoTaskId")
    status: str
    reason: str
    source_micro_event_task_id: int | None = Field(alias="sourceMicroEventTaskId")
    model: str | None
    reasoning_effort: str | None = Field(alias="reasoningEffort")
    copy_style: str | None = Field(alias="copyStyle")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class TimelineComposeEnqueueResponse(BaseModel):
    requested_count: int = Field(alias="requestedCount")
    scanned_count: int = Field(alias="scannedCount")
    enqueued_count: int = Field(alias="enqueuedCount")
    already_pending_count: int = Field(alias="alreadyPendingCount")
    already_running_count: int = Field(alias="alreadyRunningCount")
    already_succeeded_count: int = Field(alias="alreadySucceededCount")
    retry_queued_count: int = Field(alias="retryQueuedCount")
    regenerated_count: int = Field(alias="regeneratedCount")
    failed_skipped_count: int = Field(alias="failedSkippedCount")
    ineligible_count: int = Field(alias="ineligibleCount")
    items: list[TimelineComposeEnqueueItemResponse]

    model_config = ConfigDict(populate_by_name=True)


class TimelineBlockResponse(BaseModel):
    block_id: str = Field(alias="blockId")
    block_index: int = Field(alias="blockIndex")
    block_type: TimelineBlockType = Field(alias="blockType")
    title: str
    summary: str
    display_title: str = Field(alias="displayTitle")
    display_summary: str = Field(alias="displaySummary")
    episode_ids: list[str] = Field(alias="episodeIds")

    model_config = ConfigDict(populate_by_name=True)


class TimelineEpisodeResponse(BaseModel):
    episode_id: str = Field(alias="episodeId")
    episode_index: int = Field(alias="episodeIndex")
    parent_block_id: str = Field(alias="parentBlockId")
    start_micro_event_candidate_id: int | None = Field(alias="startMicroEventCandidateId")
    end_micro_event_candidate_id: int | None = Field(alias="endMicroEventCandidateId")
    program_mode: TimelineBlockType = Field(alias="programMode")
    primary_content_kind: TimelineContentKind = Field(alias="primaryContentKind")
    title: str
    summary: str
    display_title: str = Field(alias="displayTitle")
    display_summary: str = Field(alias="displaySummary")
    topics: list[str]
    viewer_tags: list[str] = Field(alias="viewerTags")
    highlight_micro_event_candidate_ids: list[int] = Field(
        alias="highlightMicroEventCandidateIds"
    )
    visibility: TimelineVisibility

    model_config = ConfigDict(populate_by_name=True)


class TimelineTopicClusterResponse(BaseModel):
    topic_id: str = Field(alias="topicId")
    topic_index: int = Field(alias="topicIndex")
    label: str
    summary: str
    display_label: str = Field(alias="displayLabel")
    episode_ids: list[str] = Field(alias="episodeIds")

    model_config = ConfigDict(populate_by_name=True)


class TimelineReviewFlagResponse(BaseModel):
    flag_index: int = Field(alias="flagIndex")
    start_micro_event_candidate_id: int | None = Field(alias="startMicroEventCandidateId")
    end_micro_event_candidate_id: int | None = Field(alias="endMicroEventCandidateId")
    type: TimelineReviewFlagType
    reason: str

    model_config = ConfigDict(populate_by_name=True)


class TimelineCompositionResponse(BaseModel):
    video_task_id: int = Field(alias="videoTaskId")
    video_id: int = Field(alias="videoId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    source_micro_event_task_id: int = Field(alias="sourceMicroEventTaskId")
    source_micro_event_fingerprint: str = Field(alias="sourceMicroEventFingerprint")
    copy_style: CopyStyle = Field(alias="copyStyle")
    status: VideoTaskStatus
    model: str | None
    reasoning_effort: str | None = Field(alias="reasoningEffort")
    title: str
    summary: str
    display_title: str = Field(alias="displayTitle")
    display_summary: str = Field(alias="displaySummary")
    main_topics: list[str] = Field(alias="mainTopics")
    validation_warnings: list[str] = Field(alias="validationWarnings")
    output_json: JsonObject = Field(alias="outputJson")
    blocks: list[TimelineBlockResponse]
    episodes: list[TimelineEpisodeResponse]
    topic_clusters: list[TimelineTopicClusterResponse] = Field(alias="topicClusters")
    review_flags: list[TimelineReviewFlagResponse] = Field(alias="reviewFlags")

    model_config = ConfigDict(populate_by_name=True)
