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

    assert set(Base.metadata.tables) == {"channels", "streamers", "youtube_transcripts"}


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
    finally:
        engine.dispose()

    assert {"channels", "streamers", "youtube_transcripts"}.issubset(table_names)
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
    assert {"id", "streamer_id", "handle", "name", "youtube_channel_id"}.issubset(
        channel_columns
    )
    assert any(
        foreign_key["referred_table"] == "streamers"
        and foreign_key["constrained_columns"] == ["streamer_id"]
        for foreign_key in channel_foreign_keys
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
