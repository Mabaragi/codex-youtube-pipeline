from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine

import httpx
import pytest

from codex_sdk_cli.domains.youtube_data.exceptions import (
    YouTubeDataChannelNotFound,
    YouTubeDataUpstreamError,
)
from codex_sdk_cli.domains.youtube_data.ports import YouTubeChannelHandleResult
from codex_sdk_cli.infra.youtube_data.client import YouTubeDataClient


def test_youtube_data_client_resolves_channel_id_and_sends_api_key() -> None:
    seen_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        params = request.url.params
        assert params["part"] == "id"
        assert params["forHandle"] == "@GoogleDevelopers"
        assert params["key"] == "AIza-test"
        return httpx.Response(
            200,
            json={"items": [{"id": "UC_x5XG1OV2P6uZZ5FSM9Ttw"}, {"id": "ignored"}]},
        )

    result = asyncio.run(_resolve(handler))

    assert result.youtube_channel_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"
    assert result.handle == "@GoogleDevelopers"
    assert len(seen_requests) == 1


def test_youtube_data_client_maps_empty_items_to_not_found() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})

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


async def _resolve(
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
) -> YouTubeChannelHandleResult:
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = YouTubeDataClient(http_client, api_key="AIza-test")
        return await client.resolve_channel_id_by_handle("@GoogleDevelopers")
