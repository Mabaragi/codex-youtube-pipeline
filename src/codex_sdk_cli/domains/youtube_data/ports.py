from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class YouTubeChannelHandleResult:
    handle: str
    youtube_channel_id: str


class YouTubeDataClientPort(Protocol):
    async def resolve_channel_id_by_handle(self, handle: str) -> YouTubeChannelHandleResult:
        """Resolve a YouTube channel ID from a public handle."""

