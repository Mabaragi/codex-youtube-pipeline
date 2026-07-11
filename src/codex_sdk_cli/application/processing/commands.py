from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from codex_sdk_cli.application.operations.results import (
    OperationBatchResult,
    OperationItem,
)
from codex_sdk_cli.application.operations.selection import (
    VideoSelection,
    VideoSelectionPort,
)
from codex_sdk_cli.application.transcripts.commands import TRANSCRIPT_CUE_TASK
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import (
    CreateWorkBatch,
    CreateWorkItem,
    WorkUnitOfWorkPort,
)
from codex_sdk_cli.domains.codex.choices import (
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.timelines.ports import CopyStyle
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.work.models import (
    JsonObject,
    WorkBatchStatus,
    WorkExecutionMode,
    WorkItem,
    WorkItemStatus,
)

MICRO_EVENT_TASK = "micro_event_extract"
MICRO_EVENT_VERSION = "v3"
TIMELINE_TASK = "timeline_compose"
TIMELINE_VERSION = "v2"
Now = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ExtractMicroEventsCommand:
    selection: VideoSelection
    window_minutes: int = 30
    overlap_minutes: int = 5
    model: CodexModelChoice = "gpt-5.5"
    reasoning_effort: ReasoningEffortChoice = "medium"
    prompt_version_id: int | None = None
    retry_failed: bool = False
    rerun_succeeded: bool = False
    include_non_embeddable: bool = False
    timeout_seconds: int = 3600
    actor_type: str = "manual_api"


@dataclass(frozen=True, slots=True)
class ComposeTimelinesCommand:
    selection: VideoSelection
    model: CodexModelChoice = "gpt-5.5"
    reasoning_effort: ReasoningEffortChoice = "high"
    copy_style: CopyStyle = "LIGHT_FANDOM_V1"
    prompt_version_id: int | None = None
    retry_failed: bool = False
    rerun_succeeded: bool = False
    include_non_embeddable: bool = False
    timeout_seconds: int = 3600
    actor_type: str = "manual_api"


class ExtractMicroEventsUseCase:
    def __init__(
        self,
        *,
        videos: VideoSelectionPort,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        now: Now | None = None,
    ) -> None:
        self._videos = videos
        self._unit_of_work_factory = unit_of_work_factory
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, command: ExtractMicroEventsCommand) -> OperationBatchResult:
        videos = await self._videos.select(command.selection)
        return await self._enqueue(videos, command)

    async def _enqueue(
        self,
        videos: list[VideoRecord],
        command: ExtractMicroEventsCommand,
    ) -> OperationBatchResult:
        now = _aware(self._now())
        items: list[OperationItem] = []
        created_count = 0
        reused_count = 0
        async with self._unit_of_work_factory() as unit_of_work:
            batch = await _create_batch(
                unit_of_work,
                operation_type=MICRO_EVENT_TASK,
                command=command,
                requested_count=len(videos),
            )
            for position, video in enumerate(videos, start=1):
                item, created, reused = await self._enqueue_video(
                    unit_of_work,
                    video=video,
                    command=command,
                    now=now,
                )
                items.append(item)
                created_count += int(created)
                reused_count += int(reused)
                await _add_batch_item(unit_of_work, batch.id, position, item)
            await _complete_batch(unit_of_work, batch.id, now)
            await unit_of_work.commit()
        return _batch_result(batch.id, items, created_count, reused_count)

    async def _enqueue_video(
        self,
        unit_of_work: WorkUnitOfWorkPort,
        *,
        video: VideoRecord,
        command: ExtractMicroEventsCommand,
        now: datetime,
    ) -> tuple[OperationItem, bool, bool]:
        if video.is_embeddable is False and not command.include_non_embeddable:
            return _skipped(video, "not_embeddable"), False, False
        source = await unit_of_work.work_items.find_latest(
            task_type=TRANSCRIPT_CUE_TASK,
            subject_type="video",
            subject_id=video.id,
            status=WorkItemStatus.SUCCEEDED,
        )
        if source is None or source.outcome_code is not None:
            return _skipped(video, "transcript_cues_not_ready"), False, False
        transcript_id = source.output_transcript_id or _output_int(
            source,
            "transcriptId",
        )
        if transcript_id is None:
            return _skipped(video, "transcript_cues_not_ready"), False, False
        input_json: JsonObject = {
            "videoId": video.id,
            "youtubeVideoId": video.youtube_video_id,
            "transcriptId": transcript_id,
            "sourceTranscriptCueWorkItemId": source.id,
            "windowMinutes": command.window_minutes,
            "overlapMinutes": command.overlap_minutes,
            "model": command.model,
            "reasoningEffort": command.reasoning_effort,
            "promptVersionId": command.prompt_version_id,
            "timeoutSeconds": command.timeout_seconds,
            "taskVersion": MICRO_EVENT_VERSION,
        }
        return await _create_dependent_work(
            unit_of_work,
            video=video,
            task_type=MICRO_EVENT_TASK,
            task_version=MICRO_EVENT_VERSION,
            input_json=input_json,
            dependency=source,
            retry_failed=command.retry_failed,
            rerun_succeeded=command.rerun_succeeded,
            timeout_seconds=command.timeout_seconds,
            now=now,
        )


class ComposeTimelinesUseCase:
    def __init__(
        self,
        *,
        videos: VideoSelectionPort,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        now: Now | None = None,
    ) -> None:
        self._videos = videos
        self._unit_of_work_factory = unit_of_work_factory
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, command: ComposeTimelinesCommand) -> OperationBatchResult:
        videos = await self._videos.select(command.selection)
        now = _aware(self._now())
        items: list[OperationItem] = []
        created_count = 0
        reused_count = 0
        async with self._unit_of_work_factory() as unit_of_work:
            batch = await _create_batch(
                unit_of_work,
                operation_type=TIMELINE_TASK,
                command=command,
                requested_count=len(videos),
            )
            for position, video in enumerate(videos, start=1):
                item, created, reused = await self._enqueue_video(
                    unit_of_work,
                    video=video,
                    command=command,
                    now=now,
                )
                items.append(item)
                created_count += int(created)
                reused_count += int(reused)
                await _add_batch_item(unit_of_work, batch.id, position, item)
            await _complete_batch(unit_of_work, batch.id, now)
            await unit_of_work.commit()
        return _batch_result(batch.id, items, created_count, reused_count)

    async def _enqueue_video(
        self,
        unit_of_work: WorkUnitOfWorkPort,
        *,
        video: VideoRecord,
        command: ComposeTimelinesCommand,
        now: datetime,
    ) -> tuple[OperationItem, bool, bool]:
        if video.is_embeddable is False and not command.include_non_embeddable:
            return _skipped(video, "not_embeddable"), False, False
        source = await unit_of_work.work_items.find_latest(
            task_type=MICRO_EVENT_TASK,
            subject_type="video",
            subject_id=video.id,
            status=WorkItemStatus.SUCCEEDED,
        )
        if source is None or source.outcome_code is not None:
            return _skipped(video, "micro_events_not_ready"), False, False
        input_json: JsonObject = {
            "videoId": video.id,
            "youtubeVideoId": video.youtube_video_id,
            "sourceMicroEventWorkItemId": source.id,
            "model": command.model,
            "reasoningEffort": command.reasoning_effort,
            "copyStyle": command.copy_style,
            "promptVersionId": command.prompt_version_id,
            "timeoutSeconds": command.timeout_seconds,
            "taskVersion": TIMELINE_VERSION,
        }
        return await _create_dependent_work(
            unit_of_work,
            video=video,
            task_type=TIMELINE_TASK,
            task_version=TIMELINE_VERSION,
            input_json=input_json,
            dependency=source,
            retry_failed=command.retry_failed,
            rerun_succeeded=command.rerun_succeeded,
            timeout_seconds=command.timeout_seconds,
            now=now,
        )


async def _create_dependent_work(
    unit_of_work: WorkUnitOfWorkPort,
    *,
    video: VideoRecord,
    task_type: str,
    task_version: str,
    input_json: JsonObject,
    dependency: WorkItem,
    retry_failed: bool,
    rerun_succeeded: bool,
    timeout_seconds: int,
    now: datetime,
) -> tuple[OperationItem, bool, bool]:
    input_hash = _hash(input_json)
    work_item, created = await unit_of_work.work_items.get_or_create(
        CreateWorkItem(
            task_type=task_type,
            subject_type="video",
            subject_id=video.id,
            external_key=video.youtube_video_id,
            task_version=task_version,
            input_hash=input_hash,
            idempotency_key=f"{task_type}:video:{video.id}:{task_version}:{input_hash}",
            execution_mode=WorkExecutionMode.WORKER,
            timeout_seconds=timeout_seconds,
            input_json=input_json,
            available_at=now,
        )
    )
    await unit_of_work.work_items.add_dependency(
        work_item_id=work_item.id,
        dependency_work_item_id=dependency.id,
    )
    if created:
        return _queued(video, work_item, "enqueued"), True, False
    if _should_reset(work_item, retry_failed, rerun_succeeded):
        work_item = await unit_of_work.work_items.reset_for_retry(
            work_item_id=work_item.id,
            now=now,
            allow_succeeded=rerun_succeeded,
        )
        return _queued(video, work_item, "requeued"), True, False
    return (
        _existing(video, work_item),
        False,
        work_item.status
        in {
            WorkItemStatus.PENDING,
            WorkItemStatus.RUNNING,
        },
    )


async def _create_batch(
    unit_of_work: WorkUnitOfWorkPort,
    *,
    operation_type: str,
    command: ExtractMicroEventsCommand | ComposeTimelinesCommand,
    requested_count: int,
):
    return await unit_of_work.work_batches.create(
        CreateWorkBatch(
            operation_type=operation_type,
            actor_type=command.actor_type,
            selection_json={"kind": type(command.selection).__name__, **asdict(command.selection)},
            options_json={
                key: value
                for key, value in asdict(command).items()
                if key not in {"selection", "actor_type"}
            },
            requested_count=requested_count,
        )
    )


async def _add_batch_item(
    unit_of_work: WorkUnitOfWorkPort,
    batch_id: int,
    position: int,
    item: OperationItem,
) -> None:
    await unit_of_work.work_batches.add_item(
        batch_id=batch_id,
        position=position,
        video_id=item.video_id,
        work_item_id=item.work_item_id,
        workflow_run_id=None,
        selection_status=item.status,
        reason=item.reason,
    )


async def _complete_batch(
    unit_of_work: WorkUnitOfWorkPort,
    batch_id: int,
    now: datetime,
) -> None:
    await unit_of_work.work_batches.complete(
        batch_id=batch_id,
        status=WorkBatchStatus.SUCCEEDED.value,
        completed_at=now,
    )


def _should_reset(item: WorkItem, retry_failed: bool, rerun_succeeded: bool) -> bool:
    if item.status in {
        WorkItemStatus.FAILED,
        WorkItemStatus.TIMED_OUT,
        WorkItemStatus.BLOCKED,
    }:
        return retry_failed
    return item.status is WorkItemStatus.SUCCEEDED and rerun_succeeded


def _existing(video: VideoRecord, item: WorkItem) -> OperationItem:
    if item.status in {WorkItemStatus.PENDING, WorkItemStatus.RUNNING}:
        return OperationItem(
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
            status=item.status.value,
            reason=f"already_{item.status.value}",
            work_item_id=item.id,
        )
    return OperationItem(
        video_id=video.id,
        youtube_video_id=video.youtube_video_id,
        status="skipped",
        reason=(
            "already_succeeded"
            if item.status is WorkItemStatus.SUCCEEDED and item.outcome_code is None
            else item.outcome_code or f"previously_{item.status.value}"
        ),
        work_item_id=item.id,
    )


def _queued(video: VideoRecord, item: WorkItem, reason: str) -> OperationItem:
    return OperationItem(
        video_id=video.id,
        youtube_video_id=video.youtube_video_id,
        status=WorkItemStatus.PENDING.value,
        reason=reason,
        work_item_id=item.id,
    )


def _skipped(video: VideoRecord, reason: str) -> OperationItem:
    return OperationItem(
        video_id=video.id,
        youtube_video_id=video.youtube_video_id,
        status="skipped",
        reason=reason,
        work_item_id=None,
    )


def _batch_result(
    batch_id: int,
    items: list[OperationItem],
    created_count: int,
    reused_count: int,
) -> OperationBatchResult:
    return OperationBatchResult(
        batch_id=batch_id,
        requested_count=len(items),
        created_count=created_count,
        reused_count=reused_count,
        skipped_count=sum(item.status == "skipped" for item in items),
        items=tuple(items),
    )


def _output_int(item: WorkItem, key: str) -> int | None:
    value = item.output_json.get(key) if item.output_json is not None else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _hash(values: JsonObject) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
