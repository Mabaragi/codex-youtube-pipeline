from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StreamerRecord:
    id: int
    name: str


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
