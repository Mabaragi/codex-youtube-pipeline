from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codex_sdk_cli.domains.channels.exceptions import ChannelAlreadyExists
from codex_sdk_cli.domains.channels.ports import ChannelCreate, ChannelUpdate
from codex_sdk_cli.domains.streamers.exceptions import StreamerHasChannels
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository


def test_streamer_and_channel_repositories(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    asyncio.run(_exercise_repositories(database_url))


async def _exercise_repositories(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            streamers = SqlAlchemyStreamerRepository(session)
            channels = SqlAlchemyChannelRepository(session)

            streamer = await streamers.create_streamer(name="Alpha")
            assert streamer.id == 1
            assert streamer.name == "Alpha"
            assert await streamers.list_streamers() == [streamer]
            assert await streamers.get_streamer(streamer.id) == streamer

            updated_streamer = await streamers.update_streamer(streamer.id, name="Beta")
            assert updated_streamer is not None
            assert updated_streamer.name == "Beta"
            assert await streamers.update_streamer(999, name="Missing") is None

            nullable_channel = await channels.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@alpha",
                    name="Alpha",
                    youtube_channel_id=None,
                )
            )
            external_channel = await channels.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@alpha-main",
                    name="Alpha Main",
                    youtube_channel_id="UC123",
                )
            )

            assert nullable_channel.youtube_channel_id is None
            assert await channels.get_channel_by_youtube_channel_id("UC123") == external_channel
            assert [channel.id for channel in await channels.list_channels()] == [
                nullable_channel.id,
                external_channel.id,
            ]
            assert [
                channel.id for channel in await channels.list_channels(streamer_id=streamer.id)
            ] == [
                nullable_channel.id,
                external_channel.id,
            ]

            with pytest.raises(ChannelAlreadyExists):
                await channels.create_channel(
                    ChannelCreate(
                        streamer_id=streamer.id,
                        handle="@alpha-backup",
                        name="Alpha Backup",
                        youtube_channel_id="UC123",
                    )
                )

            with pytest.raises(StreamerHasChannels):
                await streamers.delete_streamer(streamer.id)

            renamed_channel = await channels.update_channel(
                nullable_channel.id,
                ChannelUpdate(
                    handle="@alpha-live",
                    youtube_channel_id="UC456",
                    youtube_channel_id_set=True,
                ),
            )
            assert renamed_channel is not None
            assert renamed_channel.handle == "@alpha-live"
            assert renamed_channel.youtube_channel_id == "UC456"

            with pytest.raises(ChannelAlreadyExists):
                await channels.update_channel(
                    nullable_channel.id,
                    ChannelUpdate(youtube_channel_id="UC123", youtube_channel_id_set=True),
                )

            cleared_channel = await channels.update_channel(
                nullable_channel.id,
                ChannelUpdate(youtube_channel_id=None, youtube_channel_id_set=True),
            )
            assert cleared_channel is not None
            assert cleared_channel.youtube_channel_id is None
            assert await channels.get_channel(nullable_channel.id) == cleared_channel

            assert await channels.delete_channel(nullable_channel.id) is True
            assert await channels.delete_channel(nullable_channel.id) is False
            assert await channels.delete_channel(external_channel.id) is True
            assert await streamers.delete_streamer(streamer.id) is True
            assert await streamers.delete_streamer(streamer.id) is False
    finally:
        await engine.dispose()
