from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowSelectionItem:
    video_id: int
    youtube_video_id: str | None
    status: str
    reason: str
    workflow_run_id: int | None


@dataclass(frozen=True, slots=True)
class WorkflowBatchResult:
    batch_id: int
    requested_count: int
    created_count: int
    reused_count: int
    skipped_count: int
    items: tuple[WorkflowSelectionItem, ...]


@dataclass(frozen=True, slots=True)
class CoordinatorRunResult:
    processed: bool
    workflow_run_id: int | None = None
    status: str | None = None
    current_stage: str | None = None
