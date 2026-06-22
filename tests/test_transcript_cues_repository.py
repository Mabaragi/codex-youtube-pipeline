from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobCreate
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueCreate
from codex_sdk_cli.domains.youtube_transcripts.ports import YouTubeTranscriptRecord
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.transcript_cues.repository import SqlAlchemyTranscriptCueRepository
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)


def test_transcript_cue_repository_replaces_and_lists_cues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'transcript-cues.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    asyncio.run(_exercise_repository(database_url))


async def _exercise_repository(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            transcripts = SqlAlchemyYouTubeTranscriptRepository(session)
            pipeline_jobs = SqlAlchemyPipelineJobRepository(session)
            cues = SqlAlchemyTranscriptCueRepository(session)

            transcript = await transcripts.save_transcript_record(
                YouTubeTranscriptRecord(
                    video_id="abc123DEF45",
                    language="Korean",
                    language_code="ko",
                    is_generated=True,
                    requested_languages=("ko", "en"),
                    preserve_formatting=False,
                    storage_bucket="raw",
                    storage_object_name="youtube/transcripts/abc123DEF45-hash.json",
                    storage_uri="s3://raw/youtube/transcripts/abc123DEF45-hash.json",
                    response_sha256="a" * 64,
                    segment_count=2,
                    text_length=11,
                )
            )
            job = await pipeline_jobs.create_job(
                PipelineJobCreate(
                    step="transcript_cue_generate",
                    status="running",
                    subject_type="transcript",
                    subject_id=transcript.id,
                    external_key=transcript.video_id,
                    input_json={"transcriptId": transcript.id},
                    input_hash="b" * 64,
                )
            )
            attempt = await pipeline_jobs.create_attempt(job_id=job.id)

            first = await cues.replace_cues(
                transcript.id,
                [
                    _cue(transcript.id, 2, "world", job.id, attempt.id),
                    _cue(transcript.id, 1, "hello", job.id, attempt.id),
                ],
            )
            second = await cues.replace_cues(
                transcript.id,
                [_cue(transcript.id, 1, "updated", job.id, attempt.id)],
            )
            listed = await cues.list_cues(transcript.id)
            summary = await cues.summarize_cues(transcript.id)

            assert [record.cue_id for record in first] == [
                f"tr{transcript.id}-c000001",
                f"tr{transcript.id}-c000002",
            ]
            assert [record.text for record in second] == ["updated"]
            assert [record.text for record in listed] == ["updated"]
            assert summary.cue_count == 1
            assert summary.first_cue_id == f"tr{transcript.id}-c000001"
            assert summary.last_cue_id == f"tr{transcript.id}-c000001"
            assert summary.source_job_id == job.id
    finally:
        await engine.dispose()


def _cue(
    transcript_id: int,
    cue_index: int,
    text: str,
    job_id: int,
    attempt_id: int,
) -> TranscriptCueCreate:
    return TranscriptCueCreate(
        transcript_id=transcript_id,
        cue_id=f"tr{transcript_id}-c{cue_index:06d}",
        cue_index=cue_index,
        text=text,
        start_ms=(cue_index - 1) * 1000,
        end_ms=cue_index * 1000,
        duration_ms=1000,
        source_segment_index=cue_index - 1,
        source_job_id=job_id,
        source_job_attempt_id=attempt_id,
    )


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
