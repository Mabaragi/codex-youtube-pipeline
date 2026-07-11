from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ResolvedChannel:
    channel_id: int
    streamer_id: int
    handle: str
    name: str
    youtube_channel_id: str
    uploads_playlist_id: str


class ChannelResolverPort(Protocol):
    async def resolve(
        self,
        *,
        streamer_id: int,
        handle: str,
        work_item_id: int,
        work_attempt_id: int,
    ) -> ResolvedChannel: ...
