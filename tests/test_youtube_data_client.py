from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime

import httpx
import pytest

from codex_sdk_cli.domains.external_api_calls.ports import (
    ExternalApiCallRecord,
    ExternalApiCallRecorderPort,
    ExternalApiCallRecordRequest,
)
from codex_sdk_cli.domains.youtube_data.exceptions import (
    YouTubeDataChannelNotFound,
    YouTubeDataUpstreamError,
)
from codex_sdk_cli.domains.youtube_data.ports import (
    YouTubeChannelResolution,
    YouTubeVideoListingPage,
)
from codex_sdk_cli.infra.youtube_data.client import YouTubeDataClient


class FakeExternalApiCallRecorder(ExternalApiCallRecorderPort):
    def __init__(self) -> None:
        self.requests: list[ExternalApiCallRecordRequest] = []

    async def record_call(self, request: ExternalApiCallRecordRequest) -> ExternalApiCallRecord:
        self.requests.append(request)
        return ExternalApiCallRecord(
            id=len(self.requests),
            provider=request.provider,
            operation=request.operation,
            request_method=request.request_method,
            request_url=request.request_url,
            request_params=request.request_params,
            request_body=request.request_body,
            response_status_code=request.response_status_code,
            response_headers=request.response_headers,
            response_storage_bucket="raw" if request.response_body is not None else None,
            response_storage_object_name=(
                "external-api-calls/object.json" if request.response_body is not None else None
            ),
            response_storage_uri=(
                "s3://raw/external-api-calls/object.json"
                if request.response_body is not None
                else None
            ),
            response_sha256="hash" if request.response_body is not None else None,
            schema_name=request.schema_name,
            schema_version=request.schema_version,
            validation_status=request.validation_status,
            validation_error=request.validation_error,
            duration_ms=request.duration_ms,
            quota_cost=request.quota_cost,
            created_at=datetime.now(UTC),
            pipeline_job_attempt_id=request.pipeline_job_attempt_id,
        )


def test_youtube_data_client_resolves_channel_id_and_sends_api_key() -> None:
    seen_requests: list[httpx.Request] = []
    recorder = FakeExternalApiCallRecorder()

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        params = request.url.params
        assert params["part"] == "id,snippet,contentDetails"
        assert params["forHandle"] == "@GoogleDevelopers"
        assert params["key"] == "AIza-test"
        return httpx.Response(200, json=_channels_list_payload())

    result = asyncio.run(_resolve(handler, recorder=recorder))

    assert result.youtube_channel_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert result.handle == "@GoogleDevelopers"
    assert result.title == "Google for Developers"
    assert result.uploads_playlist_id == "UU_x5XG1OV2P6uZZ5FSM9Ttw"
    assert result.source_api_call_id == 1
    assert len(seen_requests) == 1
    assert recorder.requests[0].request_params == {
        "part": "id,snippet,contentDetails",
        "forHandle": "@GoogleDevelopers",
    }
    assert "key" not in recorder.requests[0].request_params
    assert recorder.requests[0].validation_status == "valid"
    assert recorder.requests[0].pipeline_job_attempt_id == 7


def test_youtube_data_client_maps_empty_items_to_not_found() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_channels_list_payload(items=[]))

    with pytest.raises(YouTubeDataChannelNotFound):
        asyncio.run(_resolve(handler))


@pytest.mark.parametrize("status_code", [400, 403, 500])
def test_youtube_data_client_maps_error_statuses_to_upstream(status_code: int) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": "boom"}})

    with pytest.raises(YouTubeDataUpstreamError):
        asyncio.run(_resolve(handler))


def test_youtube_data_client_maps_invalid_json_to_upstream() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{", headers={"content-type": "application/json"})

    with pytest.raises(YouTubeDataUpstreamError):
        asyncio.run(_resolve(handler))


def test_youtube_data_client_maps_schema_mismatch_to_upstream() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_channels_list_payload(items=[{"id": "UC_x5XG1OV2P6uZZ5FSM9Ttw"}]),
        )

    with pytest.raises(YouTubeDataUpstreamError):
        asyncio.run(_resolve(handler))


def test_youtube_data_client_records_invalid_schema_before_raising() -> None:
    recorder = FakeExternalApiCallRecorder()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_channels_list_payload(items=[{"id": "UC_x5XG1OV2P6uZZ5FSM9Ttw"}]),
        )

    with pytest.raises(YouTubeDataUpstreamError):
        asyncio.run(_resolve(handler, recorder=recorder))

    assert recorder.requests[0].validation_status == "invalid"
    assert recorder.requests[0].schema_name == "YouTubeChannelsListResponse"
    assert recorder.requests[0].pipeline_job_attempt_id == 7


def test_youtube_data_client_lists_upload_playlist_videos_and_sanitizes_api_key() -> None:
    recorder = FakeExternalApiCallRecorder()

    async def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert str(request.url).startswith(
            "https://www.googleapis.com/youtube/v3/playlistItems"
        )
        assert params["part"] == "snippet,contentDetails"
        assert params["playlistId"] == "UU_x5XG1OV2P6uZZ5FSM9Ttw"
        assert params["maxResults"] == "50"
        assert params["pageToken"] == "next"
        assert params["key"] == "AIza-test"
        return httpx.Response(200, json=_playlist_items_list_payload())

    result = asyncio.run(_listing(handler, recorder=recorder, page_token="next"))

    assert [video.youtube_video_id for video in result.videos] == ["video-1", "video-2"]
    assert result.videos[0].title == "Newest upload"
    assert result.videos[0].published_at == datetime(2026, 6, 16, 1, 2, 3, tzinfo=UTC)
    assert result.videos[0].thumbnail_url == "https://img.example/high.jpg"
    assert result.next_page_token == "older"
    assert result.source_api_call_id == 1
    assert recorder.requests[0].operation == "playlistItems.list"
    assert recorder.requests[0].request_params == {
        "part": "snippet,contentDetails",
        "playlistId": "UU_x5XG1OV2P6uZZ5FSM9Ttw",
        "maxResults": "50",
        "pageToken": "next",
    }
    assert "key" not in recorder.requests[0].request_params
    assert recorder.requests[0].quota_cost == 1
    assert recorder.requests[0].pipeline_job_attempt_id == 7


def test_youtube_data_client_fetches_video_details_projection() -> None:
    recorder = FakeExternalApiCallRecorder()

    async def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert str(request.url).startswith("https://www.googleapis.com/youtube/v3/videos")
        assert params["part"] == "contentDetails"
        assert params["id"] == "video-1,video-2"
        assert params["key"] == "AIza-test"
        return httpx.Response(200, json=_videos_list_payload())

    result = asyncio.run(_details(handler, recorder=recorder))

    assert result.source_api_call_id == 1
    assert [video.youtube_video_id for video in result.videos] == ["video-1", "video-2"]
    first = result.videos[0]
    assert first.duration == "PT3M21S"
    assert first.source_api_call_id == 1
    assert recorder.requests[0].operation == "videos.list"
    assert "key" not in recorder.requests[0].request_params
    assert recorder.requests[0].quota_cost == 1
    assert recorder.requests[0].schema_name == "YouTubeVideosListResponse"


def test_youtube_data_client_records_invalid_playlist_schema_before_raising() -> None:
    recorder = FakeExternalApiCallRecorder()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_playlist_items_list_payload(items=[{"snippet": {"title": "Missing ID"}}]),
        )

    with pytest.raises(YouTubeDataUpstreamError):
        asyncio.run(_listing(handler, recorder=recorder))

    assert recorder.requests[0].operation == "playlistItems.list"
    assert recorder.requests[0].validation_status == "invalid"
    assert recorder.requests[0].schema_name == "YouTubePlaylistItemsListResponse"


async def _resolve(
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
    *,
    recorder: FakeExternalApiCallRecorder | None = None,
) -> YouTubeChannelResolution:
    if recorder is None:
        recorder = FakeExternalApiCallRecorder()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = YouTubeDataClient(
            http_client,
            api_key="AIza-test",
            api_call_recorder=recorder,
        )
        return await client.resolve_youtube_channel_by_handle(
            "@GoogleDevelopers",
            pipeline_job_attempt_id=7,
        )


async def _listing(
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
    *,
    recorder: FakeExternalApiCallRecorder | None = None,
    page_token: str | None = None,
) -> YouTubeVideoListingPage:
    if recorder is None:
        recorder = FakeExternalApiCallRecorder()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = YouTubeDataClient(
            http_client,
            api_key="AIza-test",
            api_call_recorder=recorder,
        )
        return await client.list_upload_playlist_videos(
            "UU_x5XG1OV2P6uZZ5FSM9Ttw",
            page_token=page_token,
            pipeline_job_attempt_id=7,
        )


async def _details(
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
    *,
    recorder: FakeExternalApiCallRecorder | None = None,
):
    if recorder is None:
        recorder = FakeExternalApiCallRecorder()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = YouTubeDataClient(
            http_client,
            api_key="AIza-test",
            api_call_recorder=recorder,
        )
        return await client.get_video_details(
            ("video-1", "video-2"),
            pipeline_job_attempt_id=7,
        )


def _channels_list_payload(*, items: list[object] | None = None) -> dict[str, object]:
    if items is None:
        items = [
            {
                "kind": "youtube#channel",
                "etag": "channel-etag",
                "id": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
                "snippet": {"title": "Google for Developers"},
                "contentDetails": {
                    "relatedPlaylists": {
                        "uploads": "UU_x5XG1OV2P6uZZ5FSM9Ttw",
                    }
                },
            },
            {
                "kind": "youtube#channel",
                "etag": "ignored-etag",
                "id": "ignored",
                "snippet": {"title": "Ignored"},
                "contentDetails": {
                    "relatedPlaylists": {
                        "uploads": "UU_ignored",
                    }
                },
            },
        ]
    return {
        "kind": "youtube#channelListResponse",
        "etag": "list-etag",
        "pageInfo": {"totalResults": len(items), "resultsPerPage": len(items)},
        "items": items,
    }


def _playlist_items_list_payload(*, items: list[object] | None = None) -> dict[str, object]:
    if items is None:
        items = [
            {
                "snippet": {
                    "title": "Newest upload",
                    "description": "first",
                    "thumbnails": {
                        "default": {"url": "https://img.example/default.jpg"},
                        "high": {"url": "https://img.example/high.jpg"},
                    },
                },
                "contentDetails": {
                    "videoId": "video-1",
                    "videoPublishedAt": "2026-06-16T01:02:03Z",
                },
            },
            {
                "snippet": {
                    "title": "Older upload",
                    "description": "second",
                    "thumbnails": {},
                },
                "contentDetails": {
                    "videoId": "video-2",
                    "videoPublishedAt": "2026-06-15T01:02:03Z",
                },
            },
        ]
    return {
        "kind": "youtube#playlistItemListResponse",
        "etag": "playlist-etag",
        "nextPageToken": "older",
        "pageInfo": {"totalResults": 2, "resultsPerPage": 2},
        "items": items,
    }


def _videos_list_payload() -> dict[str, object]:
    return {
        "kind": "youtube#videoListResponse",
        "etag": "video-list-etag",
        "pageInfo": {"totalResults": 2, "resultsPerPage": 2},
        "items": [
            {
                "id": "video-1",
                "contentDetails": {"duration": "PT3M21S"},
            },
            {
                "id": "video-2",
                "contentDetails": {"duration": "PT1M"},
            },
        ],
    }
