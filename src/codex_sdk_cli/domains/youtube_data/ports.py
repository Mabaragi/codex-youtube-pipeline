from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class YouTubeChannelResolution:
    handle: str
    youtube_channel_id: str
    title: str
    source_api_call_id: int


@dataclass(frozen=True, slots=True)
class YouTubeVideoSearchPage:
    youtube_video_ids: tuple[str, ...]
    next_page_token: str | None
    source_api_call_id: int


@dataclass(frozen=True, slots=True)
class YouTubeVideoDetails:
    youtube_video_id: str
    title: str
    description: str
    published_at: datetime
    duration: str | None
    privacy_status: str | None
    upload_status: str | None
    live_broadcast_content: str | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    thumbnail_url: str | None
    source_api_call_id: int


@dataclass(frozen=True, slots=True)
class YouTubeVideoDetailsBatch:
    videos: tuple[YouTubeVideoDetails, ...]
    source_api_call_id: int


class YouTubeDataClientPort(Protocol):
    async def resolve_youtube_channel_by_handle(
        self,
        handle: str,
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeChannelResolution:
        """Resolve YouTube channel metadata from a public handle."""

    async def search_channel_videos(
        self,
        youtube_channel_id: str,
        *,
        page_token: str | None = None,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoSearchPage:
        """Search one page of channel videos in newest-first order."""

    async def get_video_details(
        self,
        youtube_video_ids: tuple[str, ...],
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoDetailsBatch:
        """Fetch normalized detail projections for YouTube video IDs."""
