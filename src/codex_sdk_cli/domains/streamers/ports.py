from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StreamerRecord:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ChannelRecord:
    id: int
    streamer_id: int
    handle: str
    name: str
    youtube_channel_id: str | None


@dataclass(frozen=True, slots=True)
class ChannelCreate:
    streamer_id: int
    handle: str
    name: str
    youtube_channel_id: str | None


@dataclass(frozen=True, slots=True)
class ChannelUpdate:
    streamer_id: int | None = None
    handle: str | None = None
    name: str | None = None
    youtube_channel_id: str | None = None
    youtube_channel_id_set: bool = False


class StreamerRepositoryPort(Protocol):
    async def create_streamer(self, *, name: str) -> StreamerRecord:
        """Create a streamer."""

    async def list_streamers(self) -> list[StreamerRecord]:
        """List streamers."""

    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        """Return one streamer by internal ID."""

    async def update_streamer(self, streamer_id: int, *, name: str) -> StreamerRecord | None:
        """Update one streamer by internal ID."""

    async def delete_streamer(self, streamer_id: int) -> bool:
        """Delete one streamer by internal ID."""

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        """Create a channel."""

    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        """List channels, optionally filtered by streamer."""

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        """Return one channel by internal ID."""

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        """Update one channel by internal ID."""

    async def delete_channel(self, channel_id: int) -> bool:
        """Delete one channel by internal ID."""

    async def update_youtube_channel_id_by_handle(
        self,
        *,
        handle: str,
        youtube_channel_id: str,
    ) -> list[ChannelRecord]:
        """Update YouTube channel IDs for local channels matching a handle."""
