from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind
from codex_sdk_cli.application.operations.selection import SelectedVideos
from codex_sdk_cli.application.segments.backfill import (
    BackfillSegmentsCommand,
    BackfillSegmentsUseCase,
)
from codex_sdk_cli.application.segments.commands import ClassifySegmentsCommand
from codex_sdk_cli.application.segments.ports import (
    SegmentInputPlannerPort,
    SegmentPublishedTimelineReaderPort,
)
from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionEngine,
    WorkExecutionResult,
    WorkExecutorPort,
    WorkExecutorRegistry,
)
from codex_sdk_cli.application.work.ports import CreateWorkflowRun
from codex_sdk_cli.application.workflows.commands import (
    ProcessToPublishCommand,
    StartProcessToPublishUseCase,
)
from codex_sdk_cli.application.workflows.coordinator import ProcessToPublishCoordinator
from codex_sdk_cli.domains.prompts.exceptions import PromptConflict, PromptNotFound
from codex_sdk_cli.domains.segments.models import SegmentSourceChangedError
from codex_sdk_cli.domains.work.models import WorkExecutionMode
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection
from tests.test_archive_publishing_control import _create
from tests.test_workflow_coordinator import _insert_video, _run_stage, _stage_item


class Planner(SegmentInputPlannerPort):
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def prepare(self, **kwargs) -> dict[str, object]:
        if self.error is not None:
            raise self.error
        return {"videoId": 1, "sourceTimelineWorkItemId": kwargs["timeline_work_item_id"]}


class PublishedTimeline(SegmentPublishedTimelineReaderPort):
    def __init__(self, work_id: int) -> None:
        self.work_id = work_id

    async def latest(self, **kwargs) -> int:
        return self.work_id


class InvalidClassification(WorkExecutorPort):
    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        raise ApplicationError(
            code="segments.invalid_output", message="Invalid test output", kind=ErrorKind.CONFLICT
        )


@pytest.mark.parametrize(
    "error",
    [PromptConflict("missing"), PromptNotFound("missing"), SegmentSourceChangedError("changed")],
)
def test_planning_failure_blocks_only_affected_workflow(
    migrated_database_path: Path, error: Exception
) -> None:
    asyncio.run(_planning_failure(migrated_database_path, error))


async def _planning_failure(path: Path, error: Exception) -> None:
    database = create_database_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    sessions = create_session_factory(database)

    def uow():
        return SqlAlchemyWorkUnitOfWork(sessions)

    try:
        await _insert_video(sessions)
        async with uow() as unit:
            timeline, _ = await unit.work_items.get_or_create(_create("timeline_compose", "source"))
            await unit.commit()
        # This source uses an inline test item; mark it complete without external I/O.
        async with uow() as unit:
            await unit.work_items.start_inline(
                work_item_id=timeline.id,
                worker_id="test",
                now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            await unit.work_items.mark_succeeded(
                work_item_id=timeline.id, now=datetime.now(UTC), output_json={"compositionId": 1}
            )
            await unit.workflows.create_or_get(
                CreateWorkflowRun(
                    workflow_type="classify_to_publish",
                    workflow_version="v3",
                    video_id=1,
                    input_hash="test",
                    available_at=datetime.now(UTC),
                    options_json={
                        "youtubeVideoId": "abcdefghijk",
                        "sourceTimelineWorkItemId": timeline.id,
                        "segment_model": "gpt-6-luna",
                        "segment_reasoning_effort": "high",
                        "segment_taxonomy_version": "v1.6",
                        "segment_timeout_seconds": 600,
                    },
                )
            )
            await unit.commit()
        coordinator = ProcessToPublishCoordinator(
            unit_of_work_factory=uow, segment_inputs=Planner(error), worker_id="test"
        )
        result = await coordinator.run_once()
        assert result.status == "blocked" and result.workflow_run_id is not None
        async with uow() as unit:
            blocked = await unit.workflows.get(result.workflow_run_id)
        assert blocked is not None and blocked.lease_owner is None
        assert blocked.error_code == (
            "segments.source_changed"
            if isinstance(error, SegmentSourceChangedError)
            else "segments.prompt_not_ready"
        )
        await StartProcessToPublishUseCase(
            videos=SqlAlchemyVideoSelection(sessions), unit_of_work_factory=uow
        ).execute(ProcessToPublishCommand(selection=SelectedVideos((1,))))
        assert (await coordinator.run_once()).current_stage == "transcript_collect"
    finally:
        await database.dispose()


def test_explicit_backfill_retry_resumes_after_automatic_attempt_limit(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_retry_backfill(migrated_database_path))


async def _retry_backfill(path: Path) -> None:
    database = create_database_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    sessions = create_session_factory(database)

    def uow():
        return SqlAlchemyWorkUnitOfWork(sessions)

    try:
        await _insert_video(sessions)
        async with uow() as unit:
            source, _ = await unit.work_items.get_or_create(
                replace(
                    _create("timeline_compose", "source"),
                    execution_mode=WorkExecutionMode.WORKER,
                )
            )
            await unit.commit()
        await _run_stage(
            uow, "timeline_compose", WorkExecutionResult(output_json={"compositionId": 1})
        )
        backfill = BackfillSegmentsUseCase(
            videos=SqlAlchemyVideoSelection(sessions),
            unit_of_work_factory=uow,
            planner=Planner(),
            published_sources=PublishedTimeline(source.id),
        )
        command = BackfillSegmentsCommand(ClassifySegmentsCommand(selection=SelectedVideos((1,))))
        enqueued = await backfill.execute(command)
        workflow_id = enqueued.items[0].workflow_run_id
        assert workflow_id is not None
        coordinator = ProcessToPublishCoordinator(
            unit_of_work_factory=uow, segment_inputs=Planner(), worker_id="test"
        )
        invalid = WorkExecutionEngine(
            unit_of_work_factory=uow,
            task_types=("segment_classify",),
            worker_id="test",
            registry=WorkExecutorRegistry(
                {
                    "segment_classify": InvalidClassification,
                }
            ),
        )
        for _ in range(3):
            assert (await coordinator.run_once()).current_stage == "segment_classify"
            assert not (await invalid.run_once_with_result()).succeeded
        assert (await coordinator.run_once()).status == "failed"
        work = await _stage_item(uow, workflow_id, "segment_classify")
        assert (await backfill.execute(command)).items[0].status == "failed"
        retried = await backfill.execute(
            replace(
                command,
                classification=replace(
                    command.classification,
                    retry_failed=True,
                ),
            )
        )
        assert retried.items[0].workflow_run_id == workflow_id
        assert (await coordinator.run_once()).current_stage == "segment_classify"
        completed_id = await _run_stage(
            uow,
            "segment_classify",
            WorkExecutionResult(
                output_json={
                    "classificationId": 1,
                    "inputFingerprint": work.input_hash,
                }
            ),
        )
        assert completed_id == work.id
        assert (await coordinator.run_once()).current_stage == "archive_publish"
        async with uow() as unit:
            assert len(await unit.work_attempts.list_for_work_item(work.id)) == 4
    finally:
        await database.dispose()
