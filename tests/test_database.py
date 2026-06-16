from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.settings import DEFAULT_DATABASE_URL, CliSettings


def test_database_base_registers_app_tables() -> None:
    import codex_sdk_cli.infra.database.models  # noqa: F401

    assert set(Base.metadata.tables) == {
        "channels",
        "external_api_calls",
        "pipeline_job_attempts",
        "pipeline_jobs",
        "streamers",
        "videos",
        "youtube_transcripts",
    }


def test_database_settings_use_default_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODEX_CLI_DATABASE_URL", raising=False)
    monkeypatch.delenv("CODEX_CLI_DATABASE_ECHO", raising=False)

    settings = CliSettings()

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.database_echo is False


def test_database_settings_allow_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'override.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    monkeypatch.setenv("CODEX_CLI_DATABASE_ECHO", "true")

    settings = CliSettings()

    assert settings.database_url == database_url
    assert settings.database_echo is True


def test_youtube_data_settings_handle_blank_and_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_CLI_YOUTUBE_DATA_API_KEY", " ")

    blank_settings = CliSettings()

    assert blank_settings.youtube_data_api_key is None
    assert blank_settings.youtube_data_api_key_value() is None

    monkeypatch.setenv("CODEX_CLI_YOUTUBE_DATA_API_KEY", "AIza-test")
    monkeypatch.setenv("CODEX_CLI_YOUTUBE_DATA_TIMEOUT_SECONDS", "3.5")

    settings = CliSettings()

    assert settings.youtube_data_api_key_value() == "AIza-test"
    assert settings.youtube_data_timeout_seconds == 3.5


def test_blank_database_url_uses_default() -> None:
    settings = CliSettings(database_url=" ")

    assert settings.database_url == DEFAULT_DATABASE_URL


def test_async_sqlite_session_executes_without_creating_app_tables(tmp_path: Path) -> None:
    database_file = tmp_path / "nested" / "app.db"
    database_url = f"sqlite+aiosqlite:///{database_file.as_posix()}"

    scalar, table_names = asyncio.run(_query_database(database_url))

    assert scalar == 1
    assert table_names == []
    assert database_file.exists()


def test_alembic_upgrade_creates_app_tables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_file = tmp_path / "migrated.db"
    monkeypatch.setenv(
        "CODEX_CLI_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_file.as_posix()}",
    )

    command.upgrade(_alembic_config(), "head")

    engine = create_engine(f"sqlite:///{database_file.as_posix()}")
    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        transcript_columns = {
            column["name"] for column in inspector.get_columns("youtube_transcripts")
        }
        streamer_columns = {column["name"] for column in inspector.get_columns("streamers")}
        channel_columns = {column["name"] for column in inspector.get_columns("channels")}
        channel_foreign_keys = inspector.get_foreign_keys("channels")
        channel_unique_constraints = inspector.get_unique_constraints("channels")
        external_api_call_columns = {
            column["name"] for column in inspector.get_columns("external_api_calls")
        }
        external_api_call_foreign_keys = inspector.get_foreign_keys("external_api_calls")
        pipeline_job_columns = {
            column["name"] for column in inspector.get_columns("pipeline_jobs")
        }
        pipeline_job_attempt_columns = {
            column["name"] for column in inspector.get_columns("pipeline_job_attempts")
        }
        pipeline_job_attempt_foreign_keys = inspector.get_foreign_keys("pipeline_job_attempts")
        video_columns = {column["name"] for column in inspector.get_columns("videos")}
        video_foreign_keys = inspector.get_foreign_keys("videos")
        video_unique_constraints = inspector.get_unique_constraints("videos")
    finally:
        engine.dispose()

    assert {
        "channels",
        "external_api_calls",
        "pipeline_job_attempts",
        "pipeline_jobs",
        "streamers",
        "videos",
        "youtube_transcripts",
    }.issubset(table_names)
    assert {
        "video_id",
        "language_code",
        "storage_bucket",
        "storage_object_name",
        "storage_uri",
        "response_sha256",
        "segment_count",
        "text_length",
        "notes",
    }.issubset(transcript_columns)
    assert {"id", "name"}.issubset(streamer_columns)
    assert {
        "id",
        "streamer_id",
        "handle",
        "name",
        "youtube_channel_id",
        "source_api_call_id",
        "source_job_id",
    }.issubset(channel_columns)
    assert {
        "provider",
        "operation",
        "request_params",
        "pipeline_job_attempt_id",
        "response_storage_object_name",
        "response_sha256",
        "validation_status",
    }.issubset(external_api_call_columns)
    assert {
        "id",
        "step",
        "status",
        "subject_type",
        "subject_id",
        "external_key",
        "input_json",
        "input_hash",
        "parent_job_id",
        "created_at",
        "updated_at",
        "completed_at",
    }.issubset(pipeline_job_columns)
    assert {
        "id",
        "job_id",
        "attempt_no",
        "status",
        "started_at",
        "finished_at",
        "worker_id",
        "error_type",
        "error_message",
        "output_json",
    }.issubset(pipeline_job_attempt_columns)
    assert any(
        foreign_key["referred_table"] == "streamers"
        and foreign_key["constrained_columns"] == ["streamer_id"]
        for foreign_key in channel_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "external_api_calls"
        and foreign_key["constrained_columns"] == ["source_api_call_id"]
        for foreign_key in channel_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_jobs"
        and foreign_key["constrained_columns"] == ["source_job_id"]
        for foreign_key in channel_foreign_keys
    )
    assert any(
        unique_constraint["column_names"] == ["youtube_channel_id"]
        for unique_constraint in channel_unique_constraints
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_job_attempts"
        and foreign_key["constrained_columns"] == ["pipeline_job_attempt_id"]
        for foreign_key in external_api_call_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_jobs"
        and foreign_key["constrained_columns"] == ["job_id"]
        for foreign_key in pipeline_job_attempt_foreign_keys
    )
    assert {
        "id",
        "channel_id",
        "youtube_video_id",
        "title",
        "description",
        "published_at",
        "duration",
        "privacy_status",
        "upload_status",
        "live_broadcast_content",
        "view_count",
        "like_count",
        "comment_count",
        "thumbnail_url",
        "source_search_api_call_id",
        "source_details_api_call_id",
        "source_job_id",
    }.issubset(video_columns)
    assert any(
        unique_constraint["column_names"] == ["youtube_video_id"]
        for unique_constraint in video_unique_constraints
    )
    assert any(
        foreign_key["referred_table"] == "channels"
        and foreign_key["constrained_columns"] == ["channel_id"]
        for foreign_key in video_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "external_api_calls"
        and foreign_key["constrained_columns"] == ["source_search_api_call_id"]
        for foreign_key in video_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "external_api_calls"
        and foreign_key["constrained_columns"] == ["source_details_api_call_id"]
        for foreign_key in video_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_jobs"
        and foreign_key["constrained_columns"] == ["source_job_id"]
        for foreign_key in video_foreign_keys
    )


async def _query_database(database_url: str) -> tuple[int | None, list[str]]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            scalar = await session.scalar(text("select 1"))

        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
    finally:
        await engine.dispose()

    return scalar, table_names


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
