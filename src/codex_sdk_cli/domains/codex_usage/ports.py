from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

JsonObject = dict[str, object]
CodexUsageStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class CodexUsageCreate:
    source: str
    operation: str
    model: str | None
    status: CodexUsageStatus
    thread_id: str | None
    turn_id: str | None
    usage_json: JsonObject | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    reasoning_output_tokens: int | None
    duration_ms: int
    error_type: str | None = None
    error_message: str | None = None
    video_id: int | None = None
    video_task_id: int | None = None
    job_id: int | None = None
    job_attempt_id: int | None = None
    transcript_id: int | None = None
    window_index: int | None = None


@dataclass(frozen=True, slots=True)
class CodexUsageRecord:
    id: int
    source: str
    operation: str
    model: str | None
    status: CodexUsageStatus
    thread_id: str | None
    turn_id: str | None
    usage_json: JsonObject | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None
    reasoning_output_tokens: int | None
    duration_ms: int
    error_type: str | None
    error_message: str | None
    video_id: int | None
    video_task_id: int | None
    job_id: int | None
    job_attempt_id: int | None
    transcript_id: int | None
    window_index: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CodexUsageListQuery:
    source: str | None = None
    status: str | None = None
    model: str | None = None
    video_id: int | None = None
    video_task_id: int | None = None
    job_id: int | None = None
    limit: int = 50
    cursor: int | None = None


@dataclass(frozen=True, slots=True)
class CodexUsageSummaryRecord:
    run_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int
    reasoning_output_tokens: int


@dataclass(frozen=True, slots=True)
class CodexUsageListResult:
    items: list[CodexUsageRecord]
    next_cursor: int | None
    summary: CodexUsageSummaryRecord


class CodexUsageRepositoryPort(Protocol):
    async def create_usage(self, usage: CodexUsageCreate) -> CodexUsageRecord:
        """Persist one Codex run usage row."""

    async def list_usages(self, query: CodexUsageListQuery) -> CodexUsageListResult:
        """List Codex run usage rows with a summary for the current filters."""


class CodexUsageRecorderPort(Protocol):
    async def record_usage(self, usage: CodexUsageCreate) -> None:
        """Best-effort record of one Codex run usage row."""
