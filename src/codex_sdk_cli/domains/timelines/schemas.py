from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskStatus

from .constants import TIMELINE_COMPOSE_DEFAULT_COPY_STYLE
from .ports import (
    CopyStyle,
    JsonObject,
    TimelineBlockType,
    TimelineContentKind,
    TimelineReviewFlagType,
    TimelineViewerTag,
    TimelineVisibility,
)

TimelineComposeEnqueueTarget = Literal["selected_videos", "current_filters", "next_eligible"]
TimelinePatchOperationType = Literal[
    "split_block_after_episode",
    "edit_display_copy",
    "edit_micro_event_copy",
    "edit_topic_cluster_copy",
]
TimelinePatchTargetType = Literal["video", "block", "episode"]


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
    prompt_version_id: int | None = Field(default=None, ge=1, alias="promptVersionId")
    include_non_embeddable: bool = Field(default=False, alias="includeNonEmbeddable")

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
                    "reasoningEffort": "high",
                    "promptVersionId": 1,
                    "includeNonEmbeddable": False,
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
    viewer_tags: list[TimelineViewerTag] = Field(alias="viewerTags")
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


class TimelinePatchAnchorRequest(BaseModel):
    timecode: str | None = Field(default=None, min_length=1, max_length=32)
    display_title: str | None = Field(default=None, min_length=1, alias="displayTitle")
    display_summary: str | None = Field(default=None, min_length=1, alias="displaySummary")

    @model_validator(mode="after")
    def _requires_matcher(self) -> TimelinePatchAnchorRequest:
        if not (self.timecode or self.display_title or self.display_summary):
            raise ValueError("At least one anchor matcher is required.")
        return self

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TimelinePatchNewBlockRequest(BaseModel):
    block_type: TimelineBlockType | None = Field(default=None, alias="blockType")
    title: str | None = Field(default=None, min_length=1)
    summary: str | None = Field(default=None, min_length=1)
    display_title: str | None = Field(default=None, min_length=1, alias="displayTitle")
    display_summary: str | None = Field(default=None, min_length=1, alias="displaySummary")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TimelinePatchOperationRequest(BaseModel):
    operation: TimelinePatchOperationType
    anchor_episode_id: str | None = Field(default=None, min_length=1, alias="anchorEpisodeId")
    anchor: TimelinePatchAnchorRequest | None = None
    new_block: TimelinePatchNewBlockRequest | None = Field(default=None, alias="newBlock")
    target_type: TimelinePatchTargetType | None = Field(default=None, alias="targetType")
    target_id: str | None = Field(default=None, min_length=1, alias="targetId")
    target_topic_id: str | None = Field(default=None, min_length=1, alias="targetTopicId")
    target_micro_event_candidate_id: int | None = Field(
        default=None,
        ge=1,
        alias="targetMicroEventCandidateId",
    )
    expected_episode_id: str | None = Field(default=None, min_length=1, alias="expectedEpisodeId")
    display_title: str | None = Field(default=None, min_length=1, alias="displayTitle")
    display_summary: str | None = Field(default=None, min_length=1, alias="displaySummary")
    display_label: str | None = Field(default=None, min_length=1, alias="displayLabel")
    summary: str | None = Field(default=None, min_length=1)
    event: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_operation_shape(self) -> TimelinePatchOperationRequest:
        if self.operation == "split_block_after_episode":
            if self.anchor_episode_id is None and self.anchor is None:
                raise ValueError("split_block_after_episode requires anchorEpisodeId or anchor.")
            return self
        if self.operation == "edit_micro_event_copy":
            if self.target_micro_event_candidate_id is None:
                raise ValueError("edit_micro_event_copy requires targetMicroEventCandidateId.")
            if self.event is None:
                raise ValueError("edit_micro_event_copy requires event.")
            return self
        if self.operation == "edit_topic_cluster_copy":
            if self.target_topic_id is None:
                raise ValueError("edit_topic_cluster_copy requires targetTopicId.")
            if self.display_label is None and self.summary is None:
                raise ValueError("edit_topic_cluster_copy requires displayLabel or summary.")
            return self
        if self.target_type is None:
            raise ValueError("edit_display_copy requires targetType.")
        if self.target_type in {"block", "episode"} and self.target_id is None:
            raise ValueError("edit_display_copy requires targetId for block or episode.")
        if self.display_title is None and self.display_summary is None:
            raise ValueError("edit_display_copy requires displayTitle or displaySummary.")
        return self

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TimelinePatchPublishRequest(BaseModel):
    enabled: bool = False
    environment: str = Field(default="prod", min_length=1, max_length=64)
    variant: str = Field(default="control", min_length=1, max_length=64)
    schema_version: int = Field(default=1, ge=1, le=100, alias="schemaVersion")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TimelinePatchRequest(BaseModel):
    dry_run: bool = Field(default=True, alias="dryRun")
    instruction: str | None = Field(default=None, max_length=4000)
    operations: list[TimelinePatchOperationRequest] = Field(min_length=1, max_length=20)
    publish: TimelinePatchPublishRequest | None = None

    @model_validator(mode="after")
    def _validate_publish(self) -> TimelinePatchRequest:
        if self.dry_run and self.publish is not None and self.publish.enabled:
            raise ValueError("publish.enabled requires dryRun=false.")
        return self

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "dryRun": True,
                    "instruction": "Split the later post-game conversation into a new block.",
                    "operations": [
                        {
                            "operation": "split_block_after_episode",
                            "anchorEpisodeId": "episode_012",
                            "newBlock": {
                                "blockType": "POST_GAME",
                                "displayTitle": "After the match",
                            },
                        }
                    ],
                }
            ]
        },
    )


class TimelinePatchBlockSummaryResponse(BaseModel):
    block_id: str = Field(alias="blockId")
    block_index: int = Field(alias="blockIndex")
    block_type: TimelineBlockType = Field(alias="blockType")
    display_title: str = Field(alias="displayTitle")
    display_summary: str = Field(alias="displaySummary")
    episode_ids: list[str] = Field(alias="episodeIds")

    model_config = ConfigDict(populate_by_name=True)


class TimelinePatchEpisodeSummaryResponse(BaseModel):
    episode_id: str = Field(alias="episodeId")
    episode_index: int = Field(alias="episodeIndex")
    parent_block_id: str = Field(alias="parentBlockId")
    display_title: str = Field(alias="displayTitle")
    display_summary: str = Field(alias="displaySummary")

    model_config = ConfigDict(populate_by_name=True)


class TimelinePatchTopicClusterSummaryResponse(BaseModel):
    topic_id: str = Field(alias="topicId")
    topic_index: int = Field(alias="topicIndex")
    display_label: str = Field(alias="displayLabel")
    summary: str
    episode_ids: list[str] = Field(alias="episodeIds")

    model_config = ConfigDict(populate_by_name=True)


class TimelinePatchDiffResponse(BaseModel):
    blocks: list[TimelinePatchBlockSummaryResponse]
    episodes: list[TimelinePatchEpisodeSummaryResponse]
    topic_clusters: list[TimelinePatchTopicClusterSummaryResponse] = Field(
        alias="topicClusters",
    )

    model_config = ConfigDict(populate_by_name=True)


class TimelinePatchOperationResultResponse(BaseModel):
    operation: TimelinePatchOperationType
    anchor_episode_id: str | None = Field(default=None, alias="anchorEpisodeId")
    target_type: TimelinePatchTargetType | None = Field(default=None, alias="targetType")
    target_id: str | None = Field(default=None, alias="targetId")
    target_topic_id: str | None = Field(default=None, alias="targetTopicId")
    target_micro_event_candidate_id: int | None = Field(
        default=None,
        alias="targetMicroEventCandidateId",
    )
    changed_block_ids: list[str] = Field(default_factory=list, alias="changedBlockIds")
    changed_episode_ids: list[str] = Field(default_factory=list, alias="changedEpisodeIds")
    changed_topic_ids: list[str] = Field(default_factory=list, alias="changedTopicIds")
    changed_micro_event_candidate_ids: list[int] = Field(
        default_factory=list,
        alias="changedMicroEventCandidateIds",
    )
    new_block_id: str | None = Field(default=None, alias="newBlockId")
    before_event: str | None = Field(default=None, alias="beforeEvent")
    after_event: str | None = Field(default=None, alias="afterEvent")
    message: str

    model_config = ConfigDict(populate_by_name=True)


class TimelinePatchPublishSummaryResponse(BaseModel):
    requested_count: int | None = Field(default=None, alias="requestedCount")
    published_count: int | None = Field(default=None, alias="publishedCount")
    regenerated_count: int | None = Field(default=None, alias="regeneratedCount")
    failed_count: int | None = Field(default=None, alias="failedCount")
    status: str | None = None
    reason: str | None = None
    video_task_id: int | None = Field(default=None, alias="videoTaskId")
    artifact_id: int | None = Field(default=None, alias="artifactId")
    public_url: str | None = Field(default=None, alias="publicUrl")
    error_type: str | None = Field(default=None, alias="errorType")
    error_message: str | None = Field(default=None, alias="errorMessage")

    model_config = ConfigDict(populate_by_name=True)


class TimelinePatchResponse(BaseModel):
    video_id: int = Field(alias="videoId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    video_task_id: int = Field(alias="videoTaskId")
    timeline_composition_id: int = Field(alias="timelineCompositionId")
    source_micro_event_task_id: int = Field(alias="sourceMicroEventTaskId")
    dry_run: bool = Field(alias="dryRun")
    applied: bool
    operations: list[TimelinePatchOperationResultResponse]
    before: TimelinePatchDiffResponse
    after: TimelinePatchDiffResponse
    validation_warnings: list[str] = Field(alias="validationWarnings")
    publish_result: JsonObject | None = Field(default=None, alias="publishResult")
    publish_summary: TimelinePatchPublishSummaryResponse | None = Field(
        default=None,
        alias="publishSummary",
    )

    model_config = ConfigDict(populate_by_name=True)
