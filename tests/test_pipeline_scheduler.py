from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from codex_sdk_cli.application.scheduler.ports import (
    SchedulerEvent,
    SchedulerEventRecorderPort,
)
from codex_sdk_cli.application.scheduler.use_cases import (
    PipelineSchedulerConfig,
    RunPipelineSchedulerTickUseCase,
)
from codex_sdk_cli.application.transcripts.commands import CollectTranscriptsUseCase
from codex_sdk_cli.application.videos.executors import VideoCollectExecutor
from codex_sdk_cli.application.videos.ports import (
    VideoCollectionResult,
    VideoCollectorPort,
)
from codex_sdk_cli.application.work.execution import (
    WorkExecutionEngine,
    WorkExecutorRegistry,
)
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.scheduler import SqlAlchemyScheduledChannelReader
from codex_sdk_cli.infra.work.transcript_execution import YouTubeTranscriptMetadataReader
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


class FakeVideoCollector(VideoCollectorPort):
    def __init__(self, *, fail_channel_ids: set[int] | None = None) -> None:
        self.fail_channel_ids = fail_channel_ids or set()
        self.calls: list[int] = []

    async def collect(
        self,
        *,
        channel_id: int,
        work_item_id: int,
        work_attempt_id: int,
        actor_type: str,
    ) -> VideoCollectionResult:
        del work_item_id, work_attempt_id
        assert actor_type == "system"
        self.calls.append(channel_id)
        if channel_id in self.fail_channel_ids:
            raise RuntimeError("video collect failed")
        return VideoCollectionResult(
            created_count=channel_id,
            output_json={"channelId": channel_id, "createdCount": channel_id},
        )


class FakeEvents(SchedulerEventRecorderPort):
    def __init__(self) -> None:
        self.items: list[SchedulerEvent] = []

    async def record(self, event: SchedulerEvent) -> None:
        self.items.append(event)


def test_scheduler_runs_due_video_collect_and_enqueues_transcripts(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_due_channel(database_url))


def test_scheduler_skips_recent_collect_and_rechecks_no_transcript(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_no_transcript_recheck(database_url))


def test_scheduler_continues_after_channel_failure(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_channel_failure(database_url))


def test_pipeline_scheduler_worker_imports() -> None:
    import codex_sdk_cli.workers.pipeline_scheduler as pipeline_scheduler

    assert pipeline_scheduler.run is not None


async def _exercise_due_channel(database_url: str) -> None:
    engine, session_factory = _database(database_url)
    collector = FakeVideoCollector()
    events = FakeEvents()
    try:
        await _insert_catalog(session_factory, channel_ids=(1,))
        scheduler = _scheduler(
            session_factory,
            collector=collector,
            events=events,
            now=NOW,
        )

        result = await scheduler.execute_once()

        assert result.processed_channel_count == 1
        assert result.created_video_count == 1
        assert result.transcript_enqueued_count == 1
        assert collector.calls == [1]
        rows = await _work_rows(session_factory)
        assert rows == [
            ("video_collect", "succeeded", None),
            ("transcript_collect", "pending", None),
        ]

        boundary = _scheduler(
            session_factory,
            collector=collector,
            events=events,
            now=NOW + timedelta(hours=2),
        )
        boundary_result = await boundary.execute_once()
        assert boundary_result.processed_channel_count == 1
        assert collector.calls == [1, 1]
        assert "pipeline_scheduler.channel_processed" in {
            event.event_type for event in events.items
        }
    finally:
        await engine.dispose()


async def _exercise_no_transcript_recheck(database_url: str) -> None:
    engine, session_factory = _database(database_url)
    collector = FakeVideoCollector()
    events = FakeEvents()
    try:
        await _insert_catalog(session_factory, channel_ids=(1,))
        initial = _scheduler(
            session_factory,
            collector=collector,
            events=events,
            now=NOW - timedelta(hours=1),
        )
        await initial.execute_once()
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE work_items SET status = 'succeeded', "
                    "outcome_code = 'no_transcript', "
                    "completed_at = :completed_at WHERE task_type = 'transcript_collect'"
                ),
                {"completed_at": NOW - timedelta(days=8)},
            )
            await session.commit()

        scheduler = _scheduler(
            session_factory,
            collector=collector,
            events=events,
            now=NOW,
        )
        result = await scheduler.execute_once()

        assert result.skipped_channel_count == 1
        assert result.no_transcript_recheck_count == 1
        assert collector.calls == [1]
        rows = await _work_rows(session_factory)
        assert rows == [
            ("video_collect", "succeeded", None),
            ("transcript_collect", "pending", None),
        ]
    finally:
        await engine.dispose()


async def _exercise_channel_failure(database_url: str) -> None:
    engine, session_factory = _database(database_url)
    collector = FakeVideoCollector(fail_channel_ids={1})
    events = FakeEvents()
    try:
        await _insert_catalog(session_factory, channel_ids=(1, 2))
        scheduler = _scheduler(
            session_factory,
            collector=collector,
            events=events,
            now=NOW,
        )

        result = await scheduler.execute_once()

        assert result.failed_channel_count == 1
        assert result.processed_channel_count == 1
        assert collector.calls == [1, 2]
        assert [item.status for item in result.channels] == ["failed", "processed"]
    finally:
        await engine.dispose()


def _database(database_url: str):
    engine = create_database_engine(database_url)
    return engine, create_session_factory(engine)


def _scheduler(
    session_factory,
    *,
    collector: FakeVideoCollector,
    events: FakeEvents,
    now: datetime,
) -> RunPipelineSchedulerTickUseCase:
    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    runner = WorkExecutionEngine(
        unit_of_work_factory=unit_of_work_factory,
        registry=WorkExecutorRegistry(
            {"video_collect": lambda: VideoCollectExecutor(collector)}
        ),
        task_types=("video_collect",),
        worker_id="scheduler:test",
        now=lambda: now,
    )
    return RunPipelineSchedulerTickUseCase(
        channels=SqlAlchemyScheduledChannelReader(session_factory),
        collect_transcripts=CollectTranscriptsUseCase(
            videos=SqlAlchemyVideoSelection(session_factory),
            transcripts=YouTubeTranscriptMetadataReader(session_factory),
            unit_of_work_factory=unit_of_work_factory,
            now=lambda: now,
        ),
        unit_of_work_factory=unit_of_work_factory,
        inline_runner=runner,
        events=events,
        config=PipelineSchedulerConfig(
            channel_interval_seconds=7200,
            transcript_limit=5,
            no_transcript_recheck_interval_seconds=604800,
            no_transcript_limit=2,
        ),
        now=lambda: now,
    )


async def _insert_catalog(session_factory, *, channel_ids: tuple[int, ...]) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO streamers(id, name, publish_profile_id) "
                "VALUES (1, 'Nagi', 1)"
            )
        )
        for channel_id in channel_ids:
            await session.execute(
                text(
                    "INSERT INTO channels(id, streamer_id, handle, name, "
                    "youtube_channel_id, uploads_playlist_id) VALUES "
                    "(:id, 1, :handle, :name, :youtube_channel_id, :playlist_id)"
                ),
                {
                    "id": channel_id,
                    "handle": f"@channel-{channel_id}",
                    "name": f"Channel {channel_id}",
                    "youtube_channel_id": f"UC-{channel_id}",
                    "playlist_id": f"UU-{channel_id}",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO videos(id, channel_id, youtube_video_id, title, "
                    "description, published_at, is_embeddable) VALUES "
                    "(:id, :channel_id, :youtube_video_id, :title, '', :published_at, 1)"
                ),
                {
                    "id": channel_id,
                    "channel_id": channel_id,
                    "youtube_video_id": f"video-{channel_id}",
                    "title": f"Video {channel_id}",
                    "published_at": NOW,
                },
            )
        await session.commit()


async def _work_rows(session_factory) -> list[tuple[str, str, str | None]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT task_type, status, outcome_code FROM work_items "
                    "ORDER BY id"
                )
            )
        ).all()
    return [(row.task_type, row.status, row.outcome_code) for row in rows]
