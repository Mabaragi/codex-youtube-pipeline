from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

JsonObject = dict[str, object]


@dataclass(frozen=True, slots=True)
class LlmTraceEvent:
    source: str
    operation: str
    phase: str
    video_task_id: int | None = None
    work_item_id: int | None = None
    work_attempt_id: int | None = None
    video_id: int | None = None
    job_id: int | None = None
    job_attempt_id: int | None = None
    window_index: int | None = None
    window_count: int | None = None
    repair_index: int | None = None
    target_episode_id: str | None = None
    repair_reason: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    status: str | None = None
    elapsed_ms: int | None = None
    prompt_text: str | None = None
    raw_response_text: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata: JsonObject = field(default_factory=dict)


class LlmTraceRecorderPort(Protocol):
    async def record_event(self, event: LlmTraceEvent) -> None:
        """Record an LLM trace event."""


class NoopLlmTraceRecorder(LlmTraceRecorderPort):
    async def record_event(self, event: LlmTraceEvent) -> None:
        return None
