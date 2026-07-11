from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from codex_sdk_cli.application.work.errors import WorkItemNotFound
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.domains.work.models import WorkItem

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
            item = await unit_of_work.work_items.reset_for_retry(
                work_item_id=work_item_id,
                now=_aware(self._now()),
                allow_succeeded=rerun_succeeded,
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
