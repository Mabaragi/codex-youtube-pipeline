from __future__ import annotations

from dataclasses import dataclass

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from codex_sdk_cli.domains.codex.choices import (
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainKnowledgePromptEntryRecord,
)
from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventCandidateRecord,
    MicroEventExtractionDetailRecord,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord
from codex_sdk_cli.domains.videos.ports import VideoRecord

from .ports import CopyStyle, TimelineBlockType, TimelineEpisodeCreate


@dataclass(frozen=True, slots=True)
class _PreparedTimelineCompose:
    video: VideoRecord
    source_task: VideoTaskRecord
    source_detail: MicroEventExtractionDetailRecord
    input_hash: str
    input_json: JsonObject
    model: CodexModelChoice
    reasoning_effort: ReasoningEffortChoice
    copy_style: CopyStyle
    prompt: ResolvedPrompt


@dataclass(slots=True)
class _EnqueueCounters:
    scanned_count: int = 0
    enqueued_count: int = 0
    already_pending_count: int = 0
    already_running_count: int = 0
    already_succeeded_count: int = 0
    retry_queued_count: int = 0
    regenerated_count: int = 0
    failed_skipped_count: int = 0
    ineligible_count: int = 0


@dataclass(frozen=True, slots=True)
class _ComposerInput:
    video: VideoRecord
    streamer_name: str | None
    domain_entries: list[DomainKnowledgePromptEntryRecord]
    source_task: VideoTaskRecord
    source_detail: MicroEventExtractionDetailRecord
    micro_events: list[MicroEventCandidateRecord]
    synthetic_id_by_candidate_id: dict[int, str]
    candidate_id_by_synthetic_id: dict[str, int]
    input_json: JsonObject
    input_hash: str
    model: CodexModelChoice
    reasoning_effort: ReasoningEffortChoice
    copy_style: CopyStyle
    compose_prompt: ResolvedPrompt
    repair_prompt: ResolvedPrompt


@dataclass(frozen=True, slots=True)
class _TimelineRawResponse:
    operation: str
    thread_id: str | None
    turn_id: str | None
    status: str
    raw_response_text: str
    target_episode_id: str | None = None


@dataclass(frozen=True, slots=True)
class _CoverageRepairPlan:
    target_episode: TimelineEpisodeCreate
    target_candidates: list[MicroEventCandidateRecord]
    replace_start_index: int
    replace_end_index: int
    insert_before_episode_id: str | None


@dataclass(frozen=True, slots=True)
class _BlockSegment:
    block_type: TimelineBlockType
    title: str
    summary: str
    display_title: str
    display_summary: str
    episodes: list[TimelineEpisodeCreate]


class _VideoSummaryOutput(BaseModel):
    title: str = ""
    summary: str = ""
    display_title: str = ""
    display_summary: str = ""
    main_topics: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class _TimelineBlockOutput(BaseModel):
    block_id: str = ""
    block_type: str = "MIXED"
    title: str = ""
    summary: str = ""
    display_title: str = ""
    display_summary: str = ""
    episode_ids: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class _TimelineEpisodeOutput(BaseModel):
    episode_id: str = ""
    parent_block_id: str = ""
    start_micro_event_id: str = ""
    end_micro_event_id: str = ""
    program_mode: str = "MIXED"
    primary_content_kind: str = "OTHER"
    title: str = ""
    summary: str = ""
    display_title: str = ""
    display_summary: str = ""
    topics: list[str] = Field(default_factory=list)
    viewer_tags: list[str] = Field(default_factory=list)
    highlight_micro_event_ids: list[str] = Field(default_factory=list)
    visibility: str = "DEFAULT"

    model_config = ConfigDict(extra="ignore")


class _TimelineTopicClusterOutput(BaseModel):
    topic_id: str = Field(
        default="",
        validation_alias=AliasChoices("topic_id", "topicId", "cluster_id", "clusterId"),
    )
    label: str = Field(default="", validation_alias=AliasChoices("label", "title"))
    summary: str = ""
    display_label: str = Field(
        default="",
        validation_alias=AliasChoices("display_label", "displayLabel", "title"),
    )
    episode_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("episode_ids", "episodeIds"),
    )

    model_config = ConfigDict(extra="ignore")


class _TimelineReviewFlagOutput(BaseModel):
    start_micro_event_id: str = ""
    end_micro_event_id: str = ""
    type: str = "BOUNDARY_AMBIGUOUS"
    reason: str = ""

    model_config = ConfigDict(extra="ignore")


class _TimelineOutput(BaseModel):
    video_summary: _VideoSummaryOutput = Field(default_factory=_VideoSummaryOutput)
    blocks: list[_TimelineBlockOutput] = Field(default_factory=list)
    episodes: list[_TimelineEpisodeOutput] = Field(default_factory=list)
    topic_clusters: list[_TimelineTopicClusterOutput] = Field(default_factory=list)
    review_flags: list[_TimelineReviewFlagOutput] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class _TimelineRepairEpisodeOutput(BaseModel):
    start_micro_event_id: str = ""
    end_micro_event_id: str = ""
    program_mode: str = "MIXED"
    primary_content_kind: str = "OTHER"
    title: str = ""
    summary: str = ""
    display_title: str = ""
    display_summary: str = ""
    topics: list[str] = Field(default_factory=list)
    viewer_tags: list[str] = Field(default_factory=list)
    highlight_micro_event_ids: list[str] = Field(default_factory=list)
    visibility: str = "DEFAULT"

    model_config = ConfigDict(extra="ignore")


class _TimelineEpisodeRepairOutput(BaseModel):
    target_episode_id: str = ""
    action: str = "KEEP"
    replacement_episodes: list[_TimelineRepairEpisodeOutput] = Field(default_factory=list)
    reason: str = ""

    model_config = ConfigDict(extra="ignore")
