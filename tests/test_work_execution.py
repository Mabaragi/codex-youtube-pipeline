from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionEngine,
    WorkExecutionResult,
    WorkExecutorPort,
    WorkExecutorRegistry,
)
from codex_sdk_cli.application.work.ports import CreateWorkItem
from codex_sdk_cli.domains.work.models import WorkExecutionMode, WorkItemStatus
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork


class SuccessfulExecutor(WorkExecutorPort):
    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        return WorkExecutionResult(output_json={"workItemId": context.work_item.id})


class FailingExecutor(WorkExecutorPort):
    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        del context
        raise RuntimeError("executor failed")


def test_work_execution_engine_resolves_only_claimed_executor_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_success(database_url))


def test_work_execution_engine_records_failure(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_failure(database_url))


def test_work_execution_engine_runs_inline_item(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_inline(database_url))


async def _exercise_success(database_url: str) -> None:
    engine, session_factory = await _database(database_url)
    unselected_factory_calls = 0

    def unselected_factory() -> WorkExecutorPort:
        nonlocal unselected_factory_calls
        unselected_factory_calls += 1
        raise AssertionError("unselected executor must remain lazy")

    try:
        item_id = await _enqueue(session_factory, task_type="selected")
        execution = WorkExecutionEngine(
            unit_of_work_factory=lambda: SqlAlchemyWorkUnitOfWork(session_factory),
            registry=WorkExecutorRegistry(
                {
                    "selected": SuccessfulExecutor,
                    "unselected": unselected_factory,
                }
            ),
            task_types=("selected",),
            worker_id="worker:test",
        )

        assert await execution.run_once() is True
        assert await execution.run_once() is False
        assert unselected_factory_calls == 0

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            item = await unit_of_work.work_items.get(item_id)
        assert item is not None
        assert item.status is WorkItemStatus.SUCCEEDED
        assert item.output_json == {"workItemId": item_id}

        async with session_factory() as session:
            attempt = (
                await session.execute(
                    text(
                        "SELECT status, worker_id FROM work_attempts "
                        "WHERE work_item_id = :work_item_id"
                    ),
                    {"work_item_id": item_id},
                )
            ).one()
        assert tuple(attempt) == ("succeeded", "worker:test")
    finally:
        await engine.dispose()


async def _exercise_failure(database_url: str) -> None:
    engine, session_factory = await _database(database_url)
    try:
        item_id = await _enqueue(session_factory, task_type="failing")
        execution = WorkExecutionEngine(
            unit_of_work_factory=lambda: SqlAlchemyWorkUnitOfWork(session_factory),
            registry=WorkExecutorRegistry({"failing": FailingExecutor}),
            task_types=("failing",),
            worker_id="worker:test",
        )

        assert await execution.run_once() is True

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            item = await unit_of_work.work_items.get(item_id)
        assert item is not None
        assert item.status is WorkItemStatus.FAILED
        assert item.error_code == "work.execution_failed"
        assert item.error_message == "executor failed"
    finally:
        await engine.dispose()


async def _exercise_inline(database_url: str) -> None:
    engine, session_factory = await _database(database_url)
    try:
        item_id = await _enqueue(
            session_factory,
            task_type="inline",
            execution_mode=WorkExecutionMode.INLINE,
        )
        execution = WorkExecutionEngine(
            unit_of_work_factory=lambda: SqlAlchemyWorkUnitOfWork(session_factory),
            registry=WorkExecutorRegistry({"inline": SuccessfulExecutor}),
            task_types=("inline",),
            worker_id="inline:test",
        )

        result = await execution.run_inline(item_id)

        assert result.processed is True
        assert result.succeeded is True
        assert result.work_item_id == item_id
        assert result.output_json == {"workItemId": item_id}
        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            item = await unit_of_work.work_items.get(item_id)
        assert item is not None
        assert item.status is WorkItemStatus.SUCCEEDED
    finally:
        await engine.dispose()


async def _database(database_url: str):
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await session.execute(text("INSERT INTO streamers(id, name) VALUES (1, 'Nagi')"))
        await session.execute(
            text(
                "INSERT INTO channels(id, streamer_id, handle, name) VALUES (1, 1, '@nagi', 'Nagi')"
            )
        )
        await session.execute(
            text(
                "INSERT INTO videos(id, channel_id, youtube_video_id, title, description, "
                "published_at) VALUES "
                "(1, 1, 'abcdefghijk', 'Test', '', '2026-07-01T00:00:00+00:00')"
            )
        )
        await session.commit()
    return engine, session_factory


async def _enqueue(
    session_factory,
    *,
    task_type: str,
    execution_mode: WorkExecutionMode = WorkExecutionMode.WORKER,
) -> int:
    async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
        item, _ = await unit_of_work.work_items.get_or_create(
            CreateWorkItem(
                task_type=task_type,
                subject_type="video",
                subject_id=1,
                external_key="abcdefghijk",
                task_version="v1",
                input_hash=task_type,
                idempotency_key=f"{task_type}:video:1:v1",
                execution_mode=execution_mode,
                timeout_seconds=30,
                input_json={"videoId": 1},
                available_at=datetime.now(UTC),
            )
        )
        await unit_of_work.commit()
    return item.id
