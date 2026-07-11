from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codex_sdk_cli.domains.codex.choices import (
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.timelines.ports import CopyStyle


@dataclass(frozen=True, slots=True)
class MicroEventProcessResult:
    video_id: int
    transcript_id: int
    window_count: int
    micro_event_count: int
    validation_warning_count: int = 0


@dataclass(frozen=True, slots=True)
class TimelineProcessResult:
    video_id: int
    composition_id: int
    title: str
    block_count: int
    episode_count: int
    topic_cluster_count: int
    review_flag_count: int
    validation_warning_count: int


class MicroEventProcessorPort(Protocol):
    async def process(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        video_id: int,
        transcript_id: int,
        window_minutes: int,
        overlap_minutes: int,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
        prompt_version_id: int | None,
    ) -> MicroEventProcessResult: ...


class TimelineProcessorPort(Protocol):
    async def process(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        video_id: int,
        source_micro_event_work_item_id: int,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
        copy_style: CopyStyle,
        prompt_version_id: int | None,
    ) -> TimelineProcessResult: ...
