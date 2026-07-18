from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import psutil
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from codex_sdk_cli.api.dependencies import get_database_session_factory
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.api.use_case_dependencies.operation_events import (
    get_record_operator_mutation_use_case,
)
from codex_sdk_cli.api.use_case_dependencies.streamers import get_delete_streamer_use_case
from codex_sdk_cli.application.operation_events.operator_audit import (
    RecordOperatorMutationUseCase,
)
from codex_sdk_cli.application.work.ports import CreateWorkBatch, CreateWorkflowRun
from codex_sdk_cli.domains.operation_events.ports import OperationEventCreate
from codex_sdk_cli.domains.streamers.exceptions import StreamerNotFound
from codex_sdk_cli.infra.automation.processes import PsutilManagedProcessReader
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork


class FakeProcess:
    def __init__(
        self,
        *,
        command_line: list[str],
        cwd: Path,
        started_at: float = 1_700_000_000,
    ) -> None:
        self._command_line = command_line
        self._cwd = cwd
        self._started_at = started_at

    def cmdline(self) -> list[str]:
        return self._command_line

    def cwd(self) -> str:
        return str(self._cwd)

    def create_time(self) -> float:
        return self._started_at


class FakeDeleteStreamerUseCase:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[int] = []

    async def execute(self, streamer_id: int) -> dict[str, bool]:
        if self.fail:
            raise StreamerNotFound("Streamer not found.")
        self.deleted.append(streamer_id)
        return {"success": True}


class FakeOperatorAudit:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(self, **values: object) -> None:
        self.calls.append(values)


class RecordingEventRecorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        if self.fail:
            raise RuntimeError("audit storage unavailable")
        self.events.append(event)


def test_process_inventory_validates_identity_without_exposing_sensitive_values(
    tmp_path: Path,
) -> None:
    pid_dir = tmp_path / ".home-deploy" / "pids"
    pid_dir.mkdir(parents=True)
    (pid_dir / "transcript-worker.pid").write_text("200", encoding="utf-8")
    (pid_dir / "micro-event-worker.pid").write_text("201", encoding="utf-8")
    (pid_dir / "workflow-coordinator.pid").write_text("202", encoding="utf-8")
    (pid_dir / "pipeline-scheduler.pid").write_text("203", encoding="utf-8")

    processes: dict[int, FakeProcess] = {
        100: FakeProcess(
            command_line=["uvicorn", "codex_sdk_cli.api.main:app", "secret-token"],
            cwd=tmp_path,
        ),
        200: FakeProcess(
            command_line=[
                str(tmp_path / ".venv" / "Scripts" / "python.exe"),
                "-c",
                "run_transcript",
            ],
            cwd=tmp_path.parent,
        ),
        202: FakeProcess(command_line=["another-program"], cwd=tmp_path),
    }

    def process_factory(pid: int) -> FakeProcess:
        if pid == 201:
            raise psutil.NoSuchProcess(pid)
        if pid == 203:
            raise psutil.AccessDenied(pid)
        return processes[pid]

    reader = PsutilManagedProcessReader(
        pid_dir=pid_dir,
        repository_root=tmp_path,
        process_factory=process_factory,  # type: ignore[arg-type]
        current_pid=lambda: 100,
        host_name=lambda: "ops-host",
        platform_name=lambda: "Windows-test",
    )
    inventory = asyncio.run(reader.read(observed_at=datetime(2026, 7, 14, tzinfo=UTC)))
    items = {item.name: item for item in inventory.items}

    assert inventory.host_name == "ops-host"
    assert items["api"].state == "running"
    assert items["transcript-worker"].state == "running"
    assert items["micro-event-worker"].state == "stale_pid"
    assert items["workflow-coordinator"].state == "identity_mismatch"
    assert items["pipeline-scheduler"].state == "unreadable"
    assert items["ops-ui"].state == "stopped"
    serialized = repr(inventory)
    assert "secret-token" not in serialized
    assert str(tmp_path) not in serialized


def test_workflow_and_batch_lists_filter_and_page(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_workflow_and_batch_lists(migrated_database_path))


def test_operator_reason_is_required_and_success_is_audited() -> None:
    asyncio.run(_exercise_operator_reason())


def test_operator_audit_metadata_and_best_effort_failure() -> None:
    recorder = RecordingEventRecorder()
    asyncio.run(
        RecordOperatorMutationUseCase(recorder).execute(
            mutation="archived",
            target_type="prompt_version",
            target_id=12,
            action="archive",
            reason="replace invalid prompt",
            metadata={"promptKey": "timeline_compose_v1"},
        )
    )
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event.event_type == "operator.resource_archived"
    assert event.metadata_json == {
        "targetType": "prompt_version",
        "targetId": 12,
        "action": "archive",
        "reason": "replace invalid prompt",
        "promptKey": "timeline_compose_v1",
    }

    asyncio.run(
        RecordOperatorMutationUseCase(RecordingEventRecorder(fail=True)).execute(
            mutation="deleted",
            target_type="channel",
            target_id=3,
            action="delete",
            reason="remove duplicate channel",
        )
    )


async def _exercise_workflow_and_batch_lists(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)
    now = datetime(2026, 7, 14, tzinfo=UTC)
    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO streamers(id, name, publish_profile_id) "
                    "VALUES (1, 'Ops', 1)"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO channels(id, streamer_id, handle, name) "
                    "VALUES (1, 1, '@ops', 'Ops')"
                )
            )
            for video_id in (1, 2, 3):
                await session.execute(
                    text(
                        "INSERT INTO videos(id, channel_id, youtube_video_id, title, "
                        "description, published_at, created_at, is_embeddable) "
                        "VALUES (:id, 1, :youtube_id, :title, '', :now, :now, 1)"
                    ),
                    {
                        "id": video_id,
                        "youtube_id": f"video{video_id:06d}",
                        "title": f"Video {video_id}",
                        "now": now,
                    },
                )
            await session.commit()

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            for video_id in (1, 2, 3):
                workflow, _ = await unit_of_work.workflows.create_or_get(
                    CreateWorkflowRun(
                        workflow_type="process_to_publish",
                        workflow_version="v2",
                        video_id=video_id,
                        input_hash=str(video_id) * 64,
                        options_json={"captionSlaDeadline": now.isoformat()},
                        available_at=now,
                    )
                )
                if video_id == 2:
                    await unit_of_work.workflows.mark_failed(
                        workflow_run_id=workflow.id,
                        error_code="timeline.validation_failed",
                        error_message="Invalid timeline.",
                        blocked=False,
                        now=now,
                    )
            first_batch = await unit_of_work.work_batches.create(
                CreateWorkBatch(
                    operation_type="video_collect",
                    actor_type="manual_api",
                    selection_json={},
                    options_json={},
                    requested_count=1,
                )
            )
            await unit_of_work.work_batches.complete(
                batch_id=first_batch.id,
                status="succeeded",
                completed_at=now,
            )
            await unit_of_work.work_batches.create(
                CreateWorkBatch(
                    operation_type="archive_publish",
                    actor_type="manual_api",
                    selection_json={},
                    options_json={},
                    requested_count=2,
                )
            )
            await unit_of_work.commit()

        app = create_app()
        app.dependency_overrides[get_database_session_factory] = lambda: session_factory
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            workflows = await client.get(
                "/ops/workflows",
                params={"workflowType": "process_to_publish", "limit": 1},
            )
            assert workflows.status_code == 200, workflows.text
            first_page = workflows.json()
            assert [item["videoId"] for item in first_page["items"]] == [3]
            assert first_page["nextCursor"] is not None
            second_page = await client.get(
                "/ops/workflows",
                params={"cursor": first_page["nextCursor"], "limit": 1},
            )
            assert [item["videoId"] for item in second_page.json()["items"]] == [2]
            failed = await client.get(
                "/ops/workflows",
                params={"status": "failed", "videoId": 2},
            )
            assert failed.json()["items"][0]["errorCode"] == "timeline.validation_failed"

            batches = await client.get(
                "/ops/work-batches",
                params={"operationType": "video_collect", "status": "succeeded"},
            )
            assert batches.status_code == 200, batches.text
            assert batches.json()["items"] == [
                {
                    "id": first_batch.id,
                    "operationType": "video_collect",
                    "status": "succeeded",
                    "actorType": "manual_api",
                    "requestedCount": 1,
                    "createdAt": batches.json()["items"][0]["createdAt"],
                    "completedAt": batches.json()["items"][0]["completedAt"],
                }
            ]
    finally:
        await engine.dispose()


async def _exercise_operator_reason() -> None:
    delete_use_case = FakeDeleteStreamerUseCase()
    audit = FakeOperatorAudit()
    app = create_app()
    app.dependency_overrides[get_delete_streamer_use_case] = lambda: delete_use_case
    app.dependency_overrides[get_record_operator_mutation_use_case] = lambda: audit

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        missing = await client.delete("/ops/streamers/7")
        short = await client.delete(
            "/ops/streamers/7", headers={"X-Operator-Reason": "no"}
        )
        succeeded = await client.delete(
            "/ops/streamers/7",
            headers={"X-Operator-Reason": "remove duplicate test record"},
        )

    assert missing.status_code == 422
    assert short.status_code == 422
    assert succeeded.status_code == 200, succeeded.text
    assert delete_use_case.deleted == [7]
    assert audit.calls == [
        {
            "mutation": "deleted",
            "target_type": "streamer",
            "target_id": 7,
            "action": "delete",
            "reason": "remove duplicate test record",
        }
    ]

    failing_delete = FakeDeleteStreamerUseCase(fail=True)
    failing_audit = FakeOperatorAudit()
    failed_app = create_app()
    failed_app.dependency_overrides[get_delete_streamer_use_case] = lambda: failing_delete
    failed_app.dependency_overrides[get_record_operator_mutation_use_case] = lambda: failing_audit
    async with AsyncClient(
        transport=ASGITransport(app=failed_app),
        base_url="http://testserver",
    ) as client:
        failed = await client.delete(
            "/ops/streamers/9",
            headers={"X-Operator-Reason": "verify missing record"},
        )
    assert failed.status_code == 404
    assert failing_audit.calls == []
