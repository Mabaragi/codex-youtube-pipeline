from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import get_channel_repository, get_streamer_repository
from codex_sdk_cli.api.use_case_dependencies.operation_events import (
    get_record_operator_mutation_use_case,
)
from codex_sdk_cli.domains.channels.exceptions import (
    ChannelAlreadyExists,
    ChannelPersistenceError,
)
from codex_sdk_cli.domains.channels.ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelRepositoryPort,
    ChannelUpdate,
)
from codex_sdk_cli.domains.streamers.exceptions import (
    StreamerHasChannels,
    StreamerPersistenceError,
)
from codex_sdk_cli.domains.streamers.ports import StreamerRecord, StreamerRepositoryPort
from tests.support.legacy_api import create_legacy_app as create_app


class FakeStreamerRepository(StreamerRepositoryPort):
    def __init__(self) -> None:
        self.streamers: dict[int, StreamerRecord] = {}
        self.channel_streamer_ids: set[int] = set()
        self.next_streamer_id = 1
        self.fail_persistence = False

    async def create_streamer(
        self,
        *,
        name: str,
        publish_profile_id: int = 1,
    ) -> StreamerRecord:
        self._raise_if_failed()
        record = StreamerRecord(
            id=self.next_streamer_id,
            name=name,
            publish_profile_id=publish_profile_id,
        )
        self.streamers[record.id] = record
        self.next_streamer_id += 1
        return record

    async def list_streamers(self) -> list[StreamerRecord]:
        self._raise_if_failed()
        return list(self.streamers.values())

    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        self._raise_if_failed()
        return self.streamers.get(streamer_id)

    async def update_streamer(
        self,
        streamer_id: int,
        *,
        name: str | None = None,
        publish_profile_id: int | None = None,
    ) -> StreamerRecord | None:
        self._raise_if_failed()
        record = self.streamers.get(streamer_id)
        if record is None:
            return None
        updated = replace(
            record,
            name=name if name is not None else record.name,
            publish_profile_id=(
                publish_profile_id
                if publish_profile_id is not None
                else record.publish_profile_id
            ),
        )
        self.streamers[streamer_id] = updated
        return updated

    async def is_publish_profile_active(self, publish_profile_id: int) -> bool:
        self._raise_if_failed()
        return publish_profile_id == 1

    async def has_archive_artifacts(self, streamer_id: int) -> bool:
        self._raise_if_failed()
        return False

    async def delete_streamer(self, streamer_id: int) -> bool:
        self._raise_if_failed()
        if streamer_id not in self.streamers:
            return False
        if streamer_id in self.channel_streamer_ids:
            raise StreamerHasChannels("Streamer has channels and cannot be deleted.")
        del self.streamers[streamer_id]
        return True

    def _raise_if_failed(self) -> None:
        if self.fail_persistence:
            raise StreamerPersistenceError("Streamer persistence failed.")


class FakeChannelRepository(ChannelRepositoryPort):
    def __init__(self, streamers: FakeStreamerRepository | None = None) -> None:
        self.streamers = streamers
        self.channels: dict[int, ChannelRecord] = {}
        self.next_channel_id = 1
        self.fail_persistence = False

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        self._raise_if_failed()
        existing = await self.get_channel_by_youtube_channel_id(channel.youtube_channel_id or "")
        if channel.youtube_channel_id is not None and existing is not None:
            raise ChannelAlreadyExists("YouTube channel already exists.")
        record = ChannelRecord(
            id=self.next_channel_id,
            streamer_id=channel.streamer_id,
            handle=channel.handle,
            name=channel.name,
            youtube_channel_id=channel.youtube_channel_id,
            uploads_playlist_id=channel.uploads_playlist_id,
            source_api_call_id=channel.source_api_call_id,
            source_job_id=channel.source_job_id,
        )
        self.channels[record.id] = record
        self.next_channel_id += 1
        self._sync_streamer_channel_ids()
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

    async def get_channel_by_youtube_channel_id(
        self,
        youtube_channel_id: str,
    ) -> ChannelRecord | None:
        self._raise_if_failed()
        return next(
            (
                record
                for record in self.channels.values()
                if record.youtube_channel_id == youtube_channel_id
            ),
            None,
        )

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        self._raise_if_failed()
        record = self.channels.get(channel_id)
        if record is None:
            return None
        updated = replace(
            record,
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

    async def update_uploads_playlist_id(
        self,
        channel_id: int,
        uploads_playlist_id: str,
    ) -> ChannelRecord | None:
        self._raise_if_failed()
        record = self.channels.get(channel_id)
        if record is None:
            return None
        updated = replace(record, uploads_playlist_id=uploads_playlist_id)
        self.channels[channel_id] = updated
        return updated

    async def delete_channel(self, channel_id: int) -> bool:
        self._raise_if_failed()
        if channel_id not in self.channels:
            return False
        del self.channels[channel_id]
        self._sync_streamer_channel_ids()
        return True

    def _sync_streamer_channel_ids(self) -> None:
        if self.streamers is not None:
            self.streamers.channel_streamer_ids = {
                channel.streamer_id for channel in self.channels.values()
            }

    def _raise_if_failed(self) -> None:
        if self.fail_persistence:
            raise ChannelPersistenceError("Channel persistence failed.")


class RecordingOperatorAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def execute(self, **event: object) -> None:
        self.events.append(event)


def test_streamer_and_channel_crud_api() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)

    streamer = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers",
            json={"name": " Alpha ", "publishProfileId": 1},
            expected_status=201,
        )
    )
    assert streamer == {"id": 1, "name": "Alpha", "publishProfileId": 1}
    assert asyncio.run(_request(streamers, channels, "GET", "/streamers")) == [streamer]

    updated_streamer = asyncio.run(
        _request(streamers, channels, "PATCH", "/streamers/1", json={"name": "Beta"})
    )
    assert updated_streamer == {"id": 1, "name": "Beta", "publishProfileId": 1}

    channel = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers/1/channels",
            json={
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
        "uploadsPlaylistId": None,
        "sourceApiCallId": None,
        "sourceJobId": None,
    }
    assert asyncio.run(_request(streamers, channels, "GET", "/streamers/1/channels")) == [
        channel
    ]
    assert asyncio.run(_request(streamers, channels, "GET", "/channels")) == [channel]
    assert asyncio.run(_request(streamers, channels, "GET", "/channels/1")) == channel

    updated_channel = asyncio.run(
        _request(streamers, channels, "PATCH", "/channels/1", json={"youtubeChannelId": "UC123"})
    )
    assert updated_channel["youtubeChannelId"] == "UC123"

    cleared_channel = asyncio.run(
        _request(streamers, channels, "PATCH", "/channels/1", json={"youtubeChannelId": None})
    )
    assert cleared_channel["youtubeChannelId"] is None

    assert asyncio.run(_request(streamers, channels, "DELETE", "/channels/1")) == {
        "success": True
    }
    assert asyncio.run(_request(streamers, channels, "DELETE", "/streamers/1")) == {
        "success": True
    }


def test_streamer_profile_mutations_require_reason_and_record_audit() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)
    audit = RecordingOperatorAudit()

    missing_reason = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers",
            json={"name": "Alpha", "publishProfileId": 1},
            expected_status=422,
            operator_reason=None,
            audit=audit,
        )
    )
    assert missing_reason["detail"][0]["loc"][-1] == "X-Operator-Reason"

    created = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers",
            json={"name": "Alpha", "publishProfileId": 1},
            expected_status=201,
            operator_reason="assign publication route",
            audit=audit,
        )
    )
    asyncio.run(
        _request(
            streamers,
            channels,
            "PATCH",
            f"/streamers/{created['id']}",
            json={"publishProfileId": 1},
            operator_reason="confirm publication route",
            audit=audit,
        )
    )

    assert [event["mutation"] for event in audit.events] == ["created", "updated"]
    assert audit.events[0]["metadata"] == {"publishProfileId": 1}
    assert audit.events[1]["metadata"] == {
        "publishProfileId": 1,
        "publishProfileChanged": True,
    }


def test_streamer_mutation_openapi_requires_operator_reason() -> None:
    schema = create_app().openapi()
    for method, path in (("post", "/streamers"), ("patch", "/streamers/{streamer_id}")):
        parameters = schema["paths"][path][method]["parameters"]
        reason = next(item for item in parameters if item["name"] == "X-Operator-Reason")
        assert reason["required"] is True


def test_streamer_api_maps_not_found_and_delete_conflict() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)

    missing = asyncio.run(
        _request(streamers, channels, "GET", "/streamers/404", expected_status=404)
    )
    assert missing == {"detail": "Streamer not found."}

    asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers",
            json={"name": "Alpha", "publishProfileId": 1},
            expected_status=201,
        )
    )
    asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers/1/channels",
            json={"handle": "@alpha", "name": "Alpha"},
            expected_status=201,
        )
    )

    conflict = asyncio.run(
        _request(streamers, channels, "DELETE", "/streamers/1", expected_status=409)
    )
    assert conflict == {"detail": "Streamer has channels and cannot be deleted."}


def test_streamer_api_rejects_an_inactive_publish_profile() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)

    response = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers",
            json={"name": "Alpha", "publishProfileId": 2},
            expected_status=404,
        )
    )

    assert response == {"detail": "Publish profile does not exist or has no active revision."}


def test_channel_api_maps_missing_streamer_to_not_found() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)

    response = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers/99/channels",
            json={"handle": "@missing", "name": "Missing"},
            expected_status=404,
        )
    )

    assert response == {"detail": "Streamer not found."}


def test_streamer_api_maps_persistence_errors() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)
    streamers.fail_persistence = True

    response = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers",
            json={"name": "Alpha", "publishProfileId": 1},
            expected_status=503,
        )
    )

    assert response == {"detail": "Streamer persistence failed."}


def test_channel_create_reuses_same_streamer_youtube_channel_id() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)
    streamers.streamers[1] = StreamerRecord(id=1, name="Alpha", publish_profile_id=1)

    first = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers/1/channels",
            json={"handle": "@alpha", "name": "Alpha", "youtubeChannelId": "UC123"},
            expected_status=201,
        )
    )
    second = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers/1/channels",
            json={"handle": "@alpha-copy", "name": "Alpha Copy", "youtubeChannelId": "UC123"},
            expected_status=201,
        )
    )

    assert second == first
    assert len(channels.channels) == 1


def test_channel_create_rejects_youtube_channel_id_owned_by_other_streamer() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)
    streamers.streamers[1] = StreamerRecord(id=1, name="Alpha", publish_profile_id=1)
    streamers.streamers[2] = StreamerRecord(id=2, name="Beta", publish_profile_id=1)

    asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers/1/channels",
            json={"handle": "@alpha", "name": "Alpha", "youtubeChannelId": "UC123"},
            expected_status=201,
        )
    )
    response = asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers/2/channels",
            json={"handle": "@beta", "name": "Beta", "youtubeChannelId": "UC123"},
            expected_status=409,
        )
    )

    assert response == {"detail": "YouTube channel already belongs to another streamer."}


def test_channel_patch_rejects_duplicate_youtube_channel_id() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)
    streamers.streamers[1] = StreamerRecord(id=1, name="Alpha", publish_profile_id=1)

    asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers/1/channels",
            json={"handle": "@alpha", "name": "Alpha", "youtubeChannelId": "UC123"},
            expected_status=201,
        )
    )
    asyncio.run(
        _request(
            streamers,
            channels,
            "POST",
            "/streamers/1/channels",
            json={"handle": "@alpha-2", "name": "Alpha 2"},
            expected_status=201,
        )
    )

    response = asyncio.run(
        _request(
            streamers,
            channels,
            "PATCH",
            "/channels/2",
            json={"youtubeChannelId": "UC123"},
            expected_status=409,
        )
    )

    assert response == {"detail": "YouTube channel already exists."}


def test_channel_patch_rejects_streamer_id_and_empty_body() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository(streamers)

    streamer_response = asyncio.run(
        _request(
            streamers,
            channels,
            "PATCH",
            "/channels/1",
            json={"streamerId": 2},
            expected_status=422,
        )
    )
    empty_response = asyncio.run(
        _request(streamers, channels, "PATCH", "/channels/1", json={}, expected_status=422)
    )

    assert streamer_response["detail"][0]["type"] == "extra_forbidden"
    assert empty_response["detail"][0]["type"] == "value_error"


async def _request(
    streamers: FakeStreamerRepository,
    channels: FakeChannelRepository,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    expected_status: int = 200,
    operator_reason: str | None = "legacy regression test",
    audit: RecordingOperatorAudit | None = None,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_streamer_repository] = lambda: streamers
    app.dependency_overrides[get_channel_repository] = lambda: channels
    app.dependency_overrides[get_record_operator_mutation_use_case] = lambda: (
        audit or RecordingOperatorAudit()
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        needs_reason = method == "DELETE" or (
            path == "/streamers" and method == "POST"
        ) or (path.startswith("/streamers/") and method == "PATCH")
        headers = (
            {"X-Operator-Reason": operator_reason}
            if needs_reason and operator_reason is not None
            else None
        )
        response = await client.request(method, path, json=json, headers=headers)

    assert response.status_code == expected_status, response.text
    return response.json()
