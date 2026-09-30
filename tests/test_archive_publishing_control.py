from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from alembic import command
from codex_sdk_cli.api.dependencies import _get_database_engine, get_settings
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionEngine,
    WorkExecutionResult,
    WorkExecutorPort,
    WorkExecutorRegistry,
)
from codex_sdk_cli.application.work.ports import CreateWorkItem
from codex_sdk_cli.domains.work.models import WorkExecutionMode, WorkItemStatus
from codex_sdk_cli.infra.automation.repository import SqlAlchemyAutomationRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork


def test_migration_preserves_archive_identity_and_terminal_state(
    migrated_database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "CODEX_CLI_DATABASE_URL", f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    )
    config = Config()
    config.set_main_option("script_location", "alembic")
    command.downgrade(config, "20260930_0035")
    engine = create_engine(f"sqlite:///{migrated_database_path.as_posix()}")
    try:
        with engine.begin() as connection:
            for index, status in enumerate(("pending", "failed", "running", "succeeded"), 1):
                connection.execute(
                    text(
                        "INSERT INTO work_items(id, task_type, subject_type, task_version, "
                        "input_hash, idempotency_key, execution_mode, status, timeout_seconds, "
                        "input_json, output_json) VALUES (:id,'archive_publish','system',"
                        "'v1','fixed-hash',:key,'inline',:status,60,'{}','{}')"
                    ),
                    {"id": index, "key": f"migration:{index}", "status": status},
                )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id,status,execution_mode,input_hash,output_json "
                    "FROM work_items ORDER BY id"
                )
            ).all()
        assert rows == [
            (1, "pending", "worker", "fixed-hash", "{}"),
            (2, "failed", "worker", "fixed-hash", "{}"),
            (3, "running", "inline", "fixed-hash", "{}"),
            (4, "succeeded", "inline", "fixed-hash", "{}"),
        ]
    finally:
        engine.dispose()


class FakePublishExecutor(WorkExecutorPort):
    def __init__(self, controls: SqlAlchemyAutomationRepository | None = None) -> None:
        self.calls: list[int] = []
        self.controls = controls

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        self.calls.append(context.work_item.id)
        if self.controls is not None:
            state = await self.controls.set_publishing(
                enabled=False, reason="pause during execution", now=datetime.now(UTC)
            )
            assert state.running_count == 1
        return WorkExecutionResult(output_json={"artifactId": 10, "videoId": 1})


def test_manual_publication_queues_while_off_and_resumes_same_item(
    migrated_database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", url)
    get_settings.cache_clear()
    _get_database_engine.cache_clear()
    try:
        asyncio.run(_exercise_manual_queue(url))
    finally:
        get_settings.cache_clear()
        _get_database_engine.cache_clear()


async def _exercise_manual_queue(url: str) -> None:
    database = create_database_engine(url)
    sessions = create_session_factory(database)

    def uow() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(sessions)

    controls = SqlAlchemyAutomationRepository(sessions)
    publisher = FakePublishExecutor()
    worker = WorkExecutionEngine(
        unit_of_work_factory=uow,
        registry=WorkExecutorRegistry({"archive_publish": lambda: publisher}),
        task_types=("archive_publish",),
        worker_id="publish:test",
    )
    try:
        async with sessions() as session:
            await session.execute(
                text("INSERT INTO streamers(id,name,publish_profile_id) VALUES (1,'Test',1)")
            )
            await session.execute(
                text("INSERT INTO channels(id,streamer_id,handle,name) VALUES (1,1,'@test','Test')")
            )
            await session.execute(
                text(
                    "INSERT INTO videos(id,channel_id,youtube_video_id,title,description,"
                    "published_at,is_embeddable) VALUES (1,1,'publish-test','Test','',:now,true)"
                ),
                {"now": datetime.now(UTC)},
            )
            await session.commit()
        async with uow() as unit:
            source, _ = await unit.work_items.get_or_create(_create("timeline_compose", "source"))
            await unit.work_items.start_inline(
                work_item_id=source.id,
                worker_id="test",
                now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            await unit.work_items.mark_succeeded(
                work_item_id=source.id,
                now=datetime.now(UTC),
                output_json={"videoId": 1, "compositionId": 9},
            )
            await unit.commit()
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            initial = await client.get("/ops/automation/publishing")
            assert initial.json()["enabled"] is True
            assert (
                await client.put("/ops/automation/publishing", json={"enabled": False})
            ).status_code == 200
            command = {"selection": {"type": "selected", "videoIds": [1]}, "includeSegments": False}
            queued = await client.post("/ops/operations/archive-publish", json=command)
            assert queued.status_code == 202
            assert queued.json()["createdCount"] == 1
            item_id = queued.json()["items"][0]["workItemId"]
            repeated = await client.post("/ops/operations/archive-publish", json=command)
            assert repeated.json()["items"][0]["workItemId"] == item_id
            assert repeated.json()["createdCount"] == 0
            assert not (await worker.run_once_with_result()).processed
            async with uow() as unit:
                pending = await unit.work_items.get(item_id)
                assert pending is not None
                assert pending.status is WorkItemStatus.PENDING
                assert pending.execution_mode is WorkExecutionMode.WORKER
                assert "publishingEnabled" not in pending.input_json
                assert await unit.work_attempts.list_for_work_item(item_id) == []
            assert publisher.calls == []
            status = (await client.get("/ops/automation/status")).json()
            assert status["publishing"]["pendingCount"] == 1
            assert status["runtime"]["state"] == "active"
            assert status["dailyVideoQuota"]["admitted"] == 0
            async with sessions() as session:
                for index, stage in enumerate(("archive_publish", "timeline_compose"), 1):
                    await session.execute(
                        text(
                            "INSERT INTO workflow_runs(id,workflow_type,workflow_version,video_id,"
                            "input_hash,options_json,status,current_stage) VALUES "
                            "(:id,'process_to_publish','v3',1,:hash,:options,'waiting',:stage)"
                        ),
                        {
                            "id": index,
                            "hash": f"sla:{index}",
                            "stage": stage,
                            "options": '{"captionSlaDeadline":"2020-01-01T00:00:00Z"}',
                        },
                    )
                await session.execute(
                    text(
                        "INSERT INTO workflow_steps(workflow_run_id,stage_name,position,"
                        "work_item_id,status) VALUES (1,'archive_publish',1,:id,'pending')"
                    ),
                    {"id": item_id},
                )
                await session.commit()
            breaches = await controls.sla_breaches(now=datetime.now(UTC), limit=10)
            assert [item.workflow_run_id for item in breaches] == [2]
            for path, body in [
                ("archive-object-deliver", {"artifactIds": [1], "profileRevisionId": 1}),
                ("archive-catalog-publish", {"artifactIds": [1], "profileRevisionId": 1}),
                ("archive-publication-build", {"artifactIds": [1], "profileRevisionId": 1}),
                (
                    "archive-pointer-publish",
                    {"publicationId": 1, "artifactIds": [1], "profileRevisionId": 1},
                ),
            ]:
                blocked = await client.post(f"/ops/operations/{path}", json=body)
                assert blocked.status_code == 409, blocked.text
            assert not (
                await SqlAlchemyAutomationRepository(sessions).publishing_state(
                    now=datetime.now(UTC)
                )
            ).enabled
            await client.put("/ops/automation/publishing", json={"enabled": True, "reason": "test"})
            assert (await worker.run_once_with_result()).succeeded
            assert publisher.calls == [item_id]
            async with uow() as unit:
                finished = await unit.work_items.get(item_id)
                assert finished is not None
                assert finished.input_hash == pending.input_hash
                assert finished.input_json == pending.input_json
                assert len(await unit.work_attempts.list_for_work_item(item_id)) == 1
            assert (await controls.publishing_state(now=datetime.now(UTC))).pending_count == 0
    finally:
        await database.dispose()


def _create(
    task_type: str, key: str, *, mode: WorkExecutionMode = WorkExecutionMode.INLINE
) -> CreateWorkItem:
    return CreateWorkItem(
        task_type=task_type,
        subject_type="video",
        subject_id=1,
        external_key="publish-test",
        task_version="v1",
        input_hash=key,
        idempotency_key=key,
        execution_mode=mode,
        timeout_seconds=60,
        input_json={"videoId": 1},
    )


def test_off_drains_claimed_publication_and_only_suppresses_publication_waits(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_draining_and_alerts(migrated_database_path))


async def _exercise_draining_and_alerts(path: Path) -> None:
    database = create_database_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    sessions = create_session_factory(database)

    def uow() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(sessions)

    controls = SqlAlchemyAutomationRepository(sessions)
    now = datetime.now(UTC)
    try:
        async with uow() as unit:
            queued, _ = await unit.work_items.get_or_create(
                _create("archive_publish", "first", mode=WorkExecutionMode.WORKER)
            )
            other, _ = await unit.work_items.get_or_create(
                _create("micro_event_extract", "other", mode=WorkExecutionMode.WORKER)
            )
            failed, _ = await unit.work_items.get_or_create(_create("archive_publish", "failed"))
            await unit.work_items.start_inline(
                work_item_id=failed.id,
                worker_id="test",
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
            )
            await unit.work_items.mark_failed(
                work_item_id=failed.id,
                now=now,
                error_code="test",
                error_type="TestError",
                error_message="actual failure",
            )
            await unit.commit()
        publisher = FakePublishExecutor(controls)
        worker = WorkExecutionEngine(
            unit_of_work_factory=uow,
            registry=WorkExecutorRegistry({"archive_publish": lambda: publisher}),
            task_types=("archive_publish",),
            worker_id="test",
        )
        assert (await worker.run_once_with_result()).succeeded
        async with sessions() as session:
            await session.execute(
                text("UPDATE work_items SET available_at=:past"), {"past": now - timedelta(hours=1)}
            )
            await session.commit()
        async with uow() as unit:
            waiting, _ = await unit.work_items.get_or_create(
                _create("archive_publish", "waiting", mode=WorkExecutionMode.WORKER)
            )
            await unit.commit()
        assert not (await worker.run_once_with_result()).processed
        stalls = await controls.queue_stalls(now=now + timedelta(hours=1), limit=10)
        assert [item.task_type for item in stalls] == ["micro_event_extract"]
        assert any(item.work_item_id == failed.id for item in await controls.failures(limit=10))
        async with uow() as unit:
            published = await unit.work_items.get(queued.id)
            assert published is not None and published.status is WorkItemStatus.SUCCEEDED
            claim = await unit.work_items.claim_next(
                task_types=("micro_event_extract",),
                worker_id="test",
                now=now,
                lease_expires_at=now + timedelta(minutes=5),
            )
            assert claim is not None and claim.id == other.id
            preserved = await unit.work_items.get(failed.id)
            assert preserved is not None and preserved.status is WorkItemStatus.FAILED
            await unit.commit()
        await controls.set_publishing(enabled=True, reason="resume", now=now)
        assert any(
            item.task_type == "archive_publish"
            for item in await controls.queue_stalls(now=now + timedelta(hours=1), limit=10)
        )
        async with uow() as unit:
            same = await unit.work_items.get(waiting.id)
            assert same is not None and same.status is WorkItemStatus.PENDING
    finally:
        await database.dispose()
