from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import text

from codex_sdk_cli.application.operations.selection import SelectedVideos
from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionEngine,
    WorkExecutionResult,
    WorkExecutorPort,
    WorkExecutorRegistry,
)
from codex_sdk_cli.application.workflows.archive import ArchivePublishExecutor
from codex_sdk_cli.application.workflows.commands import (
    ProcessToPublishCommand,
    StartProcessToPublishUseCase,
)
from codex_sdk_cli.application.workflows.coordinator import ProcessToPublishCoordinator
from codex_sdk_cli.application.workflows.ports import ArchivePublisherPort, PublishedArchive
from codex_sdk_cli.domains.work.models import WorkflowStatus, WorkItemStatus
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.archive_execution import InlineWorkExecutionRunner
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection


class StaticExecutor(WorkExecutorPort):
    def __init__(self, result: WorkExecutionResult) -> None:
        self._result = result

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        assert context.work_item.subject_id == 1
        return self._result


class FakeArchivePublisher(ArchivePublisherPort):
    def __init__(self) -> None:
        self.source_timeline_work_item_id: int | None = None

    async def publish(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        video_id: int,
        source_timeline_work_item_id: int,
        publish_mode: str,
        environment: str,
        variant: str,
        schema_version: int,
    ) -> PublishedArchive:
        assert work_item_id > 0 and work_attempt_id > 0
        assert (video_id, publish_mode, environment, variant, schema_version) == (
            1,
            "prod",
            "prod",
            "control",
            1,
        )
        self.source_timeline_work_item_id = source_timeline_work_item_id
        return PublishedArchive(
            video_id=video_id,
            artifact_id=100,
            public_url="https://archive.example/video-1.json",
        )


def test_process_to_publish_coordinator_resumes_each_durable_stage(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_workflow(migrated_database_path))


async def _exercise_workflow(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    try:
        await _insert_video(session_factory)
        started = await StartProcessToPublishUseCase(
            videos=SqlAlchemyVideoSelection(session_factory),
            unit_of_work_factory=unit_of_work_factory,
        ).execute(ProcessToPublishCommand(selection=SelectedVideos((1,))))
        workflow_id = started.items[0].workflow_run_id
        assert workflow_id is not None

        archive_publisher = FakeArchivePublisher()
        archive_engine = WorkExecutionEngine(
            unit_of_work_factory=unit_of_work_factory,
            registry=WorkExecutorRegistry(
                {"archive_publish": lambda: ArchivePublishExecutor(archive_publisher)}
            ),
            task_types=("archive_publish",),
            worker_id="archive:test",
        )
        coordinator = ProcessToPublishCoordinator(
            unit_of_work_factory=unit_of_work_factory,
            inline_runner=InlineWorkExecutionRunner(archive_engine),
            worker_id="coordinator:test",
        )

        first = await coordinator.run_once()
        assert (first.status, first.current_stage) == ("waiting", "transcript_collect")
        transcript_id = await _run_stage(
            unit_of_work_factory,
            "transcript_collect",
            WorkExecutionResult(
                output_json={
                    "videoId": 1,
                    "youtubeVideoId": "abcdefghijk",
                    "transcriptId": 10,
                    "languageCode": "ko",
                    "responseSha256": "a" * 64,
                },
                output_transcript_id=10,
            ),
        )

        cue_wait = await coordinator.run_once()
        assert (cue_wait.status, cue_wait.current_stage) == (
            "waiting",
            "transcript_cue_generate",
        )
        await _run_stage(
            unit_of_work_factory,
            "transcript_cue_generate",
            WorkExecutionResult(
                output_json={"transcriptId": 10, "cueCount": 4},
                output_transcript_id=10,
            ),
        )

        micro_wait = await coordinator.run_once()
        assert (micro_wait.status, micro_wait.current_stage) == (
            "waiting",
            "micro_event_extract",
        )
        micro_id = await _run_stage(
            unit_of_work_factory,
            "micro_event_extract",
            WorkExecutionResult(
                output_json={"videoId": 1, "transcriptId": 10, "microEventCount": 20}
            ),
        )

        timeline_wait = await coordinator.run_once()
        assert (timeline_wait.status, timeline_wait.current_stage) == (
            "waiting",
            "timeline_compose",
        )
        timeline_id = await _run_stage(
            unit_of_work_factory,
            "timeline_compose",
            WorkExecutionResult(output_json={"videoId": 1, "compositionId": 30}),
        )

        finished = await coordinator.run_once()
        assert finished.status == "succeeded"
        assert archive_publisher.source_timeline_work_item_id == timeline_id

        async with unit_of_work_factory() as unit_of_work:
            workflow = await unit_of_work.workflows.get(workflow_id)
            steps = await unit_of_work.workflows.list_steps(workflow_id)
        assert workflow is not None and workflow.status is WorkflowStatus.SUCCEEDED
        assert [step.stage_name for step in steps] == [
            "transcript_collect",
            "transcript_cue_generate",
            "micro_event_extract",
            "timeline_compose",
            "archive_publish",
        ]
        assert all(step.status == WorkItemStatus.SUCCEEDED.value for step in steps)
        assert transcript_id < micro_id < timeline_id
    finally:
        await engine.dispose()


async def _run_stage(
    unit_of_work_factory,
    task_type: str,
    result: WorkExecutionResult,
) -> int:
    engine = WorkExecutionEngine(
        unit_of_work_factory=unit_of_work_factory,
        registry=WorkExecutorRegistry({task_type: lambda: StaticExecutor(result)}),
        task_types=(task_type,),
        worker_id=f"{task_type}:test",
    )
    run = await engine.run_once_with_result()
    assert run.processed is True and run.succeeded is True
    assert run.work_item_id is not None
    return run.work_item_id


async def _insert_video(session_factory) -> None:
    async with session_factory() as session:
        await session.execute(text("INSERT INTO streamers(id, name) VALUES (1, 'Nagi')"))
        await session.execute(
            text(
                "INSERT INTO channels(id, streamer_id, handle, name) "
                "VALUES (1, 1, '@nagi', 'Nagi')"
            )
        )
        await session.execute(
            text(
                "INSERT INTO videos(id, channel_id, youtube_video_id, title, description, "
                "published_at, is_embeddable) VALUES "
                "(1, 1, 'abcdefghijk', 'Test', '', "
                "'2026-07-01T00:00:00+00:00', 1)"
            )
        )
        await session.commit()
