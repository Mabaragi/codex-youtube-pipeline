from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StreamerRecord:
    id: int
    name: str
    publish_profile_id: int


class StreamerRepositoryPort(Protocol):
    async def create_streamer(
        self,
        *,
        name: str,
        publish_profile_id: int,
    ) -> StreamerRecord:
        """Create a streamer."""

    async def list_streamers(self) -> list[StreamerRecord]:
        """List streamers."""

    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        """Return one streamer by internal ID."""

    async def update_streamer(
        self,
        streamer_id: int,
        *,
        name: str | None = None,
        publish_profile_id: int | None = None,
    ) -> StreamerRecord | None:
        """Update one streamer by internal ID."""

    async def is_publish_profile_active(self, publish_profile_id: int) -> bool:
        """Return whether a profile can be assigned to a streamer."""

    async def has_archive_artifacts(self, streamer_id: int) -> bool:
        """Return whether profile changes require a durable publication cutover."""

    async def delete_streamer(self, streamer_id: int) -> bool:
        """Delete one streamer by internal ID."""
