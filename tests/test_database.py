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
        "asr_correction_candidates",
        "channels",
        "codex_run_usages",
        "external_api_calls",
        "micro_event_candidates",
        "micro_event_extraction_windows",
        "operation_events",
        "pipeline_job_attempts",
        "pipeline_jobs",
        "streamers",
        "transcript_cues",
        "video_tasks",
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
    monkeypatch.setenv("CODEX_CLI_TRANSCRIPT_COLLECT_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("CODEX_CLI_TRANSCRIPT_COLLECT_CONCURRENCY_LIMIT", "2")
    monkeypatch.setenv("CODEX_CLI_TRANSCRIPT_COLLECT_DELAY_SECONDS", "30")
    monkeypatch.setenv("CODEX_CLI_MICRO_EVENT_EXTRACT_TIMEOUT_SECONDS", "1200")
    monkeypatch.setenv("CODEX_CLI_MICRO_EVENT_EXTRACT_CONCURRENCY_LIMIT", "3")

    settings = CliSettings()

    assert settings.youtube_data_api_key_value() == "AIza-test"
    assert settings.youtube_data_timeout_seconds == 3.5
    assert settings.transcript_collect_timeout_seconds == 300
    assert settings.transcript_collect_concurrency_limit == 2
    assert settings.transcript_collect_delay_seconds == 30
    assert settings.micro_event_extract_timeout_seconds == 1200
    assert settings.micro_event_extract_concurrency_limit == 3


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
        codex_usage_columns = {
            column["name"] for column in inspector.get_columns("codex_run_usages")
        }
        codex_usage_foreign_keys = inspector.get_foreign_keys("codex_run_usages")
        codex_usage_indexes = {
            index["name"]: index["column_names"]
            for index in inspector.get_indexes("codex_run_usages")
        }
        pipeline_job_columns = {
            column["name"] for column in inspector.get_columns("pipeline_jobs")
        }
        pipeline_job_indexes = {
            index["name"]: index for index in inspector.get_indexes("pipeline_jobs")
        }
        pipeline_job_attempt_columns = {
            column["name"] for column in inspector.get_columns("pipeline_job_attempts")
        }
        pipeline_job_attempt_foreign_keys = inspector.get_foreign_keys("pipeline_job_attempts")
        video_columns = {column["name"] for column in inspector.get_columns("videos")}
        video_foreign_keys = inspector.get_foreign_keys("videos")
        video_unique_constraints = inspector.get_unique_constraints("videos")
        video_task_columns = {
            column["name"] for column in inspector.get_columns("video_tasks")
        }
        video_task_foreign_keys = inspector.get_foreign_keys("video_tasks")
        video_task_unique_constraints = inspector.get_unique_constraints("video_tasks")
        operation_event_columns = {
            column["name"] for column in inspector.get_columns("operation_events")
        }
        operation_event_foreign_keys = inspector.get_foreign_keys("operation_events")
        operation_event_indexes = {
            index["name"]: index["column_names"]
            for index in inspector.get_indexes("operation_events")
        }
        transcript_cue_columns = {
            column["name"] for column in inspector.get_columns("transcript_cues")
        }
        transcript_cue_foreign_keys = inspector.get_foreign_keys("transcript_cues")
        transcript_cue_unique_constraints = inspector.get_unique_constraints(
            "transcript_cues"
        )
        transcript_cue_indexes = {
            index["name"]: index["column_names"]
            for index in inspector.get_indexes("transcript_cues")
        }
    finally:
        engine.dispose()

    assert {
        "asr_correction_candidates",
        "channels",
        "codex_run_usages",
        "external_api_calls",
        "micro_event_candidates",
        "micro_event_extraction_windows",
        "operation_events",
        "pipeline_job_attempts",
        "pipeline_jobs",
        "streamers",
        "transcript_cues",
        "video_tasks",
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
    assert pipeline_job_indexes["uq_pipeline_jobs_running_transcript_collect_batch"][
        "column_names"
    ] == ["status"]
    assert pipeline_job_indexes["uq_pipeline_jobs_running_transcript_collect_batch"][
        "unique"
    ]
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
        unique_constraint["column_names"] == ["uploads_playlist_id"]
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
        "source",
        "operation",
        "model",
        "status",
        "thread_id",
        "turn_id",
        "usage_json",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
        "duration_ms",
        "error_type",
        "error_message",
        "video_id",
        "video_task_id",
        "job_id",
        "job_attempt_id",
        "transcript_id",
        "window_index",
        "created_at",
    }.issubset(codex_usage_columns)
    assert any(
        foreign_key["referred_table"] == "videos"
        and foreign_key["constrained_columns"] == ["video_id"]
        for foreign_key in codex_usage_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "video_tasks"
        and foreign_key["constrained_columns"] == ["video_task_id"]
        for foreign_key in codex_usage_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_jobs"
        and foreign_key["constrained_columns"] == ["job_id"]
        for foreign_key in codex_usage_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_job_attempts"
        and foreign_key["constrained_columns"] == ["job_attempt_id"]
        for foreign_key in codex_usage_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "youtube_transcripts"
        and foreign_key["constrained_columns"] == ["transcript_id"]
        for foreign_key in codex_usage_foreign_keys
    )
    assert codex_usage_indexes["ix_codex_run_usages_source"] == ["source"]
    assert codex_usage_indexes["ix_codex_run_usages_video_task_id"] == [
        "video_task_id"
    ]
    assert {
        "id",
        "channel_id",
        "youtube_video_id",
        "title",
        "description",
        "published_at",
        "duration",
        "thumbnail_url",
        "source_listing_api_call_id",
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
        and foreign_key["constrained_columns"] == ["source_listing_api_call_id"]
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
    assert {
        "id",
        "video_id",
        "task_name",
        "task_version",
        "input_hash",
        "status",
        "worker_id",
        "timeout_seconds",
        "job_id",
        "job_attempt_id",
        "output_transcript_id",
        "output_json",
        "error_type",
        "error_message",
        "started_at",
        "completed_at",
    }.issubset(video_task_columns)
    assert any(
        unique_constraint["column_names"]
        == ["video_id", "task_name", "task_version", "input_hash"]
        for unique_constraint in video_task_unique_constraints
    )
    assert any(
        foreign_key["referred_table"] == "videos"
        and foreign_key["constrained_columns"] == ["video_id"]
        for foreign_key in video_task_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_jobs"
        and foreign_key["constrained_columns"] == ["job_id"]
        for foreign_key in video_task_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_job_attempts"
        and foreign_key["constrained_columns"] == ["job_attempt_id"]
        for foreign_key in video_task_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "youtube_transcripts"
        and foreign_key["constrained_columns"] == ["output_transcript_id"]
        for foreign_key in video_task_foreign_keys
    )
    assert {
        "id",
        "occurred_at",
        "event_type",
        "severity",
        "message",
        "actor_type",
        "source",
        "metadata_json",
        "job_id",
        "job_attempt_id",
        "video_task_id",
        "channel_id",
        "video_id",
        "external_api_call_id",
        "subject_type",
        "subject_id",
        "external_key",
        "correlation_id",
        "error_type",
        "error_message",
    }.issubset(operation_event_columns)
    assert any(
        foreign_key["referred_table"] == "pipeline_jobs"
        and foreign_key["constrained_columns"] == ["job_id"]
        for foreign_key in operation_event_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_job_attempts"
        and foreign_key["constrained_columns"] == ["job_attempt_id"]
        for foreign_key in operation_event_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "video_tasks"
        and foreign_key["constrained_columns"] == ["video_task_id"]
        for foreign_key in operation_event_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "channels"
        and foreign_key["constrained_columns"] == ["channel_id"]
        for foreign_key in operation_event_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "videos"
        and foreign_key["constrained_columns"] == ["video_id"]
        for foreign_key in operation_event_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "external_api_calls"
        and foreign_key["constrained_columns"] == ["external_api_call_id"]
        for foreign_key in operation_event_foreign_keys
    )
    assert operation_event_indexes["ix_operation_events_event_type"] == ["event_type"]
    assert operation_event_indexes["ix_operation_events_severity"] == ["severity"]
    assert operation_event_indexes["ix_operation_events_job_id"] == ["job_id"]
    assert operation_event_indexes["ix_operation_events_video_task_id"] == ["video_task_id"]
    assert operation_event_indexes["ix_operation_events_subject"] == [
        "subject_type",
        "subject_id",
    ]
    assert operation_event_indexes["ix_operation_events_correlation_id"] == [
        "correlation_id"
    ]
    assert {
        "id",
        "transcript_id",
        "cue_id",
        "cue_index",
        "text",
        "start_ms",
        "end_ms",
        "duration_ms",
        "source_segment_index",
        "source_job_id",
        "source_job_attempt_id",
    }.issubset(transcript_cue_columns)
    assert any(
        foreign_key["referred_table"] == "youtube_transcripts"
        and foreign_key["constrained_columns"] == ["transcript_id"]
        for foreign_key in transcript_cue_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_jobs"
        and foreign_key["constrained_columns"] == ["source_job_id"]
        for foreign_key in transcript_cue_foreign_keys
    )
    assert any(
        foreign_key["referred_table"] == "pipeline_job_attempts"
        and foreign_key["constrained_columns"] == ["source_job_attempt_id"]
        for foreign_key in transcript_cue_foreign_keys
    )
    assert any(
        unique_constraint["column_names"] == ["cue_id"]
        for unique_constraint in transcript_cue_unique_constraints
    )
    assert any(
        unique_constraint["column_names"] == ["transcript_id", "cue_index"]
        for unique_constraint in transcript_cue_unique_constraints
    )
    assert transcript_cue_indexes["ix_transcript_cues_transcript_index"] == [
        "transcript_id",
        "cue_index",
    ]
    assert transcript_cue_indexes["ix_transcript_cues_source_job_id"] == [
        "source_job_id"
    ]


def test_alembic_migrates_transcript_not_found_tasks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-transcript-not-found.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv(
        "CODEX_CLI_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    config = _alembic_config()
    command.upgrade(config, "20260619_0011")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO streamers (id, name) VALUES (1, 'Creator')"))
            connection.execute(
                text(
                    "INSERT INTO channels "
                    "(id, streamer_id, handle, name, youtube_channel_id, uploads_playlist_id) "
                    "VALUES (1, 1, '@creator', 'Creator', 'UC-test', 'UU-test')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO videos "
                    "(id, channel_id, youtube_video_id, title, description, published_at) "
                    "VALUES (1, 1, 'abc123DEF45', 'Video', '', "
                    "'2026-06-16 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO video_tasks "
                    "(id, video_id, task_name, task_version, input_hash, status, "
                    "timeout_seconds, error_type, error_message) "
                    "VALUES (1, 1, 'transcript_collect', 'v1', :input_hash, 'failed', "
                    "600, 'YouTubeTranscriptNotFound', 'No transcript.')"
                ),
                {"input_hash": "a" * 64},
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            status = connection.scalar(text("SELECT status FROM video_tasks WHERE id = 1"))
    finally:
        engine.dispose()

    assert status == "no_transcript"


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
