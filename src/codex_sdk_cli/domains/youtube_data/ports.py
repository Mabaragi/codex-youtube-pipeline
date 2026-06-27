from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class YouTubeChannelResolution:
    handle: str
    youtube_channel_id: str
    title: str
    uploads_playlist_id: str
    source_api_call_id: int


@dataclass(frozen=True, slots=True)
class YouTubeChannelUploadsPlaylist:
    youtube_channel_id: str
    uploads_playlist_id: str
    source_api_call_id: int


@dataclass(frozen=True, slots=True)
class YouTubeVideoListing:
    youtube_video_id: str
    title: str
    description: str
    published_at: datetime
    thumbnail_url: str | None
    source_api_call_id: int


@dataclass(frozen=True, slots=True)
class YouTubeVideoListingPage:
    videos: tuple[YouTubeVideoListing, ...]
    next_page_token: str | None
    source_api_call_id: int


@dataclass(frozen=True, slots=True)
class YouTubeVideoDetails:
    youtube_video_id: str
    duration: str | None
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

    async def get_channel_uploads_playlist(
        self,
        youtube_channel_id: str,
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeChannelUploadsPlaylist:
        """Fetch the stable uploads playlist ID for one YouTube channel."""

    async def list_upload_playlist_videos(
        self,
        uploads_playlist_id: str,
        *,
        page_token: str | None = None,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoListingPage:
        """List one page of uploaded videos from a channel uploads playlist."""

    async def get_video_details(
        self,
        youtube_video_ids: tuple[str, ...],
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoDetailsBatch:
        """Fetch normalized detail projections for YouTube video IDs."""
