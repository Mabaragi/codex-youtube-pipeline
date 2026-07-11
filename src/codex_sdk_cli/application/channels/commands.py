from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import CreateWorkBatch, CreateWorkItem
from codex_sdk_cli.application.workflows.ports import InlineWorkRunnerPort
from codex_sdk_cli.domains.work.models import (
    WorkBatchStatus,
    WorkExecutionMode,
    WorkItemStatus,
)

CHANNEL_RESOLVE_TASK = "channel_resolve"
CHANNEL_RESOLVE_VERSION = "v2"
Now = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ResolveChannelCommand:
    streamer_id: int
    handle: str
    retry_failed: bool = False
    rerun_succeeded: bool = False
    timeout_seconds: int = 120
    actor_type: str = "manual_api"


@dataclass(frozen=True, slots=True)
class ResolveChannelResult:
    batch_id: int
    work_item_id: int
    status: str
    reason: str
    output: dict[str, object] | None
    error_code: str | None
    error_message: str | None


class ResolveChannelUseCase:
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

    async def execute(self, command: ResolveChannelCommand) -> ResolveChannelResult:
        now = _aware(self._now())
        handle = command.handle.strip()
        input_json: dict[str, object] = {
            "streamerId": command.streamer_id,
            "handle": handle,
            "timeoutSeconds": command.timeout_seconds,
            "taskVersion": CHANNEL_RESOLVE_VERSION,
        }
        input_hash = _hash(input_json)
        async with self._unit_of_work_factory() as unit_of_work:
            batch = await unit_of_work.work_batches.create(
                CreateWorkBatch(
                    operation_type=CHANNEL_RESOLVE_TASK,
                    actor_type=command.actor_type,
                    selection_json={"streamerId": command.streamer_id, "handle": handle},
                    options_json={
                        "retryFailed": command.retry_failed,
                        "rerunSucceeded": command.rerun_succeeded,
                    },
                    requested_count=1,
                )
            )
            item, _ = await unit_of_work.work_items.get_or_create(
                CreateWorkItem(
                    task_type=CHANNEL_RESOLVE_TASK,
                    subject_type="streamer",
                    subject_id=command.streamer_id,
                    external_key=handle,
                    task_version=CHANNEL_RESOLVE_VERSION,
                    input_hash=input_hash,
                    idempotency_key=(
                        f"{CHANNEL_RESOLVE_TASK}:streamer:{command.streamer_id}:"
                        f"{CHANNEL_RESOLVE_VERSION}:{input_hash}"
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
                item = await unit_of_work.work_items.reset_for_retry(
                    work_item_id=item.id,
                    now=now,
                    allow_succeeded=False,
                )
            elif item.status is WorkItemStatus.SUCCEEDED and command.rerun_succeeded:
                item = await unit_of_work.work_items.reset_for_retry(
                    work_item_id=item.id,
                    now=now,
                    allow_succeeded=True,
                )
            await unit_of_work.work_batches.add_item(
                batch_id=batch.id,
                position=1,
                video_id=None,
                work_item_id=item.id,
                workflow_run_id=None,
                selection_status=item.status.value,
                reason="scheduled" if item.status is WorkItemStatus.PENDING else "existing",
            )
            await unit_of_work.commit()

        if item.status is WorkItemStatus.PENDING:
            await self._inline_runner.run(item.id)

        async with self._unit_of_work_factory() as unit_of_work:
            final = await unit_of_work.work_items.get(item.id)
            if final is None:
                raise RuntimeError("Channel resolve work item disappeared.")
            await unit_of_work.work_batches.complete(
                batch_id=batch.id,
                status=(
                    WorkBatchStatus.SUCCEEDED.value
                    if final.status is WorkItemStatus.SUCCEEDED
                    else WorkBatchStatus.FAILED.value
                ),
                completed_at=_aware(self._now()),
            )
            await unit_of_work.commit()
        return ResolveChannelResult(
            batch_id=batch.id,
            work_item_id=final.id,
            status=final.status.value,
            reason=final.outcome_code or final.error_code or final.status.value,
            output=final.output_json,
            error_code=final.error_code,
            error_message=final.error_message,
        )


def _hash(values: dict[str, object]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
