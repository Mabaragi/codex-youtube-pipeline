from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from codex_sdk_cli.application.operations.results import (
    ChannelOperationBatchResult,
    ChannelOperationItem,
)
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import CreateWorkBatch, CreateWorkItem
from codex_sdk_cli.application.workflows.ports import InlineWorkRunnerPort
from codex_sdk_cli.domains.work.models import (
    WorkBatchStatus,
    WorkExecutionMode,
    WorkItem,
    WorkItemStatus,
)

VIDEO_COLLECT_TASK = "video_collect"
VIDEO_COLLECT_VERSION = "v2"
Now = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CollectVideosCommand:
    channel_ids: tuple[int, ...]
    retry_failed: bool = False
    rerun_succeeded: bool = False
    timeout_seconds: int = 600
    actor_type: str = "manual_api"


class CollectVideosUseCase:
    def __init__(
        self,
        *,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        inline_runner: InlineWorkRunnerPort,
        now: Now | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._inline_runner = inline_runner
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, command: CollectVideosCommand) -> ChannelOperationBatchResult:
        channel_ids = tuple(dict.fromkeys(command.channel_ids))
        now = _aware(self._now())
        scheduled: list[tuple[int, int]] = []
        initial: dict[int, ChannelOperationItem] = {}
        async with self._unit_of_work_factory() as unit_of_work:
            batch = await unit_of_work.work_batches.create(
                CreateWorkBatch(
                    operation_type=VIDEO_COLLECT_TASK,
                    actor_type=command.actor_type,
                    selection_json={"channelIds": list(channel_ids)},
                    options_json={
                        "retryFailed": command.retry_failed,
                        "rerunSucceeded": command.rerun_succeeded,
                    },
                    requested_count=len(channel_ids),
                )
            )
            for position, channel_id in enumerate(channel_ids, start=1):
                item = await _ensure_work_item(unit_of_work, channel_id, command, now)
                if item.status is WorkItemStatus.PENDING:
                    scheduled.append((channel_id, item.id))
                    operation_item = _channel_item(channel_id, item, "scheduled")
                else:
                    operation_item = _channel_item(channel_id, item, _existing_reason(item))
                initial[channel_id] = operation_item
                await unit_of_work.work_batches.add_item(
                    batch_id=batch.id,
                    position=position,
                    video_id=None,
                    work_item_id=item.id,
                    workflow_run_id=None,
                    selection_status=operation_item.status,
                    reason=operation_item.reason,
                )
            await unit_of_work.commit()

        for _, work_item_id in scheduled:
            await self._inline_runner.run(work_item_id)

        final: list[ChannelOperationItem] = []
        async with self._unit_of_work_factory() as unit_of_work:
            for channel_id in channel_ids:
                original = initial[channel_id]
                if original.work_item_id is None:
                    final.append(original)
                    continue
                item = await unit_of_work.work_items.get(original.work_item_id)
                if item is None:
                    final.append(
                        ChannelOperationItem(
                            channel_id=channel_id,
                            status="failed",
                            reason="work_item_missing",
                            work_item_id=original.work_item_id,
                        )
                    )
                else:
                    final.append(_channel_item(channel_id, item, _final_reason(item)))
            batch_status = _batch_status(final)
            await unit_of_work.work_batches.complete(
                batch_id=batch.id,
                status=batch_status.value,
                completed_at=_aware(self._now()),
            )
            await unit_of_work.commit()
        return ChannelOperationBatchResult(
            batch_id=batch.id,
            requested_count=len(final),
            succeeded_count=sum(item.status == "succeeded" for item in final),
            failed_count=sum(item.status in {"failed", "timed_out"} for item in final),
            skipped_count=sum(item.status == "skipped" for item in final),
            items=tuple(final),
        )


async def _ensure_work_item(
    unit_of_work,
    channel_id: int,
    command: CollectVideosCommand,
    now: datetime,
) -> WorkItem:
    input_json: dict[str, object] = {
        "channelId": channel_id,
        "timeoutSeconds": command.timeout_seconds,
        "taskVersion": VIDEO_COLLECT_VERSION,
    }
    input_hash = _hash(input_json)
    item, _ = await unit_of_work.work_items.get_or_create(
        CreateWorkItem(
            task_type=VIDEO_COLLECT_TASK,
            subject_type="channel",
            subject_id=channel_id,
            external_key=None,
            task_version=VIDEO_COLLECT_VERSION,
            input_hash=input_hash,
            idempotency_key=(
                f"{VIDEO_COLLECT_TASK}:channel:{channel_id}:"
                f"{VIDEO_COLLECT_VERSION}:{input_hash}"
            ),
            execution_mode=WorkExecutionMode.INLINE,
            timeout_seconds=command.timeout_seconds,
            input_json=input_json,
            available_at=now,
        )
    )
    if item.status in {
        WorkItemStatus.FAILED,
        WorkItemStatus.TIMED_OUT,
        WorkItemStatus.BLOCKED,
    } and command.retry_failed:
        return await unit_of_work.work_items.reset_for_retry(
            work_item_id=item.id,
            now=now,
            allow_succeeded=False,
        )
    if item.status is WorkItemStatus.SUCCEEDED and command.rerun_succeeded:
        return await unit_of_work.work_items.reset_for_retry(
            work_item_id=item.id,
            now=now,
            allow_succeeded=True,
        )
    return item


def _channel_item(channel_id: int, item: WorkItem, reason: str) -> ChannelOperationItem:
    status = item.status.value
    if status in {"blocked", "canceled"}:
        status = "skipped"
    return ChannelOperationItem(
        channel_id=channel_id,
        status=status,
        reason=reason,
        work_item_id=item.id,
        output=item.output_json,
        error_code=item.error_code,
        error_message=item.error_message,
    )


def _existing_reason(item: WorkItem) -> str:
    if item.status is WorkItemStatus.SUCCEEDED:
        return "already_succeeded"
    return f"already_{item.status.value}"


def _final_reason(item: WorkItem) -> str:
    if item.status is WorkItemStatus.SUCCEEDED:
        return item.outcome_code or "succeeded"
    return item.error_code or item.outcome_code or item.status.value


def _batch_status(items: list[ChannelOperationItem]) -> WorkBatchStatus:
    succeeded = sum(item.status == "succeeded" for item in items)
    failed = sum(item.status in {"failed", "timed_out"} for item in items)
    if failed and not succeeded:
        return WorkBatchStatus.FAILED
    if failed:
        return WorkBatchStatus.PARTIAL
    return WorkBatchStatus.SUCCEEDED


def _hash(values: dict[str, object]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
