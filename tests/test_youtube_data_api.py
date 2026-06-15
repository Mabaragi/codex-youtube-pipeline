from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_settings,
    get_streamer_repository,
    get_youtube_data_client,
)
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.streamers.ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelUpdate,
    StreamerRecord,
    StreamerRepositoryPort,
)
from codex_sdk_cli.domains.youtube_data.exceptions import (
    YouTubeDataChannelNotFound,
    YouTubeDataDomainError,
    YouTubeDataUpstreamError,
)
from codex_sdk_cli.domains.youtube_data.ports import (
    YouTubeChannelHandleResult,
    YouTubeDataClientPort,
)
from codex_sdk_cli.settings import CliSettings


class FakeYouTubeDataClient(YouTubeDataClientPort):
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.error: YouTubeDataDomainError | None = None
        self.youtube_channel_id = "UC_x5XG1OV2P6uZZ5FSM9Ttw"

    async def resolve_channel_id_by_handle(self, handle: str) -> YouTubeChannelHandleResult:
        self.requests.append(handle)
        if self.error is not None:
            raise self.error
        return YouTubeChannelHandleResult(
            handle=handle,
            youtube_channel_id=self.youtube_channel_id,
        )


class FakeStreamerRepository(StreamerRepositoryPort):
    def __init__(self) -> None:
        self.streamers: dict[int, StreamerRecord] = {}
        self.channels: dict[int, ChannelRecord] = {}

    async def create_streamer(self, *, name: str) -> StreamerRecord:
        record = StreamerRecord(id=len(self.streamers) + 1, name=name)
        self.streamers[record.id] = record
        return record

    async def list_streamers(self) -> list[StreamerRecord]:
        return list(self.streamers.values())

    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        return self.streamers.get(streamer_id)

    async def update_streamer(self, streamer_id: int, *, name: str) -> StreamerRecord | None:
        record = self.streamers.get(streamer_id)
        if record is None:
            return None
        updated = replace(record, name=name)
        self.streamers[streamer_id] = updated
        return updated

    async def delete_streamer(self, streamer_id: int) -> bool:
        return self.streamers.pop(streamer_id, None) is not None

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        record = ChannelRecord(
            id=len(self.channels) + 1,
            streamer_id=channel.streamer_id,
            handle=channel.handle,
            name=channel.name,
            youtube_channel_id=channel.youtube_channel_id,
        )
        self.channels[record.id] = record
        return record

    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        records = list(self.channels.values())
        if streamer_id is None:
            return records
        return [record for record in records if record.streamer_id == streamer_id]

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        return self.channels.get(channel_id)

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        record = self.channels.get(channel_id)
        if record is None:
            return None
        updated = replace(
            record,
            streamer_id=update.streamer_id if update.streamer_id else record.streamer_id,
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
        return self.channels.pop(channel_id, None) is not None

    async def update_youtube_channel_id_by_handle(
        self,
        *,
        handle: str,
        youtube_channel_id: str,
    ) -> list[ChannelRecord]:
        match_values = _handle_match_values(handle)
        updated: list[ChannelRecord] = []
        for channel_id, record in self.channels.items():
            if record.handle.strip().lower() in match_values:
                channel = replace(record, youtube_channel_id=youtube_channel_id)
                self.channels[channel_id] = channel
                updated.append(channel)
        return updated


def test_youtube_data_resolve_updates_matching_local_channels() -> None:
    client = FakeYouTubeDataClient()
    repository = FakeStreamerRepository()
    repository.channels = {
        1: _channel(id=1, handle="@GoogleDevelopers"),
        2: _channel(id=2, handle=" googledevelopers "),
        3: _channel(id=3, handle="@Other"),
    }

    response = asyncio.run(_request(client, repository, json={"handle": " @GoogleDevelopers "}))

    assert response == {
        "handle": "@GoogleDevelopers",
        "youtubeChannelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
        "updatedChannelIds": [1, 2],
    }
    assert client.requests == ["@GoogleDevelopers"]
    assert repository.channels[1].youtube_channel_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert repository.channels[2].youtube_channel_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert repository.channels[3].youtube_channel_id is None


def test_youtube_data_resolve_returns_empty_updates_when_no_local_channel_matches() -> None:
    client = FakeYouTubeDataClient()
    repository = FakeStreamerRepository()

    response = asyncio.run(_request(client, repository, json={"handle": "@GoogleDevelopers"}))

    assert response["youtubeChannelId"] == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert response["updatedChannelIds"] == []


def test_youtube_data_resolve_maps_missing_channel_to_not_found() -> None:
    client = FakeYouTubeDataClient()
    client.error = YouTubeDataChannelNotFound("YouTube channel was not found for this handle.")

    response = asyncio.run(
        _request(
            client,
            FakeStreamerRepository(),
            json={"handle": "@missing"},
            expected_status=404,
        )
    )

    assert response == {"detail": "YouTube channel was not found for this handle."}


def test_youtube_data_resolve_maps_upstream_errors() -> None:
    client = FakeYouTubeDataClient()
    client.error = YouTubeDataUpstreamError("YouTube Data API request failed upstream.")

    response = asyncio.run(
        _request(
            client,
            FakeStreamerRepository(),
            json={"handle": "@blocked"},
            expected_status=502,
        )
    )

    assert response == {"detail": "YouTube Data API request failed upstream."}


def test_youtube_data_resolve_requires_api_key_configuration() -> None:
    response = asyncio.run(
        _request_without_client_override(
            FakeStreamerRepository(),
            json={"handle": "@GoogleDevelopers"},
            expected_status=503,
        )
    )

    assert response == {"detail": "YouTube Data API key is not configured."}


def test_youtube_data_openapi_path_and_tag() -> None:
    app = create_app()
    schema = app.openapi()

    path_item = schema["paths"]["/youtube-data/channels/resolve"]

    assert path_item["post"]["tags"] == ["youtube-data"]


async def _request(
    youtube_data_client: FakeYouTubeDataClient,
    repository: FakeStreamerRepository,
    *,
    json: dict[str, Any],
    expected_status: int = 200,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_youtube_data_client] = lambda: youtube_data_client
    app.dependency_overrides[get_streamer_repository] = lambda: repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/youtube-data/channels/resolve", json=json)

    assert response.status_code == expected_status, response.text
    return response.json()


async def _request_without_client_override(
    repository: FakeStreamerRepository,
    *,
    json: dict[str, Any],
    expected_status: int = 200,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: CliSettings(youtube_data_api_key=None)
    app.dependency_overrides[get_streamer_repository] = lambda: repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/youtube-data/channels/resolve", json=json)

    assert response.status_code == expected_status, response.text
    return response.json()


def _channel(*, id: int, handle: str) -> ChannelRecord:
    return ChannelRecord(
        id=id,
        streamer_id=1,
        handle=handle,
        name=handle,
        youtube_channel_id=None,
    )


def _handle_match_values(handle: str) -> set[str]:
    normalized = handle.strip().lower()
    if normalized.startswith("@"):
        normalized = normalized[1:].strip()
    return {normalized, f"@{normalized}"}

