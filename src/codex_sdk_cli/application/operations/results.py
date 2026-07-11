from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperationItem:
    video_id: int
    youtube_video_id: str
    status: str
    reason: str
    work_item_id: int | None


@dataclass(frozen=True, slots=True)
class OperationBatchResult:
    batch_id: int
    requested_count: int
    created_count: int
    reused_count: int
    skipped_count: int
    items: tuple[OperationItem, ...]


@dataclass(frozen=True, slots=True)
class ChannelOperationItem:
    channel_id: int
    status: str
    reason: str
    work_item_id: int | None
    output: dict[str, object] | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ChannelOperationBatchResult:
    batch_id: int
    requested_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    items: tuple[ChannelOperationItem, ...]
