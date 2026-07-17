from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from sqlalchemy import text

from codex_sdk_cli.application.operations.selection import SelectedVideos
from codex_sdk_cli.application.processing.commands import (
    ComposeTimelinesCommand,
    ComposeTimelinesUseCase,
    ExtractMicroEventsCommand,
    ExtractMicroEventsUseCase,
)
from codex_sdk_cli.application.processing.executors import (
    MicroEventExtractionExecutor,
    TimelineCompositionExecutor,
)
from codex_sdk_cli.application.processing.ports import (
    MicroEventProcessorPort,
    MicroEventProcessResult,
    TimelineProcessorPort,
    TimelineProcessResult,
)
from codex_sdk_cli.application.transcripts.commands import TRANSCRIPT_CUE_TASK
from codex_sdk_cli.application.work.execution import (
    WorkExecutionEngine,
    WorkExecutorRegistry,
    WorkUnitOfWorkFactory,
)
from codex_sdk_cli.application.work.ports import CreateWorkItem
from codex_sdk_cli.domains.codex.choices import (
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.work.models import WorkExecutionMode, WorkItemStatus
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.work.execution_repositories import WorkVideoTaskRepository
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection


class FakeMicroEventProcessor(MicroEventProcessorPort):
    def __init__(self) -> None:
        self.provenance: tuple[int, int] | None = None

    async def process(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        video_id: int,
        transcript_id: int,
        window_minutes: int,
        overlap_minutes: int,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
        prompt_version_id: int | None,
    ) -> MicroEventProcessResult:
        assert (video_id, transcript_id) == (1, 10)
        assert (window_minutes, overlap_minutes) == (30, 5)
        assert (model, reasoning_effort) == ("gpt-5.5", "medium")
        assert prompt_version_id is None
        self.provenance = (work_item_id, work_attempt_id)
        return MicroEventProcessResult(
            video_id=video_id,
            transcript_id=transcript_id,
            window_count=2,
            micro_event_count=12,
            validation_warning_count=1,
        )


class FakeTimelineProcessor(TimelineProcessorPort):
    def __init__(self) -> None:
        self.source_work_item_id: int | None = None

    async def process(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        video_id: int,
        source_micro_event_work_item_id: int,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
        copy_style: str,
        prompt_version_id: int | None,
    ) -> TimelineProcessResult:
        assert work_item_id > 0 and work_attempt_id > 0
        assert video_id == 1
        assert model == "gpt-5.5"
        assert reasoning_effort == "high"
        assert copy_style == "LIGHT_FANDOM_V1"
        assert prompt_version_id is None
        self.source_work_item_id = source_micro_event_work_item_id
        return TimelineProcessResult(
            video_id=video_id,
            composition_id=20,
            title="Timeline",
            block_count=2,
            episode_count=8,
            topic_cluster_count=2,
            review_flag_count=1,
            validation_warning_count=0,
        )


def test_micro_event_and_timeline_work_lifecycle(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_processing_work(migrated_database_path))


async def _exercise_processing_work(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    try:
        await _insert_video_and_transcript(session_factory)
        cue_work_item_id = await _create_succeeded_cue_work(unit_of_work_factory)
        videos = SqlAlchemyVideoSelection(session_factory)

        micro_command = ExtractMicroEventsUseCase(
            videos=videos,
            unit_of_work_factory=unit_of_work_factory,
        )
        micro_batch = await micro_command.execute(
            ExtractMicroEventsCommand(selection=SelectedVideos((1,)))
        )
        assert micro_batch.created_count == 1
        micro_work_item_id = micro_batch.items[0].work_item_id
        assert micro_work_item_id is not None

        micro_processor = FakeMicroEventProcessor()
        micro_engine = WorkExecutionEngine(
            unit_of_work_factory=unit_of_work_factory,
            registry=WorkExecutorRegistry(
                {"micro_event_extract": lambda: MicroEventExtractionExecutor(micro_processor)}
            ),
            task_types=("micro_event_extract",),
            worker_id="micro-worker:test",
        )
        assert await micro_engine.run_once() is True
        assert micro_processor.provenance is not None

        timeline_command = ComposeTimelinesUseCase(
            videos=videos,
            unit_of_work_factory=unit_of_work_factory,
        )
        timeline_batch = await timeline_command.execute(
            ComposeTimelinesCommand(selection=SelectedVideos((1,)))
        )
        assert timeline_batch.created_count == 1
        timeline_work_item_id = timeline_batch.items[0].work_item_id
        assert timeline_work_item_id is not None

        async with session_factory() as session:
            timeline_task = await WorkVideoTaskRepository(session).get_task(
                timeline_work_item_id
            )
        assert timeline_task is not None
        assert timeline_task.input_json is not None
        assert timeline_task.input_json["inputHash"] == timeline_task.input_hash

        timeline_processor = FakeTimelineProcessor()
        timeline_engine = WorkExecutionEngine(
            unit_of_work_factory=unit_of_work_factory,
            registry=WorkExecutorRegistry(
                {"timeline_compose": lambda: TimelineCompositionExecutor(timeline_processor)}
            ),
            task_types=("timeline_compose",),
            worker_id="timeline-worker:test",
        )
        assert await timeline_engine.run_once() is True
        assert timeline_processor.source_work_item_id == micro_work_item_id

        async with unit_of_work_factory() as unit_of_work:
            cue = await unit_of_work.work_items.get(cue_work_item_id)
            micro = await unit_of_work.work_items.get(micro_work_item_id)
            timeline = await unit_of_work.work_items.get(timeline_work_item_id)
        assert cue is not None and cue.status is WorkItemStatus.SUCCEEDED
        assert micro is not None and micro.status is WorkItemStatus.SUCCEEDED
        assert micro.output_json is not None
        assert micro.output_json["microEventCount"] == 12
        assert timeline is not None and timeline.status is WorkItemStatus.SUCCEEDED
        assert timeline.output_json is not None
        assert timeline.output_json["compositionId"] == 20
    finally:
        await engine.dispose()


async def _create_succeeded_cue_work(
    unit_of_work_factory: WorkUnitOfWorkFactory,
) -> int:
    async with unit_of_work_factory() as unit_of_work:
        item, created = await unit_of_work.work_items.get_or_create(
            CreateWorkItem(
                task_type=TRANSCRIPT_CUE_TASK,
                subject_type="video",
                subject_id=1,
                external_key="abcdefghijk",
                task_version="v2",
                input_hash="a" * 64,
                idempotency_key="cue:video:1:test",
                execution_mode=WorkExecutionMode.INLINE,
                timeout_seconds=600,
                input_json={"videoId": 1, "transcriptId": 10},
            )
        )
        assert created is True
        running = await unit_of_work.work_items.start_inline(
            work_item_id=item.id,
            worker_id="test",
            now=item.created_at,
            lease_expires_at=item.created_at + timedelta(minutes=10),
        )
        assert running is not None
        attempt = await unit_of_work.work_attempts.create(
            work_item_id=item.id,
            worker_id="test",
        )
        await unit_of_work.work_attempts.mark_succeeded(
            attempt_id=attempt.id,
            now=item.created_at,
            output_json={"transcriptId": 10, "cueCount": 2},
        )
        item = await unit_of_work.work_items.mark_succeeded(
            work_item_id=item.id,
            now=item.created_at,
            output_json={"transcriptId": 10, "cueCount": 2},
            output_transcript_id=10,
        )
        await unit_of_work.commit()
    return item.id


async def _insert_video_and_transcript(session_factory) -> None:
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
                "published_at, is_embeddable) VALUES "
                "(1, 1, 'abcdefghijk', 'Test', '', "
                "'2026-07-01T00:00:00+00:00', 1)"
            )
        )
        await session.execute(
            text(
                "INSERT INTO youtube_transcripts(id, video_id, language, language_code, "
                "is_generated, requested_languages, preserve_formatting, storage_bucket, "
                "storage_object_name, storage_uri, response_sha256, segment_count, text_length) "
                "VALUES (10, 'abcdefghijk', 'Korean', 'ko', 1, '[\"ko\",\"en\"]', 0, "
                "'transcripts', 'video.json', 's3://transcripts/video.json', "
                "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 2, 8)"
            )
        )
        await session.commit()
