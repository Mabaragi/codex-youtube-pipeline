from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.streamers.exceptions import StreamerHasChannels
from codex_sdk_cli.domains.streamers.ports import ChannelCreate, ChannelUpdate
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository


def test_streamer_repository_crud_and_delete_guard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'repo.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    asyncio.run(_exercise_repository(database_url))


def test_streamer_repository_updates_youtube_channel_id_by_handle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'handles.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    updated_ids = asyncio.run(_save_handle_variants_and_update(database_url))

    assert updated_ids == [1, 2, 3]


async def _exercise_repository(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyStreamerRepository(session)

            streamer = await repository.create_streamer(name="Alpha")
            assert streamer.id == 1
            assert streamer.name == "Alpha"
            assert await repository.list_streamers() == [streamer]
            assert await repository.get_streamer(streamer.id) == streamer

            updated_streamer = await repository.update_streamer(streamer.id, name="Beta")
            assert updated_streamer is not None
            assert updated_streamer.name == "Beta"
            assert await repository.update_streamer(999, name="Missing") is None

            nullable_channel = await repository.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@alpha",
                    name="Alpha",
                    youtube_channel_id=None,
                )
            )
            external_channel = await repository.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@alpha-main",
                    name="Alpha Main",
                    youtube_channel_id="UC123",
                )
            )
            duplicate_external_channel = await repository.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@alpha-backup",
                    name="Alpha Backup",
                    youtube_channel_id="UC123",
                )
            )

            assert nullable_channel.youtube_channel_id is None
            assert (
                external_channel.youtube_channel_id
                == duplicate_external_channel.youtube_channel_id
            )
            assert [
                channel.id
                for channel in await repository.list_channels(streamer_id=streamer.id)
            ] == [
                nullable_channel.id,
                external_channel.id,
                duplicate_external_channel.id,
            ]

            with pytest.raises(StreamerHasChannels):
                await repository.delete_streamer(streamer.id)

            renamed_channel = await repository.update_channel(
                nullable_channel.id,
                ChannelUpdate(
                    handle="@alpha-live",
                    youtube_channel_id="UC123",
                    youtube_channel_id_set=True,
                ),
            )
            assert renamed_channel is not None
            assert renamed_channel.handle == "@alpha-live"
            assert renamed_channel.youtube_channel_id == "UC123"

            cleared_channel = await repository.update_channel(
                nullable_channel.id,
                ChannelUpdate(youtube_channel_id=None, youtube_channel_id_set=True),
            )
            assert cleared_channel is not None
            assert cleared_channel.youtube_channel_id is None
            assert await repository.get_channel(nullable_channel.id) == cleared_channel

            assert await repository.delete_channel(nullable_channel.id) is True
            assert await repository.delete_channel(nullable_channel.id) is False
            assert await repository.delete_channel(external_channel.id) is True
            assert await repository.delete_channel(duplicate_external_channel.id) is True
            assert await repository.delete_streamer(streamer.id) is True
            assert await repository.delete_streamer(streamer.id) is False
    finally:
        await engine.dispose()


async def _save_handle_variants_and_update(database_url: str) -> list[int]:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyStreamerRepository(session)
            streamer = await repository.create_streamer(name="Alpha")
            for handle in ("@Mixed", "mixed", " @MIXED "):
                await repository.create_channel(
                    ChannelCreate(
                        streamer_id=streamer.id,
                        handle=handle,
                        name=handle,
                        youtube_channel_id=None,
                    )
                )
            await repository.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@other",
                    name="Other",
                    youtube_channel_id=None,
                )
            )
            updated = await repository.update_youtube_channel_id_by_handle(
                handle=" Mixed ",
                youtube_channel_id="UC123",
            )
            all_channels = await repository.list_channels()
            assert [channel.youtube_channel_id for channel in all_channels] == [
                "UC123",
                "UC123",
                "UC123",
                None,
            ]
            return [channel.id for channel in updated]
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
