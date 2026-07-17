from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from codex_sdk_cli.application.work.execution import WorkRunResult
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.work.models import JsonObject


@dataclass(frozen=True, slots=True)
class ScheduledChannel:
    id: int
    youtube_channel_id: str


@dataclass(frozen=True, slots=True)
class SchedulerEvent:
    event_type: str
    severity: str
    message: str
    channel_id: int | None = None
    subject_type: str | None = None
    subject_id: int | None = None
    external_key: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata_json: JsonObject | None = None


class ScheduledChannelReaderPort(Protocol):
    async def list_scheduled_channels(self) -> list[ScheduledChannel]: ...


class SchedulerEventRecorderPort(Protocol):
    async def record(self, event: SchedulerEvent) -> None: ...


class InlineWorkRunnerPort(Protocol):
    async def run_inline(self, work_item_id: int) -> WorkRunResult: ...


@dataclass(frozen=True, slots=True)
class AutomationScheduleState:
    mode: str
    backfill_started_at: datetime
    runtime_state: str = "active"


class AutomationScheduleStatePort(Protocol):
    async def get_state(self, *, now: datetime) -> AutomationScheduleState: ...

    async def mark_steady(self, *, now: datetime) -> None: ...


class WorkflowCandidateReaderPort(Protocol):
    async def list_candidates(
        self,
        *,
        state: AutomationScheduleState,
        limit: int,
    ) -> list[VideoRecord]: ...


class PublishedPromptSnapshotPort(Protocol):
    async def active_version_ids(self) -> tuple[int, int]: ...
