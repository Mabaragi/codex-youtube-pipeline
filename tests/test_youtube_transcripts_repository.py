from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select

from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    YouTubeTranscriptPersistenceError,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataFilters,
    YouTubeTranscriptRecord,
)
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
    YouTubeTranscriptRecordModel,
)


def test_repository_inserts_and_updates_transcript_metadata(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

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
    assert row.notes is None


def test_repository_lists_filters_updates_notes_and_deletes_metadata(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    result = asyncio.run(_exercise_metadata_crud(database_url))

    assert result["all_ids"] == [1, 2, 3]
    assert result["filtered_ids"] == [1, 3]
    assert result["paginated_ids"] == [2]
    assert result["got_storage_uri"] == "s3://raw/youtube/transcripts/object-2.json"
    assert result["updated_notes"] == "reviewed"
    assert result["cleared_notes"] is None
    assert result["existing_request_id"] == 3
    assert result["reversed_request"] is None
    assert result["deleted"] is True
    assert result["missing_after_delete"] is None
    assert result["delete_missing"] is False


def test_repository_converts_sqlalchemy_errors_to_domain_error(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'missing-schema.db').as_posix()}"

    with pytest.raises(YouTubeTranscriptPersistenceError):
        asyncio.run(_list_without_schema(database_url))


async def _save_twice_and_fetch(database_url: str) -> YouTubeTranscriptRecordModel:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyYouTubeTranscriptRepository(session)
            await repository.save_transcript_record(
                _record(language="English", object_name="object.json", sha="a" * 64)
            )
            await repository.save_transcript_record(
                _record(language="Korean", object_name="object.json", sha="b" * 64)
            )

        async with session_factory() as session:
            row = await session.scalar(select(YouTubeTranscriptRecordModel))
            assert row is not None
            return row
    finally:
        await engine.dispose()


async def _exercise_metadata_crud(database_url: str) -> dict[str, object]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyYouTubeTranscriptRepository(session)
            await repository.save_transcript_record(
                _record(video_id="dQw4w9WgXcQ", language="Korean", object_name="object-1.json")
            )
            await repository.save_transcript_record(
                _record(video_id="abc123DEF45", language="English", object_name="object-2.json")
            )
            await repository.save_transcript_record(
                _record(video_id="dQw4w9WgXcQ", language="Korean", object_name="object-3.json")
            )

            all_records = await repository.list_transcript_metadata(
                YouTubeTranscriptMetadataFilters()
            )
            filtered_records = await repository.list_transcript_metadata(
                YouTubeTranscriptMetadataFilters(video_id="dQw4w9WgXcQ", language_code="ko")
            )
            paginated_records = await repository.list_transcript_metadata(
                YouTubeTranscriptMetadataFilters(limit=1, offset=1)
            )
            got = await repository.get_transcript_metadata(2)
            updated = await repository.update_transcript_notes(1, "reviewed")
            cleared = await repository.update_transcript_notes(1, None)
            existing_request = await repository.find_transcript_metadata_for_request(
                video_id="dQw4w9WgXcQ",
                requested_languages=("ko", "en"),
                preserve_formatting=False,
            )
            reversed_request = await repository.find_transcript_metadata_for_request(
                video_id="dQw4w9WgXcQ",
                requested_languages=("en", "ko"),
                preserve_formatting=False,
            )
            deleted = await repository.delete_transcript_metadata(2)
            missing_after_delete = await repository.get_transcript_metadata(2)
            delete_missing = await repository.delete_transcript_metadata(999)

        assert got is not None
        assert updated is not None
        assert cleared is not None
        assert existing_request is not None
        return {
            "all_ids": [record.id for record in all_records],
            "filtered_ids": [record.id for record in filtered_records],
            "paginated_ids": [record.id for record in paginated_records],
            "got_storage_uri": got.storage_uri,
            "updated_notes": updated.notes,
            "cleared_notes": cleared.notes,
            "existing_request_id": existing_request.id,
            "reversed_request": reversed_request,
            "deleted": deleted,
            "missing_after_delete": missing_after_delete,
            "delete_missing": delete_missing,
        }
    finally:
        await engine.dispose()


async def _list_without_schema(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyYouTubeTranscriptRepository(session)
            await repository.list_transcript_metadata(YouTubeTranscriptMetadataFilters())
    finally:
        await engine.dispose()


def _record(
    *,
    language: str,
    object_name: str,
    video_id: str = "dQw4w9WgXcQ",
    sha: str = "a" * 64,
) -> YouTubeTranscriptRecord:
    language_code = "ko" if language == "Korean" else "en"
    return YouTubeTranscriptRecord(
        video_id=video_id,
        language=language,
        language_code=language_code,
        is_generated=True,
        requested_languages=(language_code, "en"),
        preserve_formatting=False,
        storage_bucket="raw",
        storage_object_name=f"youtube/transcripts/{object_name}",
        storage_uri=f"s3://raw/youtube/transcripts/{object_name}",
        response_sha256=sha,
        segment_count=3,
        text_length=22,
    )
