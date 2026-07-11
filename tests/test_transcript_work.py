from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text

from codex_sdk_cli.application.operations.selection import SelectedVideos
from codex_sdk_cli.application.transcripts.commands import (
    CollectTranscriptsCommand,
    CollectTranscriptsUseCase,
    GenerateTranscriptCuesCommand,
    GenerateTranscriptCuesUseCase,
)
from codex_sdk_cli.application.transcripts.executors import (
    TranscriptCollectExecutor,
    TranscriptCueGenerateExecutor,
)
from codex_sdk_cli.application.transcripts.ports import (
    GeneratedCues,
    StoredTranscript,
    TranscriptCueGeneratorPort,
    TranscriptFetcherPort,
    TranscriptMetadataReaderPort,
)
from codex_sdk_cli.application.work.execution import (
    WorkExecutionEngine,
    WorkExecutorRegistry,
    WorkRunResult,
)
from codex_sdk_cli.domains.work.models import WorkItemStatus
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection
from codex_sdk_cli.settings import CliSettings
from codex_sdk_cli.workers.transcripts import run_transcript_worker
from codex_sdk_cli.workers.work import WorkCooldownPolicy


class FakeTranscriptFetcher(TranscriptFetcherPort):
    def __init__(self, result: StoredTranscript | None) -> None:
        self._result = result

    async def fetch(
        self,
        *,
        youtube_video_id: str,
        languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> StoredTranscript | None:
        assert youtube_video_id == "abcdefghijk"
        assert languages == ("ko", "en")
        assert preserve_formatting is False
        return self._result


class FakeTranscriptMetadataReader(TranscriptMetadataReaderPort):
    async def get(self, transcript_id: int) -> StoredTranscript | None:
        if transcript_id != 10:
            return None
        return _stored_transcript()


class FakeCueGenerator(TranscriptCueGeneratorPort):
    def __init__(self) -> None:
        self.provenance: tuple[int, int] | None = None

    async def generate(
        self,
        *,
        transcript_id: int,
        work_item_id: int,
        work_attempt_id: int,
    ) -> GeneratedCues:
        assert transcript_id == 10
        self.provenance = (work_item_id, work_attempt_id)
        return GeneratedCues(
            transcript_id=transcript_id,
            cue_count=2,
            first_cue_id="tr10-c000001",
            last_cue_id="tr10-c000002",
        )


def test_transcript_and_cue_work_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_transcript_and_cue_work(database_url))


def test_idle_transcript_worker_keeps_storage_dependency_lazy(
    migrated_database_path: Path,
) -> None:
    settings = CliSettings(
        database_url=f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}",
        transcript_minio_endpoint=None,
        transcript_minio_access_key=None,
        transcript_minio_secret_key=None,
        transcript_minio_bucket=None,
    )

    asyncio.run(run_transcript_worker(settings=settings, stop_after_one=True))


def test_transcript_cooldown_skips_no_transcript_outcome() -> None:
    policy = WorkCooldownPolicy(
        delay_seconds=300,
        exempt_outcome_codes=frozenset({"no_transcript"}),
    )

    assert policy.delay_for(
        WorkRunResult(processed=True, succeeded=True, outcome_code="no_transcript")
    ) == 0.0
    assert policy.delay_for(WorkRunResult(processed=True, succeeded=True)) == 300.0
    assert policy.delay_for(WorkRunResult(processed=True, succeeded=False)) == 300.0


async def _exercise_transcript_and_cue_work(database_url: str) -> None:
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    try:
        await _insert_video_and_transcript(session_factory)
        selection = SqlAlchemyVideoSelection(session_factory)
        collect = CollectTranscriptsUseCase(
            videos=selection,
            unit_of_work_factory=unit_of_work_factory,
        )
        command = CollectTranscriptsCommand(selection=SelectedVideos((1,)))

        first = await collect.execute(command)
        duplicate = await collect.execute(command)
        assert first.created_count == 1
        assert first.items[0].reason == "enqueued"
        assert duplicate.reused_count == 1
        transcript_work_item_id = first.items[0].work_item_id
        assert transcript_work_item_id is not None

        no_transcript_engine = WorkExecutionEngine(
            unit_of_work_factory=unit_of_work_factory,
            registry=WorkExecutorRegistry(
                {
                    "transcript_collect": lambda: TranscriptCollectExecutor(
                        FakeTranscriptFetcher(None)
                    )
                }
            ),
            task_types=("transcript_collect",),
            worker_id="transcript-worker:test",
        )
        assert await no_transcript_engine.run_once() is True

        skipped = await collect.execute(command)
        assert skipped.items[0].reason == "no_transcript"
        requeued = await collect.execute(
            CollectTranscriptsCommand(
                selection=SelectedVideos((1,)),
                recheck_no_transcript=True,
            )
        )
        assert requeued.items[0].reason == "requeued"

        success_engine = WorkExecutionEngine(
            unit_of_work_factory=unit_of_work_factory,
            registry=WorkExecutorRegistry(
                {
                    "transcript_collect": lambda: TranscriptCollectExecutor(
                        FakeTranscriptFetcher(_stored_transcript())
                    )
                }
            ),
            task_types=("transcript_collect",),
            worker_id="transcript-worker:test",
        )
        assert await success_engine.run_once() is True

        cues = GenerateTranscriptCuesUseCase(
            videos=selection,
            transcripts=FakeTranscriptMetadataReader(),
            unit_of_work_factory=unit_of_work_factory,
        )
        cue_batch = await cues.execute(
            GenerateTranscriptCuesCommand(selection=SelectedVideos((1,)))
        )
        assert cue_batch.created_count == 1
        cue_work_item_id = cue_batch.items[0].work_item_id
        assert cue_work_item_id is not None

        cue_generator = FakeCueGenerator()
        cue_engine = WorkExecutionEngine(
            unit_of_work_factory=unit_of_work_factory,
            registry=WorkExecutorRegistry(
                {"transcript_cue_generate": lambda: TranscriptCueGenerateExecutor(cue_generator)}
            ),
            task_types=("transcript_cue_generate",),
            worker_id="cue-worker:test",
        )
        assert await cue_engine.run_once() is True
        assert cue_generator.provenance is not None

        async with SqlAlchemyWorkUnitOfWork(session_factory) as unit_of_work:
            transcript_item = await unit_of_work.work_items.get(transcript_work_item_id)
            cue_item = await unit_of_work.work_items.get(cue_work_item_id)
        assert transcript_item is not None
        assert transcript_item.status is WorkItemStatus.SUCCEEDED
        assert transcript_item.outcome_code is None
        assert transcript_item.output_transcript_id == 10
        assert cue_item is not None
        assert cue_item.status is WorkItemStatus.SUCCEEDED
        assert cue_item.output_json is not None
        assert cue_item.output_json["cueCount"] == 2
    finally:
        await engine.dispose()


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
                "(1, 1, 'abcdefghijk', 'Test', '', '2026-07-01T00:00:00+00:00', 1)"
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


def _stored_transcript() -> StoredTranscript:
    return StoredTranscript(
        transcript_id=10,
        youtube_video_id="abcdefghijk",
        language_code="ko",
        response_sha256="a" * 64,
    )
