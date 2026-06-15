from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import select

from alembic import command
from codex_sdk_cli.domains.youtube.ports import YouTubeTranscriptRecord
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.youtube.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
    YouTubeTranscriptRecordModel,
)


def test_repository_inserts_and_updates_transcript_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'repo.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    row = asyncio.run(_save_twice_and_fetch(database_url))

    assert row.video_id == "dQw4w9WgXcQ"
    assert row.language == "Korean"
    assert row.language_code == "ko"
    assert row.is_generated is True
    assert row.requested_languages == ["ko", "en"]
    assert row.preserve_formatting is False
    assert row.storage_bucket == "raw"
    assert row.storage_object_name == "youtube/transcripts/object.json"
    assert row.storage_uri == "s3://raw/youtube/transcripts/object.json"
    assert row.response_sha256 == "b" * 64
    assert row.segment_count == 3
    assert row.text_length == 22


async def _save_twice_and_fetch(database_url: str) -> YouTubeTranscriptRecordModel:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyYouTubeTranscriptRepository(session)
            await repository.save_transcript_record(_record(language="English", sha="a" * 64))
            await repository.save_transcript_record(_record(language="Korean", sha="b" * 64))

        async with session_factory() as session:
            row = await session.scalar(select(YouTubeTranscriptRecordModel))
            assert row is not None
            return row
    finally:
        await engine.dispose()


def _record(*, language: str, sha: str) -> YouTubeTranscriptRecord:
    return YouTubeTranscriptRecord(
        video_id="dQw4w9WgXcQ",
        language=language,
        language_code="ko",
        is_generated=True,
        requested_languages=("ko", "en"),
        preserve_formatting=False,
        storage_bucket="raw",
        storage_object_name="youtube/transcripts/object.json",
        storage_uri="s3://raw/youtube/transcripts/object.json",
        response_sha256=sha,
        segment_count=3,
        text_length=22,
    )


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
