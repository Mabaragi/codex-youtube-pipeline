from __future__ import annotations

from dataclasses import dataclass

from codex_sdk_cli.application.work.errors import WorkItemNotFound
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import WorkItemQuery
from codex_sdk_cli.domains.work.models import WorkAttempt, WorkItem


@dataclass(frozen=True, slots=True)
class WorkItemListResult:
    items: tuple[WorkItem, ...]
    next_cursor: int | None


@dataclass(frozen=True, slots=True)
class WorkItemDetail:
    item: WorkItem
    attempts: tuple[WorkAttempt, ...]


class ListWorkItemsUseCase:
    def __init__(self, unit_of_work_factory: WorkUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def execute(self, query: WorkItemQuery) -> WorkItemListResult:
        requested_limit = min(max(query.limit, 1), 200)
        expanded = WorkItemQuery(
            task_type=query.task_type,
            status=query.status,
            subject_type=query.subject_type,
            subject_id=query.subject_id,
            cursor=query.cursor,
            limit=requested_limit + 1,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            rows = await unit_of_work.work_items.list_items(expanded)
        has_more = len(rows) > requested_limit
        items = rows[:requested_limit]
        return WorkItemListResult(
            items=tuple(items),
            next_cursor=items[-1].id if has_more and items else None,
        )


class GetWorkItemUseCase:
    def __init__(self, unit_of_work_factory: WorkUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def execute(self, work_item_id: int) -> WorkItemDetail:
        async with self._unit_of_work_factory() as unit_of_work:
            item = await unit_of_work.work_items.get(work_item_id)
            if item is None:
                raise WorkItemNotFound(work_item_id)
            attempts = await unit_of_work.work_attempts.list_for_work_item(work_item_id)
        return WorkItemDetail(item=item, attempts=tuple(attempts))
