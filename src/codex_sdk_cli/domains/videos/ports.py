from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VideoCreate:
    channel_id: int
    youtube_video_id: str
    title: str
    description: str
    published_at: datetime
    duration: str | None
    thumbnail_url: str | None
    source_listing_api_call_id: int
    source_details_api_call_id: int
    source_job_id: int
    is_embeddable: bool | None = None
    embed_status_checked_at: datetime | None = None
    source_embed_status_api_call_id: int | None = None


@dataclass(frozen=True, slots=True)
class VideoRecord:
    id: int
    channel_id: int
    youtube_video_id: str
    title: str
    description: str
    published_at: datetime
    duration: str | None
    thumbnail_url: str | None
    source_listing_api_call_id: int | None
    source_details_api_call_id: int | None
    source_job_id: int | None
    created_at: datetime
    updated_at: datetime
    is_embeddable: bool | None = None
    embed_status_checked_at: datetime | None = None
    source_embed_status_api_call_id: int | None = None


class VideoRepositoryPort(Protocol):
    async def get_video(self, video_id: int) -> VideoRecord | None:
        """Return one stored video by local ID."""

    async def get_video_by_youtube_video_id(
        self,
        youtube_video_id: str,
    ) -> VideoRecord | None:
        """Return one stored video by external YouTube video ID."""

    async def list_all_videos(self) -> list[VideoRecord]:
        """List all stored videos."""

    async def list_videos(self, *, channel_id: int) -> list[VideoRecord]:
        """List stored videos for one channel."""

    async def list_videos_for_embed_status_refresh(
        self,
        *,
        video_ids: tuple[int, ...] | None,
        limit: int,
    ) -> list[VideoRecord]:
        """List stored videos whose embed status should be refreshed."""

    async def find_existing_youtube_video_id(
        self,
        *,
        channel_id: int,
        youtube_video_ids: tuple[str, ...],
    ) -> str | None:
        """Return the first already stored video ID for a channel, preserving input order."""

    async def create_videos(self, videos: list[VideoCreate]) -> list[VideoRecord]:
        """Create normalized video rows after all upstream API calls succeed."""

    async def update_embed_status(
        self,
        video_id: int,
        *,
        is_embeddable: bool | None,
        checked_at: datetime,
        source_api_call_id: int | None,
    ) -> VideoRecord:
        """Update YouTube embed status metadata for one stored video."""
