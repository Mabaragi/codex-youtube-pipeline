from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskStatus

JsonObject = dict[str, object]

CopyStyle = Literal["LIGHT_FANDOM_V1"]
TimelineBlockType = Literal[
    "PRE_ROLL",
    "OPENING",
    "JUST_CHATTING",
    "COMMUNITY_REVIEW",
    "MEDIA_REVIEW",
    "GAME_SETUP",
    "GAMEPLAY",
    "BREAK",
    "POST_GAME",
    "CLOSING",
    "MIXED",
]
TimelineContentKind = Literal[
    "ANNOUNCEMENT",
    "PERSONAL_STORY",
    "OPINION",
    "QNA",
    "REACTION",
    "TECHNICAL_SETUP",
    "GAME_PROGRESS",
    "GAME_DISCUSSION",
    "COMMUNITY_REVIEW",
    "MEDIA_REVIEW",
    "META_CHAT",
    "BREAK_TIME",
    "OTHER",
]
TimelineVisibility = Literal["DEFAULT", "COLLAPSED", "HIDDEN"]
TimelineViewerTag = Literal[
    "STORY",
    "FUNNY",
    "REACTION",
    "INFORMATION",
    "FOOD",
    "GAME_PROGRESS",
    "GAME_STORY",
    "GAME_DISCUSSION",
    "COMMUNITY",
    "MEDIA",
    "ANNOUNCEMENT",
    "META",
    "QNA",
]
TimelineReviewFlagType = Literal[
    "MODE_CONFLICT",
    "BOUNDARY_AMBIGUOUS",
    "ASR_SEMANTIC_RISK",
    "OVERBROAD_EPISODE",
    "OVERBROAD_MICRO_EVENT",
    "POSSIBLE_DUPLICATE",
]


@dataclass(frozen=True, slots=True)
class TimelineComposeRequest:
    prompt: str
    video_id: int
    video_task_id: int
    job_id: int
    job_attempt_id: int
    source_micro_event_task_id: int
    model: CodexModelChoice | None
    reasoning_effort: ReasoningEffortChoice | None


@dataclass(frozen=True, slots=True)
class TimelineComposeResult:
    thread_id: str | None
    turn_id: str | None
    status: str
    final_response: str


@dataclass(frozen=True, slots=True)
class TimelineEpisodeRepairRequest:
    prompt: str
    video_id: int
    video_task_id: int
    job_id: int
    job_attempt_id: int
    source_micro_event_task_id: int
    target_episode_id: str
    model: CodexModelChoice | None
    reasoning_effort: ReasoningEffortChoice | None


@dataclass(frozen=True, slots=True)
class TimelineEpisodeRepairResult:
    thread_id: str | None
    turn_id: str | None
    status: str
    final_response: str


class TimelineComposerPort(Protocol):
    async def compose(self, request: TimelineComposeRequest) -> TimelineComposeResult:
        """Compose one video timeline from micro-events."""

    async def repair_episode(
        self,
        request: TimelineEpisodeRepairRequest,
    ) -> TimelineEpisodeRepairResult:
        """Repair one overbroad timeline episode without recomposing the full video."""


@dataclass(frozen=True, slots=True)
class TimelineBlockCreate:
    block_id: str
    block_index: int
    block_type: TimelineBlockType
    title: str
    summary: str
    display_title: str
    display_summary: str
    episode_ids: list[str]


@dataclass(frozen=True, slots=True)
class TimelineEpisodeCreate:
    episode_id: str
    episode_index: int
    parent_block_id: str
    start_micro_event_candidate_id: int | None
    end_micro_event_candidate_id: int | None
    program_mode: TimelineBlockType
    primary_content_kind: TimelineContentKind
    title: str
    summary: str
    display_title: str
    display_summary: str
    topics: list[str]
    viewer_tags: list[TimelineViewerTag]
    highlight_micro_event_candidate_ids: list[int]
    visibility: TimelineVisibility


@dataclass(frozen=True, slots=True)
class TimelineTopicClusterCreate:
    topic_id: str
    topic_index: int
    label: str
    summary: str
    display_label: str
    episode_ids: list[str]


@dataclass(frozen=True, slots=True)
class TimelineReviewFlagCreate:
    flag_index: int
    start_micro_event_candidate_id: int | None
    end_micro_event_candidate_id: int | None
    type: TimelineReviewFlagType
    reason: str


@dataclass(frozen=True, slots=True)
class TimelineCompositionCreate:
    video_task_id: int
    video_id: int
    source_micro_event_task_id: int
    source_micro_event_fingerprint: str
    copy_style: CopyStyle
    model: str | None
    reasoning_effort: str | None
    title: str
    summary: str
    display_title: str
    display_summary: str
    main_topics: list[str]
    output_json: JsonObject
    validation_warnings: list[str]
    source_job_id: int | None
    source_job_attempt_id: int | None
    codex_thread_id: str | None
    codex_turn_id: str | None
    raw_response_text: str | None
    blocks: list[TimelineBlockCreate] = field(default_factory=list)
    episodes: list[TimelineEpisodeCreate] = field(default_factory=list)
    topic_clusters: list[TimelineTopicClusterCreate] = field(default_factory=list)
    review_flags: list[TimelineReviewFlagCreate] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TimelineBlockRecord(TimelineBlockCreate):
    id: int
    composition_id: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TimelineEpisodeRecord(TimelineEpisodeCreate):
    id: int
    composition_id: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TimelineTopicClusterRecord(TimelineTopicClusterCreate):
    id: int
    composition_id: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TimelineReviewFlagRecord(TimelineReviewFlagCreate):
    id: int
    composition_id: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TimelineCompositionRecord:
    id: int
    video_task_id: int
    video_id: int
    youtube_video_id: str
    source_micro_event_task_id: int
    source_micro_event_fingerprint: str
    copy_style: CopyStyle
    status: VideoTaskStatus
    model: str | None
    reasoning_effort: str | None
    title: str
    summary: str
    display_title: str
    display_summary: str
    main_topics: list[str]
    output_json: JsonObject
    validation_warnings: list[str]
    source_job_id: int | None
    source_job_attempt_id: int | None
    codex_thread_id: str | None
    codex_turn_id: str | None
    raw_response_text: str | None
    created_at: datetime
    updated_at: datetime
    blocks: list[TimelineBlockRecord] = field(default_factory=list)
    episodes: list[TimelineEpisodeRecord] = field(default_factory=list)
    topic_clusters: list[TimelineTopicClusterRecord] = field(default_factory=list)
    review_flags: list[TimelineReviewFlagRecord] = field(default_factory=list)


class TimelineCompositionRepositoryPort(Protocol):
    async def delete_composition(self, video_task_id: int) -> None:
        """Delete persisted timeline rows for one task."""

    async def replace_composition(
        self,
        create: TimelineCompositionCreate,
    ) -> TimelineCompositionRecord | None:
        """Replace all timeline rows for one task."""

    async def get_composition(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> TimelineCompositionRecord | None:
        """Return one timeline composition."""

    async def get_latest_succeeded_composition(
        self,
        *,
        video_id: int,
    ) -> TimelineCompositionRecord | None:
        """Return the latest succeeded timeline composition."""
