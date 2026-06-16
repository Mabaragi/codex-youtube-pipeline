from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class YouTubeChannelResolution:
    handle: str
    youtube_channel_id: str
    title: str
    source_api_call_id: int


class YouTubeDataClientPort(Protocol):
    async def resolve_youtube_channel_by_handle(self, handle: str) -> YouTubeChannelResolution:
        """Resolve YouTube channel metadata from a public handle."""
