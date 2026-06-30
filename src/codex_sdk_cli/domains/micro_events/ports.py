from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskStatus

JsonObject = dict[str, object]
WindowStatus = Literal["succeeded", "failed"]
Activity = Literal[
    "PRE_ROLL",
    "OPENING",
    "JUST_CHATTING",
    "ANNOUNCEMENT",
    "COMMUNITY_REVIEW",
    "MEDIA_REVIEW",
    "GAME_SETUP",
    "GAMEPLAY",
    "BREAK",
    "POST_GAME",
    "CLOSING",
    "UNKNOWN",
]
ProgramMode = Literal[
    "OPENING",
    "JUST_CHATTING",
    "GAME_SETUP",
    "GAMEPLAY",
    "BREAK",
    "POST_GAME",
    "CLOSING",
    "UNKNOWN",
]
ContentKind = Literal[
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
    "OTHER",
]
RelationToPrevious = Literal["NEW_TOPIC", "CONTINUATION", "ASIDE", "RETURN"]
SupportLevel = Literal["DIRECT", "CONTEXTUAL", "AMBIGUOUS"]
ExcludedRangeReason = Literal[
    "MUSIC_ONLY",
    "SILENCE_OR_GAP",
    "UNINTELLIGIBLE",
    "LOW_INFORMATION",
    "TECHNICAL_NOISE",
]
CorrectionType = Literal[
    "PROPER_NOUN",
    "GAME_TITLE",
    "CONTENT_TITLE",
    "COMMON_WORD",
    "FOOD",
    "PLACE",
    "STREAM_TERM",
    "CONTEXTUAL_TERM",
    "UNCERTAIN",
]
ApplyScope = Literal[
    "NONE",
    "SEARCH_ONLY",
    "SEARCH_AND_SUMMARY",
    "DISPLAY_ALLOWED",
]


@dataclass(frozen=True, slots=True)
class MicroEventExtractionRequest:
    prompt: str
    video_id: int | None = None
    video_task_id: int | None = None
    job_id: int | None = None
    job_attempt_id: int | None = None
    transcript_id: int | None = None
    window_index: int | None = None
    model: CodexModelChoice | None = None
    reasoning_effort: ReasoningEffortChoice | None = None


@dataclass(frozen=True, slots=True)
class MicroEventRepairRequest:
    prompt: str
    original_prompt: str
    original_response: str
    validation_error: str
    owned_start_cue_id: str
    owned_end_cue_id: str
    owned_cue_ids: list[str]
    video_id: int | None = None
    video_task_id: int | None = None
    job_id: int | None = None
    job_attempt_id: int | None = None
    transcript_id: int | None = None
    window_index: int | None = None
    model: CodexModelChoice | None = None
    reasoning_effort: ReasoningEffortChoice | None = None


@dataclass(frozen=True, slots=True)
class MicroEventExtractionResult:
    thread_id: str
    turn_id: str
    status: str
    final_response: str


class MicroEventExtractorPort(Protocol):
    async def extract_window(
        self,
        request: MicroEventExtractionRequest,
    ) -> MicroEventExtractionResult:
        """Extract candidate events from one transcript cue window."""

    async def repair_window(
        self,
        request: MicroEventRepairRequest,
    ) -> MicroEventExtractionResult:
        """Repair one invalid extraction response so it satisfies window invariants."""


@dataclass(frozen=True, slots=True)
class MicroEventCandidateCreate:
    candidate_index: int
    activity: Activity
    event: str
    start_cue_id: str
    end_cue_id: str
    evidence_cue_ids: list[str]
    boundary_before: bool
    boundary_after: bool
    confidence: float
    program_mode: ProgramMode | None = None
    content_kind: ContentKind | None = None
    topics: list[str] | None = None
    relation_to_previous: RelationToPrevious | None = None
    continues_to_next: bool | None = None
    support_level: SupportLevel | None = None


@dataclass(frozen=True, slots=True)
class AsrCorrectionCandidateCreate:
    candidate_index: int
    original: str
    suggested: str
    correction_type: CorrectionType
    apply_scope: ApplyScope
    confidence: float


@dataclass(frozen=True, slots=True)
class MicroEventExcludedRangeCreate:
    range_index: int
    start_cue_id: str
    end_cue_id: str
    reason: ExcludedRangeReason


@dataclass(frozen=True, slots=True)
class MicroEventExtractionWindowCreate:
    video_task_id: int
    video_id: int
    transcript_id: int
    window_index: int
    start_cue_id: str
    end_cue_id: str
    cue_count: int
    status: WindowStatus
    carry_out_unfinished: bool
    codex_thread_id: str | None
    codex_turn_id: str | None
    raw_response_text: str | None
    parsed_response_json: JsonObject | None
    validation_error: str | None
    source_job_id: int
    source_job_attempt_id: int
    micro_events: list[MicroEventCandidateCreate] = field(default_factory=list)
    excluded_ranges: list[MicroEventExcludedRangeCreate] = field(default_factory=list)
    asr_correction_candidates: list[AsrCorrectionCandidateCreate] = field(
        default_factory=list
    )


@dataclass(frozen=True, slots=True)
class MicroEventCandidateRecord:
    id: int
    window_id: int
    video_task_id: int
    transcript_id: int
    candidate_index: int
    activity: Activity
    event: str
    start_cue_id: str
    end_cue_id: str
    evidence_cue_ids: list[str]
    boundary_before: bool
    boundary_after: bool
    confidence: float
    program_mode: ProgramMode | None
    content_kind: ContentKind | None
    topics: list[str] | None
    relation_to_previous: RelationToPrevious | None
    continues_to_next: bool | None
    support_level: SupportLevel | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AsrCorrectionCandidateRecord:
    id: int
    window_id: int
    video_task_id: int
    transcript_id: int
    candidate_index: int
    original: str
    suggested: str
    correction_type: CorrectionType
    apply_scope: ApplyScope
    confidence: float
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MicroEventExcludedRangeRecord:
    id: int
    window_id: int
    video_task_id: int
    transcript_id: int
    range_index: int
    start_cue_id: str
    end_cue_id: str
    reason: ExcludedRangeReason
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MicroEventExtractionWindowRecord:
    id: int
    video_task_id: int
    video_id: int
    transcript_id: int
    window_index: int
    start_cue_id: str
    end_cue_id: str
    cue_count: int
    status: WindowStatus
    carry_out_unfinished: bool
    codex_thread_id: str | None
    codex_turn_id: str | None
    raw_response_text: str | None
    parsed_response_json: JsonObject | None
    validation_error: str | None
    source_job_id: int | None
    source_job_attempt_id: int | None
    created_at: datetime
    updated_at: datetime
    micro_events: list[MicroEventCandidateRecord] = field(default_factory=list)
    excluded_ranges: list[MicroEventExcludedRangeRecord] = field(default_factory=list)
    asr_correction_candidates: list[AsrCorrectionCandidateRecord] = field(
        default_factory=list
    )


@dataclass(frozen=True, slots=True)
class MicroEventExtractionDetailRecord:
    video_task_id: int
    video_id: int
    youtube_video_id: str
    transcript_id: int | None
    status: VideoTaskStatus
    job_id: int | None
    job_attempt_id: int | None
    output_json: JsonObject | None
    error_type: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    windows: list[MicroEventExtractionWindowRecord]


class MicroEventExtractionRepositoryPort(Protocol):
    async def delete_extraction(self, video_task_id: int) -> None:
        """Delete all window and candidate rows for one extraction task."""

    async def replace_extraction(
        self,
        video_task_id: int,
        windows: list[MicroEventExtractionWindowCreate],
    ) -> MicroEventExtractionDetailRecord | None:
        """Replace all extraction rows for one task."""

    async def get_extraction(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> MicroEventExtractionDetailRecord | None:
        """Return one extraction detail for a video and task."""

    async def get_latest_succeeded_extraction(
        self,
        *,
        video_id: int,
    ) -> MicroEventExtractionDetailRecord | None:
        """Return the newest succeeded extraction for a video."""

    async def update_candidate_event(
        self,
        *,
        video_task_id: int,
        candidate_id: int,
        event: str,
    ) -> MicroEventCandidateRecord | None:
        """Update one candidate's public event text within an extraction task."""
