from __future__ import annotations

from typing import Any

import httpx
from typing_extensions import override

from codex_sdk_cli.domains.youtube_data.exceptions import (
    YouTubeDataChannelNotFound,
    YouTubeDataUpstreamError,
)
from codex_sdk_cli.domains.youtube_data.ports import (
    YouTubeChannelHandleResult,
    YouTubeDataClientPort,
)

YOUTUBE_CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"


class YouTubeDataClient(YouTubeDataClientPort):
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        api_key: str,
        channels_endpoint: str = YOUTUBE_CHANNELS_ENDPOINT,
    ) -> None:
        self._http_client = http_client
        self._api_key = api_key
        self._channels_endpoint = channels_endpoint

    @override
    async def resolve_channel_id_by_handle(self, handle: str) -> YouTubeChannelHandleResult:
        try:
            response = await self._http_client.get(
                self._channels_endpoint,
                params={
                    "part": "id",
                    "forHandle": handle,
                    "key": self._api_key,
                },
            )
        except httpx.RequestError as exc:
            raise YouTubeDataUpstreamError("YouTube Data API request failed.") from exc

        if response.status_code >= 400:
            raise YouTubeDataUpstreamError("YouTube Data API request failed upstream.")

        payload = _json_object(response)
        items = payload.get("items")
        if not isinstance(items, list):
            raise YouTubeDataUpstreamError("YouTube Data API response was invalid.")
        if not items:
            raise YouTubeDataChannelNotFound("YouTube channel was not found for this handle.")

        channel_id = _first_channel_id(items)
        if channel_id is None:
            raise YouTubeDataUpstreamError("YouTube Data API response was invalid.")

        return YouTubeChannelHandleResult(handle=handle, youtube_channel_id=channel_id)


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise YouTubeDataUpstreamError("YouTube Data API response was invalid.") from exc
    if not isinstance(payload, dict):
        raise YouTubeDataUpstreamError("YouTube Data API response was invalid.")
    return payload


def _first_channel_id(items: list[object]) -> str | None:
    first_item = items[0]
    if not isinstance(first_item, dict):
        return None
    channel_id = first_item.get("id")
    if not isinstance(channel_id, str) or not channel_id:
        return None
    return channel_id

