from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from codex_sdk_cli.application.operations.selection import SelectedVideos
from codex_sdk_cli.application.scheduler.quota import daily_quota_window
from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionEngine,
    WorkExecutionResult,
    WorkExecutorPort,
    WorkExecutorRegistry,
    WorkRunResult,
)
from codex_sdk_cli.application.workflows.archive import ArchivePublishExecutor
from codex_sdk_cli.application.workflows.commands import (
    ProcessToPublishCommand,
    StartProcessToPublishUseCase,
)
from codex_sdk_cli.application.workflows.coordinator import ProcessToPublishCoordinator
from codex_sdk_cli.application.workflows.ports import (
    ArchivePublisherPort,
    PublishedArchive,
    TranscriptArtifact,
    TranscriptArtifactReaderPort,
)
from codex_sdk_cli.domains.work.models import WorkflowStatus, WorkItemStatus
from codex_sdk_cli.infra.automation.repository import SqlAlchemyAutomationRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.scheduler import SqlAlchemyWorkflowCandidateReader
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection
from codex_sdk_cli.settings import CliSettings
from codex_sdk_cli.workers.asr import run_worker as run_asr_worker


class StaticExecutor(WorkExecutorPort):
    def __init__(self, result: WorkExecutionResult) -> None:
        self._result = result

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        assert context.work_item.subject_id == 1
        return self._result


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


class UnusedInlineRunner:
    async def run(self, work_item_id: int) -> WorkRunResult:
        raise AssertionError(f"unexpected inline work {work_item_id}")


class PausedInlineRunner:
    async def run(self, work_item_id: int) -> WorkRunResult:
        return WorkRunResult(processed=False, work_item_id=work_item_id)


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


class FakeTranscriptArtifacts(TranscriptArtifactReaderPort):
    async def find_latest(self, *, youtube_video_id: str) -> TranscriptArtifact | None:
        assert youtube_video_id == "abcdefghijk"
        return TranscriptArtifact(transcript_id=10, response_sha256="c" * 64)


def test_process_to_publish_coordinator_resumes_each_durable_stage(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_workflow(migrated_database_path))


def test_process_to_publish_v3_pins_classification_and_both_dependencies(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_workflow(migrated_database_path, segment_enabled=True))


class FakeSegmentInputs:
    async def prepare(self, **kwargs):
        return {
            "videoId": kwargs["video_id"],
            "sourceTimelineWorkItemId": kwargs["timeline_work_item_id"],
            "sourceFingerprint": "a" * 64,
            "model": kwargs["model"],
            "reasoningEffort": kwargs["reasoning_effort"],
        }


def test_process_to_publish_v2_rechecks_then_branches_to_asr(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_asr_branch(migrated_database_path))


def test_process_to_publish_recheck_discovers_transcript_before_asr(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_recheck_discovers_transcript(migrated_database_path))


def test_process_to_publish_replaces_pending_collect_with_existing_artifact(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_artifact_reuse(migrated_database_path))


async def _exercise_artifact_reuse(database_path: Path) -> None:
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
        initial = ProcessToPublishCoordinator(
            unit_of_work_factory=unit_of_work_factory,
            worker_id="coordinator:initial",
        )
        assert (await initial.run_once()).current_stage == "transcript_collect"
        async with unit_of_work_factory() as unit_of_work:
            first_steps = await unit_of_work.workflows.list_steps(workflow_id)
        original_item_id = first_steps[0].work_item_id
        assert original_item_id is not None

        resumed = ProcessToPublishCoordinator(
            unit_of_work_factory=unit_of_work_factory,
            transcript_artifacts=FakeTranscriptArtifacts(),
            worker_id="coordinator:resumed",
        )
        result = await resumed.run_once()
        assert result.current_stage == "transcript_cue_generate"
        async with unit_of_work_factory() as unit_of_work:
            original = await unit_of_work.work_items.get(original_item_id)
            steps = await unit_of_work.workflows.list_steps(workflow_id)
            transcript = await unit_of_work.work_items.get(steps[0].work_item_id or 0)
        assert original is not None and original.status is WorkItemStatus.CANCELED
        assert transcript is not None and transcript.status is WorkItemStatus.SUCCEEDED
        assert transcript.output_transcript_id == 10
        assert transcript.input_json["artifactReuse"] is True
    finally:
        await engine.dispose()


async def _exercise_workflow(database_path: Path, *, segment_enabled: bool = False) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    try:
        await _insert_video(session_factory)
        started = await StartProcessToPublishUseCase(
            videos=SqlAlchemyVideoSelection(session_factory),
            unit_of_work_factory=unit_of_work_factory,
        ).execute(
            ProcessToPublishCommand(selection=SelectedVideos((1,)), segment_enabled=segment_enabled)
        )
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
            worker_id="coordinator:test",
            segment_inputs=FakeSegmentInputs(),
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

        if segment_enabled:
            waiting = await coordinator.run_once()
            assert waiting.current_stage == "segment_classify"
            item = await _stage_item(unit_of_work_factory, workflow_id, "segment_classify")
            await _run_stage(
                unit_of_work_factory,
                "segment_classify",
                WorkExecutionResult(
                    output_json={
                        "classificationId": 40,
                        "sourceTimelineWorkItemId": timeline_id,
                        "inputFingerprint": item.input_hash,
                    },
                ),
            )

        paused_coordinator = ProcessToPublishCoordinator(
            unit_of_work_factory=unit_of_work_factory,
            worker_id="coordinator:paused",
        )
        paused = await paused_coordinator.run_once()
        assert (paused.status, paused.current_stage) == ("waiting", "archive_publish")
        pending_archive = await _stage_item(unit_of_work_factory, workflow_id, "archive_publish")
        assert pending_archive.status is WorkItemStatus.PENDING
        if segment_enabled:
            assert pending_archive.input_json["sourceClassificationId"] == 40
            assert pending_archive.input_json["sourceTimelineWorkItemId"] == timeline_id
            async with session_factory() as session:
                dependencies = (
                    (
                        await session.execute(
                            text(
                                "SELECT dependency_work_item_id FROM work_item_dependencies "
                                "WHERE work_item_id=:id"
                            ),
                            {"id": pending_archive.id},
                        )
                    )
                    .scalars()
                    .all()
                )
            classification_item = await _stage_item(
                unit_of_work_factory, workflow_id, "segment_classify"
            )
            assert set(dependencies) == {timeline_id, classification_item.id}

        controls = SqlAlchemyAutomationRepository(session_factory)
        await controls.set_publishing(enabled=False, reason="test pause", now=datetime.now(UTC))
        assert not (await archive_engine.run_once_with_result()).processed
        async with unit_of_work_factory() as unit:
            assert await unit.work_attempts.list_for_work_item(pending_archive.id) == []
            preserved = await unit.work_items.get(pending_archive.id)
        assert preserved == pending_archive
        assert archive_publisher.source_timeline_work_item_id is None
        assert not (await coordinator.run_once()).processed
        resumed_controls = SqlAlchemyAutomationRepository(session_factory)
        await resumed_controls.set_publishing(
            enabled=True, reason="test resume", now=datetime.now(UTC)
        )
        assert (await archive_engine.run_once_with_result()).succeeded
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
            *(["segment_classify"] if segment_enabled else []),
            "archive_publish",
        ]
        assert all(step.status == WorkItemStatus.SUCCEEDED.value for step in steps)
        assert transcript_id < micro_id < timeline_id
    finally:
        await engine.dispose()


async def _exercise_asr_branch(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    try:
        clock = MutableClock(datetime(2026, 7, 16, tzinfo=UTC))
        await _insert_video(session_factory)
        started = await StartProcessToPublishUseCase(
            videos=SqlAlchemyVideoSelection(session_factory),
            unit_of_work_factory=unit_of_work_factory,
            now=clock,
        ).execute(
            ProcessToPublishCommand(
                selection=SelectedVideos((1,)),
                transcript_fallback_grace_seconds=21600,
                transcript_recheck_interval_seconds=1800,
                actor_type="system",
                automation_mode="backfill",
            )
        )
        workflow_id = started.items[0].workflow_run_id
        assert workflow_id is not None
        coordinator = ProcessToPublishCoordinator(
            unit_of_work_factory=unit_of_work_factory,
            worker_id="coordinator:test",
            now=clock,
        )

        assert (await coordinator.run_once()).current_stage == "transcript_collect"
        await _run_stage(
            unit_of_work_factory,
            "transcript_collect",
            WorkExecutionResult(
                output_json={"videoId": 1, "reason": "no_transcript"},
                outcome_code="no_transcript",
            ),
            now=clock,
        )
        first_recheck = await coordinator.run_once()
        assert first_recheck.current_stage == "transcript_recheck"
        first_recheck_item = await _stage_item(
            unit_of_work_factory, workflow_id, "transcript_recheck"
        )
        assert _aware(first_recheck_item.available_at) == clock.value + timedelta(minutes=30)

        recheck_item_id: int | None = None
        for attempt_number in range(1, 13):
            clock.advance(timedelta(minutes=30))
            current_item_id = await _run_stage(
                unit_of_work_factory,
                "transcript_collect",
                WorkExecutionResult(
                    output_json={"videoId": 1, "reason": "no_transcript"},
                    outcome_code="no_transcript",
                ),
                now=clock,
            )
            recheck_item_id = recheck_item_id or current_item_id
            assert current_item_id == recheck_item_id
            next_result = await coordinator.run_once()
            if attempt_number < 12:
                assert next_result.current_stage == "transcript_recheck"
                pending_recheck = await _stage_item(
                    unit_of_work_factory, workflow_id, "transcript_recheck"
                )
                assert _aware(pending_recheck.available_at) == clock.value + timedelta(minutes=30)
            else:
                assert next_result.current_stage == "asr_transcribe"

        assert recheck_item_id is not None
        async with unit_of_work_factory() as unit_of_work:
            attempts = await unit_of_work.work_attempts.list_for_work_item(recheck_item_id)
        assert len(attempts) == 12
        pending_asr = await _stage_item(unit_of_work_factory, workflow_id, "asr_transcribe")
        assert pending_asr.status is WorkItemStatus.PENDING
        automation = SqlAlchemyAutomationRepository(session_factory)
        state = await automation.get_state(now=clock.value)
        async with unit_of_work_factory() as unit_of_work:
            workflow = await unit_of_work.workflows.get(workflow_id)
        assert workflow is not None
        quota_window = daily_quota_window(_aware(workflow.created_at), "Asia/Seoul")
        candidates = SqlAlchemyWorkflowCandidateReader(session_factory)

        async def admitted_count() -> int:
            snapshot = await candidates.read_snapshot(
                state=state,
                quota_started_at=quota_window.started_at,
                quota_ends_at=quota_window.ends_at,
            )
            return snapshot.admitted_today_count

        assert await admitted_count() == 1
        await run_asr_worker(
            settings=CliSettings(asr_worker_enabled=False),
            stop_after_one=True,
        )
        still_pending = await _stage_item(unit_of_work_factory, workflow_id, "asr_transcribe")
        assert still_pending.id == pending_asr.id
        assert still_pending.status is WorkItemStatus.PENDING
        assert await admitted_count() == 1

        asr_id = await _run_stage(
            unit_of_work_factory,
            "asr_transcribe",
            WorkExecutionResult(
                output_json={
                    "videoId": 1,
                    "transcriptId": 11,
                    "responseSha256": "b" * 64,
                },
                output_transcript_id=11,
            ),
            now=clock,
        )
        cue_wait = await coordinator.run_once()
        assert cue_wait.current_stage == "transcript_cue_generate"
        async with unit_of_work_factory() as unit_of_work:
            workflow = await unit_of_work.workflows.get(workflow_id)
            steps = await unit_of_work.workflows.list_steps(workflow_id)
        assert workflow is not None
        assert [step.stage_name for step in steps] == [
            "transcript_collect",
            "transcript_recheck",
            "asr_transcribe",
            "transcript_cue_generate",
        ]
        asr_step = next(step for step in steps if step.stage_name == "asr_transcribe")
        assert asr_step.work_item_id == asr_id
        assert asr_id == pending_asr.id
        assert await admitted_count() == 1
    finally:
        await engine.dispose()


async def _exercise_recheck_discovers_transcript(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    try:
        clock = MutableClock(datetime(2026, 7, 16, tzinfo=UTC))
        await _insert_video(session_factory)
        started = await StartProcessToPublishUseCase(
            videos=SqlAlchemyVideoSelection(session_factory),
            unit_of_work_factory=unit_of_work_factory,
            now=clock,
        ).execute(ProcessToPublishCommand(selection=SelectedVideos((1,))))
        workflow_id = started.items[0].workflow_run_id
        assert workflow_id is not None
        coordinator = ProcessToPublishCoordinator(
            unit_of_work_factory=unit_of_work_factory,
            worker_id="coordinator:test",
            now=clock,
        )

        assert (await coordinator.run_once()).current_stage == "transcript_collect"
        await _run_stage(
            unit_of_work_factory,
            "transcript_collect",
            WorkExecutionResult(
                output_json={"videoId": 1, "reason": "no_transcript"},
                outcome_code="no_transcript",
            ),
            now=clock,
        )
        assert (await coordinator.run_once()).current_stage == "transcript_recheck"

        clock.advance(timedelta(minutes=30))
        await _run_stage(
            unit_of_work_factory,
            "transcript_collect",
            WorkExecutionResult(
                output_json={
                    "videoId": 1,
                    "transcriptId": 12,
                    "responseSha256": "d" * 64,
                },
                output_transcript_id=12,
            ),
            now=clock,
        )
        assert (await coordinator.run_once()).current_stage == "transcript_cue_generate"
        async with unit_of_work_factory() as unit_of_work:
            steps = await unit_of_work.workflows.list_steps(workflow_id)
        assert "asr_transcribe" not in {step.stage_name for step in steps}
    finally:
        await engine.dispose()


async def _run_stage(
    unit_of_work_factory,
    task_type: str,
    result: WorkExecutionResult,
    *,
    now=None,
) -> int:
    engine = WorkExecutionEngine(
        unit_of_work_factory=unit_of_work_factory,
        registry=WorkExecutorRegistry({task_type: lambda: StaticExecutor(result)}),
        task_types=(task_type,),
        worker_id=f"{task_type}:test",
        now=now,
    )
    run = await engine.run_once_with_result()
    assert run.processed is True and run.succeeded is True
    assert run.work_item_id is not None
    return run.work_item_id


async def _stage_item(unit_of_work_factory, workflow_id: int, stage_name: str):
    async with unit_of_work_factory() as unit_of_work:
        steps = await unit_of_work.workflows.list_steps(workflow_id)
        step = next(step for step in steps if step.stage_name == stage_name)
        assert step.work_item_id is not None
        item = await unit_of_work.work_items.get(step.work_item_id)
    assert item is not None
    return item


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _insert_video(session_factory) -> None:
    async with session_factory() as session:
        await session.execute(
            text("INSERT INTO streamers(id, name, publish_profile_id) VALUES (1, 'Nagi', 1)")
        )
        await session.execute(
            text(
                "INSERT INTO channels(id, streamer_id, handle, name) VALUES (1, 1, '@nagi', 'Nagi')"
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
