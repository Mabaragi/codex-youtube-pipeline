from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from codex_sdk_cli.application.operations.selection import SelectedVideos
from codex_sdk_cli.application.segments.backfill import BackfillSegmentsCommand
from codex_sdk_cli.application.segments.commands import ClassifySegmentsCommand
from codex_sdk_cli.application.segments.executors import SegmentClassificationExecutor
from codex_sdk_cli.application.work.execution import (
    WorkExecutionEngine,
    WorkExecutionResult,
    WorkExecutorRegistry,
)
from codex_sdk_cli.application.work.ports import CreateWorkItem
from codex_sdk_cli.application.workflows.archive import ArchivePublishExecutor
from codex_sdk_cli.application.workflows.coordinator import ProcessToPublishCoordinator
from codex_sdk_cli.bootstrap.segments import (
    SegmentInputPlanner,
    classify_segments_use_case,
)
from codex_sdk_cli.domains.segments.models import SegmentSourceChangedError
from codex_sdk_cli.domains.work.models import WorkExecutionMode
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.segments.publication import SqlAlchemySegmentPublicationReader
from codex_sdk_cli.infra.segments.repository import (
    SegmentClassificationModel,
    SqlAlchemySegmentResultStore,
)
from codex_sdk_cli.infra.segments.source import SqlAlchemySegmentSourceReader
from codex_sdk_cli.infra.timelines.repository import TimelineCompositionModel
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from tests.test_segments import Runtime
from tests.test_workflow_coordinator import FakeArchivePublisher, _insert_video, _run_stage


def test_versioned_empty_classification_and_publisher_source_validation(
    migrated_database_path: Path,
):
    asyncio.run(exercise(migrated_database_path))


async def exercise(path):
    from datetime import UTC, datetime

    engine = create_database_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    sessions = create_session_factory(engine)

    def uow():
        return SqlAlchemyWorkUnitOfWork(sessions)

    try:
        await _insert_video(sessions)
        async with uow() as unit:
            timeline, _ = await unit.work_items.get_or_create(
                CreateWorkItem(
                    task_type="timeline_compose",
                    subject_type="video",
                    subject_id=1,
                    external_key="abcdefghijk",
                    task_version="v1",
                    input_hash="timeline",
                    idempotency_key="timeline",
                    execution_mode=WorkExecutionMode.WORKER,
                    timeout_seconds=600,
                    input_json={},
                    available_at=datetime.now(UTC),
                )
            )
            await unit.commit()
        await _run_stage(
            uow, "timeline_compose", WorkExecutionResult(output_json={"compositionId": 1})
        )
        async with sessions() as session:
            composition = TimelineCompositionModel(
                video_task_id=timeline.id,
                work_item_id=timeline.id,
                video_id=1,
                source_micro_event_task_id=timeline.id,
                source_micro_event_fingerprint="a" * 64,
                copy_style="test",
                title="test",
                summary="test",
                display_title="test",
                display_summary="test",
                main_topics=[],
                output_json={"timeline_state": "empty"},
                validation_warnings=[],
            )
            session.add(composition)
            await session.commit()
            composition_id = composition.id
        commands = classify_segments_use_case(sessions)
        command = ClassifySegmentsCommand(selection=SelectedVideos((1,)))
        first = await commands.execute(command)
        repeated = await commands.execute(command)
        assert first.created_count == 1 and repeated.reused_count == 1
        assert first.items[0].work_item_id == repeated.items[0].work_item_id
        runtime = Runtime([])
        executor = SegmentClassificationExecutor(
            source=SqlAlchemySegmentSourceReader(sessions),
            results=SqlAlchemySegmentResultStore(sessions),
            runtime=runtime,
        )
        worker = WorkExecutionEngine(
            unit_of_work_factory=uow,
            registry=WorkExecutorRegistry({"segment_classify": lambda: executor}),
            task_types=("segment_classify",),
            worker_id="test",
        )
        run = await worker.run_once_with_result()
        assert run.output_json is not None and run.work_item_id is not None
        assert run.succeeded and run.output_json["segmentCount"] == 0 and not runtime.calls
        async with uow() as unit:
            work = await unit.work_items.get(run.work_item_id)
        assert work is not None
        pinned = {
            "videoId": 1,
            "sourceTimelineWorkItemId": timeline.id,
            "sourceClassificationWorkItemId": work.id,
            "sourceClassificationId": run.output_json["classificationId"],
            "sourceClassificationFingerprint": work.input_hash,
        }
        from codex_sdk_cli.application.segments.backfill import BackfillSegmentsUseCase
        from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection

        class PublishedSource:
            async def latest(self, **kwargs):
                return timeline.id

        backfills = BackfillSegmentsUseCase(
            videos=SqlAlchemyVideoSelection(sessions),
            unit_of_work_factory=uow,
            planner=SegmentInputPlanner(sessions),
            published_sources=PublishedSource(),
        )
        backfill_command = BackfillSegmentsCommand(classification=command)
        backfill = await backfills.execute(backfill_command)
        again = await backfills.execute(backfill_command)
        assert (
            again.reused_count == 1
            and again.items[0].workflow_run_id == backfill.items[0].workflow_run_id
        )
        publisher = FakeArchivePublisher()
        archive_worker = WorkExecutionEngine(
            unit_of_work_factory=uow,
            registry=WorkExecutorRegistry(
                {
                    "archive_publish": lambda: ArchivePublishExecutor(publisher),
                }
            ),
            task_types=("archive_publish",),
            worker_id="archive:test",
        )
        coordinator = ProcessToPublishCoordinator(
            unit_of_work_factory=uow,
            segment_inputs=SegmentInputPlanner(sessions),
            worker_id="workflow:test",
        )
        waiting = await coordinator.run_once()
        assert (waiting.status, waiting.current_stage) == ("waiting", "archive_publish")
        assert publisher.source_timeline_work_item_id is None
        assert (await archive_worker.run_once_with_result()).succeeded
        assert (await coordinator.run_once()).status == "succeeded"
        async with uow() as unit:
            workflow_id = backfill.items[0].workflow_run_id
            assert workflow_id is not None
            steps = await unit.workflows.list_steps(workflow_id)
        assert [s.stage_name for s in steps] == ["segment_classify", "archive_publish"]
        assert steps[0].work_item_id == work.id
        assert publisher.source_timeline_work_item_id == timeline.id
        async with sessions() as session:
            reader = SqlAlchemySegmentPublicationReader(session)
            payload = await reader.load(pinned)
            assert payload["taxonomyVersion"] == "v1.6" and payload["segments"] == []
            for key, value in [
                ("videoId", 2),
                ("sourceTimelineWorkItemId", 999),
                ("sourceClassificationFingerprint", "bad"),
            ]:
                with pytest.raises(SegmentSourceChangedError):
                    await reader.load({**pinned, key: value})
            changed = await session.get(TimelineCompositionModel, composition_id)
            assert changed is not None
            changed.display_summary = "edited after classification"
            await session.commit()
        async with sessions() as session:
            with pytest.raises(SegmentSourceChangedError, match="Source changed"):
                await SqlAlchemySegmentPublicationReader(session).load(pinned)
        second = await commands.execute(command)
        assert second.created_count == 1 and second.items[0].work_item_id != work.id
        assert (await worker.run_once_with_result()).succeeded
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(SegmentClassificationModel))
                == 2
            )
    finally:
        await engine.dispose()
