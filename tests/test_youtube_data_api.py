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
    YouTubeChannelResolution,
    YouTubeDataClientPort,
)
from codex_sdk_cli.settings import CliSettings


class FakeYouTubeDataClient(YouTubeDataClientPort):
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.error: YouTubeDataDomainError | None = None
        self.youtube_channel_id = "UC_x5XG1OV2P6uZZ5FSM9Ttw"
        self.title = "Google for Developers"

    async def resolve_youtube_channel_by_handle(self, handle: str) -> YouTubeChannelResolution:
        self.requests.append(handle)
        if self.error is not None:
            raise self.error
        return YouTubeChannelResolution(
            handle=handle,
            youtube_channel_id=self.youtube_channel_id,
            title=self.title,
            source_api_call_id=42,
        )


class FakeStreamerRepository(StreamerRepositoryPort):
    def __init__(self) -> None:
        self.streamers: dict[int, StreamerRecord] = {}
        self.channels: dict[int, ChannelRecord] = {}
        self.next_streamer_id = 1
        self.next_channel_id = 1

    async def create_streamer(self, *, name: str) -> StreamerRecord:
        record = StreamerRecord(id=self.next_streamer_id, name=name)
        self.streamers[record.id] = record
        self.next_streamer_id += 1
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
            id=self.next_channel_id,
            streamer_id=channel.streamer_id,
            handle=channel.handle,
            name=channel.name,
            youtube_channel_id=channel.youtube_channel_id,
            source_api_call_id=channel.source_api_call_id,
        )
        self.channels[record.id] = record
        self.next_channel_id += 1
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


def test_youtube_data_resolve_creates_one_channel_for_streamer() -> None:
    client = FakeYouTubeDataClient()
    repository = FakeStreamerRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request(
            client,
            repository,
            json={"streamerId": 1, "handle": " @GoogleDevelopers "},
            expected_status=201,
        )
    )

    assert response == {
        "channelId": 1,
        "streamerId": 1,
        "handle": "@GoogleDevelopers",
        "name": "Google for Developers",
        "youtubeChannelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
        "sourceApiCallId": 42,
    }
    assert client.requests == ["@GoogleDevelopers"]
    assert repository.channels[1] == ChannelRecord(
        id=1,
        streamer_id=1,
        handle="@GoogleDevelopers",
        name="Google for Developers",
        youtube_channel_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
        source_api_call_id=42,
    )


def test_youtube_data_resolve_accepts_matching_expected_youtube_channel_id() -> None:
    client = FakeYouTubeDataClient()
    repository = FakeStreamerRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request(
            client,
            repository,
            json={
                "streamerId": 1,
                "handle": "@GoogleDevelopers",
                "youtubeChannelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
            },
            expected_status=201,
        )
    )

    assert response["youtubeChannelId"] == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert response["channelId"] == 1


def test_youtube_data_resolve_rejects_mismatched_youtube_channel_id() -> None:
    client = FakeYouTubeDataClient()
    repository = FakeStreamerRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request(
            client,
            repository,
            json={
                "streamerId": 1,
                "handle": "@GoogleDevelopers",
                "youtubeChannelId": "UC-other",
            },
            expected_status=400,
        )
    )

    assert response == {"detail": "Resolved YouTube channel ID did not match the request."}
    assert repository.channels == {}


def test_youtube_data_resolve_maps_missing_streamer_to_not_found() -> None:
    response = asyncio.run(
        _request(
            FakeYouTubeDataClient(),
            FakeStreamerRepository(),
            json={"streamerId": 404, "handle": "@GoogleDevelopers"},
            expected_status=404,
        )
    )

    assert response == {"detail": "Streamer not found."}


def test_youtube_data_resolve_maps_missing_channel_to_not_found() -> None:
    client = FakeYouTubeDataClient()
    client.error = YouTubeDataChannelNotFound("YouTube channel was not found for this handle.")
    repository = FakeStreamerRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Missing")

    response = asyncio.run(
        _request(
            client,
            repository,
            json={"streamerId": 1, "handle": "@missing"},
            expected_status=404,
        )
    )

    assert response == {"detail": "YouTube channel was not found for this handle."}


def test_youtube_data_resolve_maps_upstream_errors() -> None:
    client = FakeYouTubeDataClient()
    client.error = YouTubeDataUpstreamError("YouTube Data API request failed upstream.")
    repository = FakeStreamerRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Blocked")

    response = asyncio.run(
        _request(
            client,
            repository,
            json={"streamerId": 1, "handle": "@blocked"},
            expected_status=502,
        )
    )

    assert response == {"detail": "YouTube Data API request failed upstream."}


def test_youtube_data_resolve_requires_api_key_configuration() -> None:
    repository = FakeStreamerRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request_without_client_override(
            repository,
            json={"streamerId": 1, "handle": "@GoogleDevelopers"},
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
