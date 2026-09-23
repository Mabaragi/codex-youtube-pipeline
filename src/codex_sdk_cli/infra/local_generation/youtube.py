from __future__ import annotations

import httpx

from codex_sdk_cli.application.one_shot.ports import VideoMetadata
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptFetchRequest,
    YouTubeTranscriptFetchResult,
)
from codex_sdk_cli.infra.youtube_data.schemas import YouTubeVideosListResponse
from codex_sdk_cli.infra.youtube_transcripts.client import YouTubeTranscriptClient
from codex_sdk_cli.settings import CliSettings


class YouTubeSingleVideoLookup:
    def __init__(self, settings: CliSettings) -> None:
        self._settings = settings

    async def lookup(self, youtube_video_id: str) -> VideoMetadata:
        key = self._settings.youtube_data_api_key
        if key is None:
            raise RuntimeError("CODEX_CLI_YOUTUBE_DATA_API_KEY is required.")
        async with httpx.AsyncClient(timeout=self._settings.youtube_data_timeout_seconds) as client:
            response = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "snippet,contentDetails,status",
                    "id": youtube_video_id,
                    "key": key.get_secret_value(),
                },
            )
        response.raise_for_status()
        payload = YouTubeVideosListResponse.model_validate(response.json())
        if len(payload.items) != 1:
            raise LookupError("YouTube video was not found or is unavailable.")
        item = payload.items[0]
        snippet = item.snippet
        details = item.content_details
        if snippet is None or details is None or details.duration is None:
            raise ValueError("YouTube video metadata is incomplete.")
        if item.status is None or item.status.embeddable is not True:
            raise ValueError("YouTube video is not embeddable.")
        if item.status.privacy_status not in (None, "public"):
            raise ValueError("YouTube video is not public.")
        return VideoMetadata(
            youtube_video_id=item.youtube_video_id,
            title=snippet.title,
            description=snippet.description,
            published_at=snippet.published_at,
            duration=details.duration,
            duration_seconds=_duration_seconds(details.duration),
            thumbnail_url=snippet.thumbnail_url,
            channel_id=snippet.channel_id,
            channel_name=snippet.channel_title,
            is_embeddable=True,
        )


class YouTubeCaptionLookup:
    def __init__(self, settings: CliSettings) -> None:
        self._client = YouTubeTranscriptClient.from_settings(settings)

    async def fetch(
        self, youtube_video_id: str, languages: tuple[str, ...]
    ) -> YouTubeTranscriptFetchResult:
        return await self._client.fetch_transcript(
            YouTubeTranscriptFetchRequest(
                video_id=youtube_video_id,
                languages=languages,
                preserve_formatting=False,
            )
        )


def _duration_seconds(value: str) -> int:
    import re

    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if match is None:
        raise ValueError("YouTube video duration is invalid.")
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    duration = days * 86400 + hours * 3600 + minutes * 60 + seconds
    if duration <= 0:
        raise ValueError("YouTube video duration must be positive.")
    return duration
