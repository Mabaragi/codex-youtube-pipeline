from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from codex_sdk_cli.application.operations.results import OperationBatchResult, OperationItem
from codex_sdk_cli.application.operations.selection import VideoSelection, VideoSelectionPort
from codex_sdk_cli.application.processing.commands import TIMELINE_TASK
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import CreateWorkBatch, CreateWorkItem
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.work.models import (
    JsonObject,
    WorkBatchStatus,
    WorkExecutionMode,
    WorkItem,
    WorkItemStatus,
)

from .models import CoordinatorRunResult
from .models import coordinator_result as _coordinator_result
from .ports import InlineWorkRunnerPort
from .stage_policy import ARCHIVE_PUBLISH_TASK, ARCHIVE_PUBLISH_VERSION

Now = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class PublishArchivesCommand:
    selection: VideoSelection
    publish_mode: str = "prod"
    environment: str = "prod"
    variant: str = "control"
    schema_version: int = 1
    retry_failed: bool = False
    rerun_succeeded: bool = False
    include_non_embeddable: bool = False
    timeout_seconds: int = 600
    actor_type: str = "manual_api"


class PublishArchivesUseCase:
    def __init__(
        self,
        *,
        videos: VideoSelectionPort,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        inline_runner: InlineWorkRunnerPort,
        now: Now | None = None,
    ) -> None:
        self._videos = videos
        self._unit_of_work_factory = unit_of_work_factory
        self._inline_runner = inline_runner
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, command: PublishArchivesCommand) -> OperationBatchResult:
        videos = await self._videos.select(command.selection)
        now = _aware(self._now())
        initial: list[OperationItem] = []
        scheduled_ids: list[int] = []
        async with self._unit_of_work_factory() as unit_of_work:
            batch = await unit_of_work.work_batches.create(
                CreateWorkBatch(
                    operation_type=ARCHIVE_PUBLISH_TASK,
                    actor_type=command.actor_type,
                    selection_json={
                        "kind": type(command.selection).__name__,
                        **asdict(command.selection),
                    },
                    options_json={
                        "publishMode": command.publish_mode,
                        "environment": command.environment,
                        "variant": command.variant,
                        "schemaVersion": command.schema_version,
                        "retryFailed": command.retry_failed,
                        "rerunSucceeded": command.rerun_succeeded,
                    },
                    requested_count=len(videos),
                )
            )
            for position, video in enumerate(videos, start=1):
                operation_item, work_item = await _prepare_video(
                    unit_of_work,
                    video=video,
                    command=command,
                    now=now,
                )
                initial.append(operation_item)
                if work_item is not None and work_item.status is WorkItemStatus.PENDING:
                    scheduled_ids.append(work_item.id)
                await unit_of_work.work_batches.add_item(
                    batch_id=batch.id,
                    position=position,
                    video_id=video.id,
                    work_item_id=operation_item.work_item_id,
                    workflow_run_id=None,
                    selection_status=operation_item.status,
                    reason=operation_item.reason,
                )
            await unit_of_work.commit()

        for work_item_id in scheduled_ids:
            await self._inline_runner.run(work_item_id)

        final: list[OperationItem] = []
        async with self._unit_of_work_factory() as unit_of_work:
            for item in initial:
                if item.work_item_id is None:
                    final.append(item)
                    continue
                work_item = await unit_of_work.work_items.get(item.work_item_id)
                final.append(item if work_item is None else _result_item(item, work_item))
            await unit_of_work.work_batches.complete(
                batch_id=batch.id,
                status=_batch_status(final).value,
                completed_at=_aware(self._now()),
            )
            await unit_of_work.commit()
        return OperationBatchResult(
            batch_id=batch.id,
            requested_count=len(final),
            created_count=sum(item.status == "succeeded" for item in final),
            reused_count=sum(item.reason == "already_published" for item in final),
            skipped_count=sum(item.status == "skipped" for item in final),
            items=tuple(final),
        )


async def wait_for_archive_publish_resume(
    unit_of_work_factory: WorkUnitOfWorkFactory,
    *,
    workflow_run_id: int,
    now: datetime,
) -> CoordinatorRunResult:
    async with unit_of_work_factory() as unit_of_work:
        workflow = await unit_of_work.workflows.get(workflow_run_id)
        if workflow is None:
            return CoordinatorRunResult(
                processed=True,
                workflow_run_id=workflow_run_id,
                status="missing",
            )
        waiting = await unit_of_work.workflows.set_waiting(
            workflow_run_id=workflow.id,
            current_stage=ARCHIVE_PUBLISH_TASK,
            now=now,
        )
        await unit_of_work.commit()
    return _coordinator_result(waiting)


async def _prepare_video(
    unit_of_work,
    *,
    video: VideoRecord,
    command: PublishArchivesCommand,
    now: datetime,
) -> tuple[OperationItem, WorkItem | None]:
    if video.is_embeddable is False and not command.include_non_embeddable:
        return _skipped(video, "not_embeddable"), None
    source = await unit_of_work.work_items.find_latest(
        task_type=TIMELINE_TASK,
        subject_type="video",
        subject_id=video.id,
        status=WorkItemStatus.SUCCEEDED,
    )
    if source is None or source.outcome_code is not None:
        return _skipped(video, "timeline_not_ready"), None
    input_json: JsonObject = {
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
        "sourceTimelineWorkItemId": source.id,
        "publishMode": command.publish_mode,
        "environment": command.environment,
        "variant": command.variant,
        "schemaVersion": command.schema_version,
        "timeoutSeconds": command.timeout_seconds,
        "taskVersion": ARCHIVE_PUBLISH_VERSION,
    }
    input_hash = _hash(input_json)
    work_item, created = await unit_of_work.work_items.get_or_create(
        CreateWorkItem(
            task_type=ARCHIVE_PUBLISH_TASK,
            subject_type="video",
            subject_id=video.id,
            external_key=video.youtube_video_id,
            task_version=ARCHIVE_PUBLISH_VERSION,
            input_hash=input_hash,
            idempotency_key=(
                f"{ARCHIVE_PUBLISH_TASK}:video:{video.id}:"
                f"{ARCHIVE_PUBLISH_VERSION}:{input_hash}"
            ),
            execution_mode=WorkExecutionMode.INLINE,
            timeout_seconds=command.timeout_seconds,
            input_json=input_json,
            available_at=now,
        )
    )
    await unit_of_work.work_items.add_dependency(
        work_item_id=work_item.id,
        dependency_work_item_id=source.id,
    )
    if not created and _should_reset(work_item, command):
        work_item = await unit_of_work.work_items.reset_for_retry(
            work_item_id=work_item.id,
            now=now,
            allow_succeeded=command.rerun_succeeded,
        )
        return _pending(video, work_item, "requeued"), work_item
    if created:
        return _pending(video, work_item, "scheduled"), work_item
    if work_item.status is WorkItemStatus.SUCCEEDED:
        return _skipped_with_work(video, work_item, "already_published"), work_item
    return _skipped_with_work(video, work_item, f"already_{work_item.status.value}"), work_item


def _should_reset(item: WorkItem, command: PublishArchivesCommand) -> bool:
    if item.status in {
        WorkItemStatus.FAILED,
        WorkItemStatus.TIMED_OUT,
        WorkItemStatus.BLOCKED,
    }:
        return command.retry_failed
    return item.status is WorkItemStatus.SUCCEEDED and command.rerun_succeeded


def _result_item(original: OperationItem, item: WorkItem) -> OperationItem:
    return OperationItem(
        video_id=original.video_id,
        youtube_video_id=original.youtube_video_id,
        status=item.status.value,
        reason=(
            "published"
            if item.status is WorkItemStatus.SUCCEEDED
            else item.error_code or item.status.value
        ),
        work_item_id=item.id,
    )


def _pending(video: VideoRecord, item: WorkItem, reason: str) -> OperationItem:
    return OperationItem(video.id, video.youtube_video_id, "pending", reason, item.id)


def _skipped(video: VideoRecord, reason: str) -> OperationItem:
    return OperationItem(video.id, video.youtube_video_id, "skipped", reason, None)


def _skipped_with_work(video: VideoRecord, item: WorkItem, reason: str) -> OperationItem:
    return OperationItem(video.id, video.youtube_video_id, "skipped", reason, item.id)


def _batch_status(items: list[OperationItem]) -> WorkBatchStatus:
    failed = sum(item.status in {"failed", "timed_out"} for item in items)
    succeeded = sum(item.status == "succeeded" for item in items)
    if failed and not succeeded:
        return WorkBatchStatus.FAILED
    if failed:
        return WorkBatchStatus.PARTIAL
    return WorkBatchStatus.SUCCEEDED


def _hash(values: JsonObject) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
