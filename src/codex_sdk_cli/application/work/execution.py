from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind
from codex_sdk_cli.domains.work.models import JsonObject, WorkItem

from .ports import WorkUnitOfWorkPort

Now = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]
WorkUnitOfWorkFactory = Callable[[], WorkUnitOfWorkPort]


@dataclass(frozen=True, slots=True)
class WorkExecutionResult:
    output_json: JsonObject
    output_transcript_id: int | None = None
    outcome_code: str | None = None
    cooldown_seconds_override: int | None = None


@dataclass(frozen=True, slots=True)
class WorkRunResult:
    processed: bool
    work_item_id: int | None = None
    succeeded: bool | None = None
    outcome_code: str | None = None
    output_json: JsonObject | None = None
    cooldown_seconds_override: int | None = None


@dataclass(frozen=True, slots=True)
class WorkExecutionContext:
    work_item: WorkItem
    attempt_id: int
    worker_id: str


class WorkExecutorPort(Protocol):
    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult: ...


WorkExecutorFactory = Callable[[], WorkExecutorPort]


class WorkExecutorNotRegistered(ApplicationError):
    def __init__(self, task_type: str) -> None:
        super().__init__(
            code="work.executor_not_registered",
            message=f"No executor is registered for task type {task_type}.",
            kind=ErrorKind.INTERNAL,
            details={"taskType": task_type},
        )


class WorkExecutorRegistry:
    """Resolve only the executor selected by the claimed work item."""

    def __init__(self, factories: Mapping[str, WorkExecutorFactory]) -> None:
        self._factories = dict(factories)

    def resolve(self, task_type: str) -> WorkExecutorPort:
        factory = self._factories.get(task_type)
        if factory is None:
            raise WorkExecutorNotRegistered(task_type)
        return factory()


class WorkExecutionEngine:
    def __init__(
        self,
        *,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        registry: WorkExecutorRegistry,
        task_types: tuple[str, ...],
        worker_id: str,
        lease_seconds: int = 90,
        heartbeat_seconds: int = 30,
        now: Now | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if not task_types:
            raise ValueError("At least one task type is required.")
        if lease_seconds < 1 or heartbeat_seconds < 1:
            raise ValueError("Lease and heartbeat durations must be positive.")
        if heartbeat_seconds >= lease_seconds:
            raise ValueError("Heartbeat interval must be shorter than the lease.")
        self._unit_of_work_factory = unit_of_work_factory
        self._registry = registry
        self._task_types = task_types
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._sleep = sleep

    async def run_once(self) -> bool:
        return (await self.run_once_with_result()).processed

    async def run_once_with_result(self) -> WorkRunResult:
        claimed = await self._claim()
        if claimed is None:
            return WorkRunResult(processed=False)
        return await self._execute_claimed(*claimed)

    async def run_inline(self, work_item_id: int) -> WorkRunResult:
        started = await self._start_inline(work_item_id)
        if started is None:
            return WorkRunResult(processed=False, work_item_id=work_item_id)
        return await self._execute_claimed(*started)

    async def _execute_claimed(
        self,
        work_item: WorkItem,
        attempt_id: int,
    ) -> WorkRunResult:
        try:
            executor = self._registry.resolve(work_item.task_type)
            result = await self._execute_with_heartbeat(
                executor,
                WorkExecutionContext(
                    work_item=work_item,
                    attempt_id=attempt_id,
                    worker_id=self._worker_id,
                ),
            )
        except TimeoutError as exc:
            await self._mark_failed(
                work_item_id=work_item.id,
                attempt_id=attempt_id,
                error_code="work.timed_out",
                error_type=type(exc).__name__,
                error_message=f"Work item exceeded {work_item.timeout_seconds} seconds.",
                timed_out=True,
            )
            return WorkRunResult(
                processed=True,
                work_item_id=work_item.id,
                succeeded=False,
            )
        except Exception as exc:
            await self._mark_failed(
                work_item_id=work_item.id,
                attempt_id=attempt_id,
                error_code=_error_code(exc),
                error_type=type(exc).__name__,
                error_message=str(exc) or type(exc).__name__,
                timed_out=False,
            )
            return WorkRunResult(
                processed=True,
                work_item_id=work_item.id,
                succeeded=False,
            )
        else:
            await self._mark_succeeded(
                work_item_id=work_item.id,
                attempt_id=attempt_id,
                result=result,
            )
            return WorkRunResult(
                processed=True,
                work_item_id=work_item.id,
                succeeded=True,
                outcome_code=result.outcome_code,
                output_json=result.output_json,
                cooldown_seconds_override=result.cooldown_seconds_override,
            )

    async def recover_expired(self) -> int:
        async with self._unit_of_work_factory() as unit_of_work:
            recovered = await unit_of_work.work_items.recover_expired_leases(now=self._aware_now())
            await unit_of_work.commit()
        return recovered

    async def _claim(self) -> tuple[WorkItem, int] | None:
        now = self._aware_now()
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.work_items.mark_dependency_blocked(now=now)
            work_item = await unit_of_work.work_items.claim_next(
                task_types=self._task_types,
                worker_id=self._worker_id,
                now=now,
                lease_expires_at=now + timedelta(seconds=self._lease_seconds),
            )
            if work_item is None:
                await unit_of_work.commit()
                return None
            attempt = await unit_of_work.work_attempts.create(
                work_item_id=work_item.id,
                worker_id=self._worker_id,
            )
            await unit_of_work.commit()
        return work_item, attempt.id

    async def _start_inline(self, work_item_id: int) -> tuple[WorkItem, int] | None:
        now = self._aware_now()
        async with self._unit_of_work_factory() as unit_of_work:
            work_item = await unit_of_work.work_items.start_inline(
                work_item_id=work_item_id,
                worker_id=self._worker_id,
                now=now,
                lease_expires_at=now + timedelta(seconds=self._lease_seconds),
            )
            if work_item is None:
                await unit_of_work.commit()
                return None
            attempt = await unit_of_work.work_attempts.create(
                work_item_id=work_item.id,
                worker_id=self._worker_id,
            )
            await unit_of_work.commit()
        return work_item, attempt.id

    async def _execute_with_heartbeat(
        self,
        executor: WorkExecutorPort,
        context: WorkExecutionContext,
    ) -> WorkExecutionResult:
        heartbeat = asyncio.create_task(self._heartbeat_loop(context.work_item.id))
        try:
            return await asyncio.wait_for(
                executor.execute(context),
                timeout=context.work_item.timeout_seconds,
            )
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat_loop(self, work_item_id: int) -> None:
        while True:
            await self._sleep(float(self._heartbeat_seconds))
            now = self._aware_now()
            async with self._unit_of_work_factory() as unit_of_work:
                alive = await unit_of_work.work_items.heartbeat(
                    work_item_id=work_item_id,
                    worker_id=self._worker_id,
                    now=now,
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                )
                await unit_of_work.commit()
            if not alive:
                return

    async def _mark_succeeded(
        self,
        *,
        work_item_id: int,
        attempt_id: int,
        result: WorkExecutionResult,
    ) -> None:
        now = self._aware_now()
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.work_attempts.mark_succeeded(
                attempt_id=attempt_id,
                now=now,
                output_json=result.output_json,
            )
            await unit_of_work.work_items.mark_succeeded(
                work_item_id=work_item_id,
                now=now,
                output_json=result.output_json,
                output_transcript_id=result.output_transcript_id,
                outcome_code=result.outcome_code,
            )
            await unit_of_work.commit()

    async def _mark_failed(
        self,
        *,
        work_item_id: int,
        attempt_id: int,
        error_code: str,
        error_type: str,
        error_message: str,
        timed_out: bool,
    ) -> None:
        now = self._aware_now()
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.work_attempts.mark_failed(
                attempt_id=attempt_id,
                now=now,
                error_code=error_code,
                error_type=error_type,
                error_message=error_message,
                timed_out=timed_out,
            )
            await unit_of_work.work_items.mark_failed(
                work_item_id=work_item_id,
                now=now,
                error_code=error_code,
                error_type=error_type,
                error_message=error_message,
                timed_out=timed_out,
            )
            await unit_of_work.commit()

    def _aware_now(self) -> datetime:
        value = self._now()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ApplicationError):
        return exc.descriptor.code
    return "work.execution_failed"
