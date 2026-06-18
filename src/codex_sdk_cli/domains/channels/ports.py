from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ChannelRecord:
    id: int
    streamer_id: int
    handle: str
    name: str
    youtube_channel_id: str | None
    uploads_playlist_id: str | None
    source_api_call_id: int | None
    source_job_id: int | None = None


@dataclass(frozen=True, slots=True)
class ChannelCreate:
    streamer_id: int
    handle: str
    name: str
    youtube_channel_id: str | None
    uploads_playlist_id: str | None = None
    source_api_call_id: int | None = None
    source_job_id: int | None = None


@dataclass(frozen=True, slots=True)
class ChannelUpdate:
    handle: str | None = None
    name: str | None = None
    youtube_channel_id: str | None = None
    youtube_channel_id_set: bool = False


class ChannelRepositoryPort(Protocol):
    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        """Create a channel."""

    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        """List channels, optionally filtered by streamer."""

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        """Return one channel by internal ID."""

    async def get_channel_by_youtube_channel_id(
        self,
        youtube_channel_id: str,
    ) -> ChannelRecord | None:
        """Return one channel by unique YouTube channel ID."""

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        """Update one channel by internal ID."""

    async def update_uploads_playlist_id(
        self,
        channel_id: int,
        uploads_playlist_id: str,
    ) -> ChannelRecord | None:
        """Update the cached uploads playlist ID for one channel."""

    async def delete_channel(self, channel_id: int) -> bool:
        """Delete one channel by internal ID."""
