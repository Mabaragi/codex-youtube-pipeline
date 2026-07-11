from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias

from codex_sdk_cli.domains.videos.ports import VideoRecord


@dataclass(frozen=True, slots=True)
class SelectedVideos:
    video_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ChannelVideos:
    channel_id: int
    limit: int = 50


@dataclass(frozen=True, slots=True)
class FilteredVideos:
    channel_id: int | None = None
    search: str | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class NextEligibleVideos:
    limit: int = 20


VideoSelection: TypeAlias = SelectedVideos | ChannelVideos | FilteredVideos | NextEligibleVideos


class VideoSelectionPort(Protocol):
    async def select(self, selection: VideoSelection) -> list[VideoRecord]: ...
