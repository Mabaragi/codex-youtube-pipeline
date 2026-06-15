from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import get_streamer_repository
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.streamers.exceptions import (
    StreamerHasChannels,
    StreamerPersistenceError,
)
from codex_sdk_cli.domains.streamers.ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelUpdate,
    StreamerRecord,
    StreamerRepositoryPort,
)


class FakeStreamerRepository(StreamerRepositoryPort):
    def __init__(self) -> None:
        self.streamers: dict[int, StreamerRecord] = {}
        self.channels: dict[int, ChannelRecord] = {}
        self.next_streamer_id = 1
        self.next_channel_id = 1
        self.fail_persistence = False

    async def create_streamer(self, *, name: str) -> StreamerRecord:
        self._raise_if_failed()
        record = StreamerRecord(id=self.next_streamer_id, name=name)
        self.streamers[record.id] = record
        self.next_streamer_id += 1
        return record

    async def list_streamers(self) -> list[StreamerRecord]:
        self._raise_if_failed()
        return list(self.streamers.values())

    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        self._raise_if_failed()
        return self.streamers.get(streamer_id)

    async def update_streamer(self, streamer_id: int, *, name: str) -> StreamerRecord | None:
        self._raise_if_failed()
        record = self.streamers.get(streamer_id)
        if record is None:
            return None
        updated = replace(record, name=name)
        self.streamers[streamer_id] = updated
        return updated

    async def delete_streamer(self, streamer_id: int) -> bool:
        self._raise_if_failed()
        if streamer_id not in self.streamers:
            return False
        if any(channel.streamer_id == streamer_id for channel in self.channels.values()):
            raise StreamerHasChannels("Streamer has channels and cannot be deleted.")
        del self.streamers[streamer_id]
        return True

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        self._raise_if_failed()
        record = ChannelRecord(
            id=self.next_channel_id,
            streamer_id=channel.streamer_id,
            handle=channel.handle,
            name=channel.name,
            youtube_channel_id=channel.youtube_channel_id,
        )
        self.channels[record.id] = record
        self.next_channel_id += 1
        return record

    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        self._raise_if_failed()
        records = list(self.channels.values())
        if streamer_id is None:
            return records
        return [record for record in records if record.streamer_id == streamer_id]

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        self._raise_if_failed()
        return self.channels.get(channel_id)

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        self._raise_if_failed()
        record = self.channels.get(channel_id)
        if record is None:
            return None
        streamer_id = update.streamer_id if update.streamer_id is not None else record.streamer_id
        updated = replace(
            record,
            streamer_id=streamer_id,
            handle=update.handle if update.handle is not None else record.handle,
            name=update.name if update.name is not None else record.name,
            youtube_channel_id=(
                update.youtube_channel_id
                if update.youtube_channel_id_set
                else record.youtube_channel_id
            ),
        )
        self.channels[channel_id] = updated
        return updated

    async def delete_channel(self, channel_id: int) -> bool:
        self._raise_if_failed()
        if channel_id not in self.channels:
            return False
        del self.channels[channel_id]
        return True

    async def update_youtube_channel_id_by_handle(
        self,
        *,
        handle: str,
        youtube_channel_id: str,
    ) -> list[ChannelRecord]:
        self._raise_if_failed()
        match_values = _handle_match_values(handle)
        updated: list[ChannelRecord] = []
        for channel_id, record in self.channels.items():
            if record.handle.strip().lower() in match_values:
                channel = replace(record, youtube_channel_id=youtube_channel_id)
                self.channels[channel_id] = channel
                updated.append(channel)
        return updated

    def _raise_if_failed(self) -> None:
        if self.fail_persistence:
            raise StreamerPersistenceError("Streamer persistence failed.")


def test_streamer_and_channel_crud_api() -> None:
    fake = FakeStreamerRepository()

    streamer = asyncio.run(
        _request(fake, "POST", "/streamers", json={"name": " Alpha "}, expected_status=201)
    )
    assert streamer == {"id": 1, "name": "Alpha"}
    assert asyncio.run(_request(fake, "GET", "/streamers")) == [streamer]

    updated_streamer = asyncio.run(
        _request(fake, "PATCH", "/streamers/1", json={"name": "Beta"})
    )
    assert updated_streamer == {"id": 1, "name": "Beta"}

    channel = asyncio.run(
        _request(
            fake,
            "POST",
            "/channels",
            json={
                "streamerId": 1,
                "handle": " @beta ",
                "name": " Main ",
                "youtubeChannelId": None,
            },
            expected_status=201,
        )
    )
    assert channel == {
        "id": 1,
        "streamerId": 1,
        "handle": "@beta",
        "name": "Main",
        "youtubeChannelId": None,
    }
    assert asyncio.run(_request(fake, "GET", "/channels?streamerId=1")) == [channel]
    assert asyncio.run(_request(fake, "GET", "/channels/1")) == channel

    updated_channel = asyncio.run(
        _request(fake, "PATCH", "/channels/1", json={"youtubeChannelId": "UC123"})
    )
    assert updated_channel["youtubeChannelId"] == "UC123"

    cleared_channel = asyncio.run(
        _request(fake, "PATCH", "/channels/1", json={"youtubeChannelId": None})
    )
    assert cleared_channel["youtubeChannelId"] is None

    assert asyncio.run(_request(fake, "DELETE", "/channels/1")) == {"success": True}
    assert asyncio.run(_request(fake, "DELETE", "/streamers/1")) == {"success": True}


def test_streamer_api_maps_not_found_and_delete_conflict() -> None:
    fake = FakeStreamerRepository()

    missing = asyncio.run(_request(fake, "GET", "/streamers/404", expected_status=404))
    assert missing == {"detail": "Streamer not found."}

    asyncio.run(_request(fake, "POST", "/streamers", json={"name": "Alpha"}, expected_status=201))
    asyncio.run(
        _request(
            fake,
            "POST",
            "/channels",
            json={"streamerId": 1, "handle": "@alpha", "name": "Alpha"},
            expected_status=201,
        )
    )

    conflict = asyncio.run(_request(fake, "DELETE", "/streamers/1", expected_status=409))
    assert conflict == {"detail": "Streamer has channels and cannot be deleted."}


def test_channel_api_maps_missing_streamer_to_not_found() -> None:
    response = asyncio.run(
        _request(
            FakeStreamerRepository(),
            "POST",
            "/channels",
            json={"streamerId": 99, "handle": "@missing", "name": "Missing"},
            expected_status=404,
        )
    )

    assert response == {"detail": "Streamer not found."}


def test_streamer_api_maps_persistence_errors() -> None:
    fake = FakeStreamerRepository()
    fake.fail_persistence = True

    response = asyncio.run(
        _request(fake, "POST", "/streamers", json={"name": "Alpha"}, expected_status=503)
    )

    assert response == {"detail": "Streamer persistence failed."}


def test_channel_patch_rejects_empty_body() -> None:
    response = asyncio.run(
        _request(FakeStreamerRepository(), "PATCH", "/channels/1", json={}, expected_status=422)
    )

    assert response["detail"][0]["type"] == "value_error"


def _handle_match_values(handle: str) -> set[str]:
    normalized = handle.strip().lower()
    if normalized.startswith("@"):
        normalized = normalized[1:].strip()
    return {normalized, f"@{normalized}"}


async def _request(
    repository: FakeStreamerRepository,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_streamer_repository] = lambda: repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.request(method, path, json=json)

    assert response.status_code == expected_status, response.text
    return response.json()
