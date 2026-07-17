from __future__ import annotations

from dataclasses import dataclass

from codex_sdk_cli.application.work.errors import (
    WorkBatchNotFound,
    WorkflowRunNotFound,
    WorkItemNotFound,
)
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import (
    WorkBatchQuery,
    WorkflowRunQuery,
    WorkItemQuery,
)
from codex_sdk_cli.domains.work.models import (
    WorkAttempt,
    WorkBatch,
    WorkBatchItem,
    WorkflowRun,
    WorkflowStep,
    WorkItem,
)


@dataclass(frozen=True, slots=True)
class WorkItemListResult:
    items: tuple[WorkItem, ...]
    next_cursor: int | None


@dataclass(frozen=True, slots=True)
class WorkItemDetail:
    item: WorkItem
    attempts: tuple[WorkAttempt, ...]


@dataclass(frozen=True, slots=True)
class WorkBatchDetail:
    batch: WorkBatch
    items: tuple[WorkBatchItem, ...]


@dataclass(frozen=True, slots=True)
class WorkBatchListResult:
    items: tuple[WorkBatch, ...]
    next_cursor: int | None


@dataclass(frozen=True, slots=True)
class WorkflowRunDetail:
    workflow: WorkflowRun
    steps: tuple[WorkflowStep, ...]
    step_items: tuple[WorkItem, ...]


@dataclass(frozen=True, slots=True)
class WorkflowRunListResult:
    items: tuple[WorkflowRun, ...]
    next_cursor: int | None


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


class GetWorkBatchUseCase:
    def __init__(self, unit_of_work_factory: WorkUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def execute(self, batch_id: int) -> WorkBatchDetail:
        async with self._unit_of_work_factory() as unit_of_work:
            batch = await unit_of_work.work_batches.get(batch_id)
            if batch is None:
                raise WorkBatchNotFound(batch_id)
            items = await unit_of_work.work_batches.list_items(batch_id)
        return WorkBatchDetail(batch=batch, items=tuple(items))


class ListWorkBatchesUseCase:
    def __init__(self, unit_of_work_factory: WorkUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def execute(self, query: WorkBatchQuery) -> WorkBatchListResult:
        requested_limit = min(max(query.limit, 1), 200)
        expanded = WorkBatchQuery(
            operation_type=query.operation_type,
            status=query.status,
            cursor=query.cursor,
            limit=requested_limit + 1,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            rows = await unit_of_work.work_batches.list_batches(expanded)
        items = rows[:requested_limit]
        return WorkBatchListResult(
            items=tuple(items),
            next_cursor=items[-1].id if len(rows) > requested_limit and items else None,
        )


class GetWorkflowRunUseCase:
    def __init__(self, unit_of_work_factory: WorkUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def execute(self, workflow_run_id: int) -> WorkflowRunDetail:
        async with self._unit_of_work_factory() as unit_of_work:
            workflow = await unit_of_work.workflows.get(workflow_run_id)
            if workflow is None:
                raise WorkflowRunNotFound(workflow_run_id)
            steps = await unit_of_work.workflows.list_steps(workflow_run_id)
            step_items = [
                item
                for step in steps
                if step.work_item_id is not None
                and (item := await unit_of_work.work_items.get(step.work_item_id)) is not None
            ]
        return WorkflowRunDetail(
            workflow=workflow,
            steps=tuple(steps),
            step_items=tuple(step_items),
        )


class ListWorkflowRunsUseCase:
    def __init__(self, unit_of_work_factory: WorkUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def execute(self, query: WorkflowRunQuery) -> WorkflowRunListResult:
        requested_limit = min(max(query.limit, 1), 200)
        expanded = WorkflowRunQuery(
            workflow_type=query.workflow_type,
            status=query.status,
            video_id=query.video_id,
            cursor=query.cursor,
            limit=requested_limit + 1,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            rows = await unit_of_work.workflows.list_runs(expanded)
        items = rows[:requested_limit]
        return WorkflowRunListResult(
            items=tuple(items),
            next_cursor=items[-1].id if len(rows) > requested_limit and items else None,
        )
