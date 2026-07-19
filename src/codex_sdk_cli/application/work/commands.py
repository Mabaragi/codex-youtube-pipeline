from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from codex_sdk_cli.application.work.errors import (
    WorkItemNotFound,
    WorkItemRetryInputUnavailable,
    WorkItemRetrySuperseded,
)
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import WorkUnitOfWorkPort
from codex_sdk_cli.domains.codex.choices import CODEX_MODEL_CHOICES
from codex_sdk_cli.domains.work.models import JsonObject, WorkItem, WorkItemStatus

Now = Callable[[], datetime]


class RetryWorkItemUseCase:
    def __init__(
        self,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        *,
        now: Now | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self,
        work_item_id: int,
        *,
        rerun_succeeded: bool = False,
    ) -> WorkItem:
        async with self._unit_of_work_factory() as unit_of_work:
            item = await unit_of_work.work_items.get(work_item_id)
            if item is None:
                raise WorkItemNotFound(work_item_id)
            if _can_retry(item.status, rerun_succeeded=rerun_succeeded):
                await _validate_retry(unit_of_work, item)
            now = _aware(self._now())
            item = await unit_of_work.work_items.reset_for_retry(
                work_item_id=work_item_id,
                now=now,
                allow_succeeded=rerun_succeeded,
            )
            await unit_of_work.workflows.reset_linked_for_work_item_retry(
                work_item_id=work_item_id,
                now=now,
            )
            await unit_of_work.commit()
        return item


class CancelWorkItemUseCase:
    def __init__(
        self,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        *,
        now: Now | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, work_item_id: int, *, reason: str) -> WorkItem:
        async with self._unit_of_work_factory() as unit_of_work:
            item = await unit_of_work.work_items.get(work_item_id)
            if item is None:
                raise WorkItemNotFound(work_item_id)
            item = await unit_of_work.work_items.cancel(
                work_item_id=work_item_id,
                now=_aware(self._now()),
                reason=reason,
            )
            await unit_of_work.commit()
        return item


class CancelPendingSubjectWorkUseCase:
    def __init__(
        self,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        *,
        now: Now | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        subject_type: str,
        subject_id: int,
        task_types: tuple[str, ...],
        outcome_code: str,
        reason: str,
    ) -> int:
        async with self._unit_of_work_factory() as unit_of_work:
            canceled = await unit_of_work.work_items.cancel_pending_for_subject(
                subject_type=subject_type,
                subject_id=subject_id,
                task_types=task_types,
                now=_aware(self._now()),
                outcome_code=outcome_code,
                reason=reason,
            )
            await unit_of_work.commit()
        return canceled


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _can_retry(status: WorkItemStatus, *, rerun_succeeded: bool) -> bool:
    return status in {
        WorkItemStatus.FAILED,
        WorkItemStatus.TIMED_OUT,
        WorkItemStatus.BLOCKED,
        WorkItemStatus.CANCELED,
    } or (rerun_succeeded and status is WorkItemStatus.SUCCEEDED)


async def _validate_retry(unit_of_work: WorkUnitOfWorkPort, item: WorkItem) -> None:
    if item.task_type != "micro_event_extract":
        return

    invalid_fields = _invalid_micro_event_input_fields(item.input_json)
    if item.subject_id is not None:
        latest_success = await unit_of_work.work_items.find_latest(
            task_type=item.task_type,
            subject_type=item.subject_type,
            subject_id=item.subject_id,
            status=WorkItemStatus.SUCCEEDED,
        )
        if (
            latest_success is not None
            and latest_success.id > item.id
            and (
                bool(invalid_fields)
                or (
                    latest_success.task_version == item.task_version
                    and latest_success.input_hash == item.input_hash
                )
            )
        ):
            raise WorkItemRetrySuperseded(
                item.id,
                replacement_work_item_id=latest_success.id,
            )

    if invalid_fields:
        raise WorkItemRetryInputUnavailable(item.id, invalid_fields=invalid_fields)


def _invalid_micro_event_input_fields(values: JsonObject) -> tuple[str, ...]:
    invalid_fields = [
        key
        for key in ("videoId", "transcriptId", "windowMinutes", "overlapMinutes")
        if not _is_int(values.get(key))
    ]
    model = values.get("model")
    if not isinstance(model, str) or model not in CODEX_MODEL_CHOICES:
        invalid_fields.append("model")
    if values.get("reasoningEffort") not in {"low", "medium", "high", "xhigh"}:
        invalid_fields.append("reasoningEffort")
    prompt_version_id = values.get("promptVersionId")
    if prompt_version_id is not None and not _is_int(prompt_version_id):
        invalid_fields.append("promptVersionId")
    return tuple(invalid_fields)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
