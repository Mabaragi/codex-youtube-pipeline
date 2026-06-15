from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

from .exceptions import InvalidYouTubeVideo
from .ports import (
    TranscriptStorageLocation,
    YouTubeTranscriptFetchRequest,
    YouTubeTranscriptPort,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageSaveRequest,
)
from .schemas import (
    TranscriptRequest,
    TranscriptResponse,
    TranscriptSegmentResponse,
    TranscriptStorageResponse,
)

DEFAULT_TRANSCRIPT_LANGUAGES = ("ko", "en")
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
SCHEMELESS_YOUTUBE_PREFIXES = (
    "youtube.com/",
    "www.youtube.com/",
    "m.youtube.com/",
    "music.youtube.com/",
    "youtube-nocookie.com/",
    "www.youtube-nocookie.com/",
    "youtu.be/",
    "www.youtu.be/",
)


class FetchYouTubeTranscriptUseCase:
    def __init__(
        self,
        client: YouTubeTranscriptPort,
        storage: YouTubeTranscriptStoragePort,
        *,
        storage_prefix: str = "youtube/transcripts",
        date_provider: Callable[[], date] | None = None,
    ) -> None:
        self._client = client
        self._storage = storage
        self._storage_prefix = storage_prefix
        self._date_provider = date_provider or _utc_today

    async def execute(self, request: TranscriptRequest) -> TranscriptResponse:
        video_id = normalize_video_id(request.video)
        languages = normalize_languages(request.languages)
        result = await self._client.fetch_transcript(
            YouTubeTranscriptFetchRequest(
                video_id=video_id,
                languages=languages,
                preserve_formatting=request.preserve_formatting,
            )
        )
        segments = [
            TranscriptSegmentResponse(
                text=segment.text,
                start=segment.start,
                duration=segment.duration,
            )
            for segment in result.segments
        ]
        object_name = build_transcript_object_name(
            prefix=self._storage_prefix,
            storage_date=self._date_provider(),
            video_id=video_id,
            languages=languages,
            preserve_formatting=request.preserve_formatting,
        )
        location = self._storage.location_for(object_name)
        response = TranscriptResponse(
            videoId=result.video_id,
            language=result.language,
            languageCode=result.language_code,
            isGenerated=result.is_generated,
            text="\n".join(segment.text for segment in result.segments),
            segments=segments,
            storage=_storage_response(location),
        )
        await self._storage.save_transcript(
            YouTubeTranscriptStorageSaveRequest(
                object_name=object_name,
                payload=response.model_dump_json(by_alias=True).encode("utf-8"),
            )
        )
        return response


def normalize_video_id(video: str) -> str:
    value = video.strip()
    if not value:
        raise InvalidYouTubeVideo("Video must be a YouTube URL or video ID.")
    if VIDEO_ID_PATTERN.fullmatch(value):
        return value

    parsed = urlparse(_with_scheme_for_youtube_url(value))
    host = parsed.netloc.lower().split(":", maxsplit=1)[0]
    video_id: str | None = None

    if host in YOUTUBE_SHORT_HOSTS:
        video_id = _first_path_part(parsed.path)
    elif host in YOUTUBE_HOSTS:
        path_parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed"}:
            video_id = path_parts[1]
    else:
        raise InvalidYouTubeVideo("Video must be a supported YouTube URL or video ID.")

    if video_id is None or VIDEO_ID_PATTERN.fullmatch(video_id) is None:
        raise InvalidYouTubeVideo("Video must be a valid 11-character YouTube video ID.")

    return video_id


def normalize_languages(languages: list[str] | None) -> tuple[str, ...]:
    if languages is None:
        return DEFAULT_TRANSCRIPT_LANGUAGES

    normalized = tuple(language.strip() for language in languages)
    if not normalized:
        raise InvalidYouTubeVideo("At least one transcript language must be requested.")
    if any(not language for language in normalized):
        raise InvalidYouTubeVideo("Transcript language codes cannot be blank.")
    return normalized


def build_transcript_object_name(
    *,
    prefix: str,
    storage_date: date,
    video_id: str,
    languages: tuple[str, ...],
    preserve_formatting: bool,
) -> str:
    normalized_prefix = prefix.strip("/")
    date_path = storage_date.strftime("%Y/%m/%d")
    request_hash = _transcript_request_hash(video_id, languages, preserve_formatting)
    file_name = f"{video_id}-{request_hash}.json"
    if not normalized_prefix:
        return f"{date_path}/{file_name}"
    return f"{normalized_prefix}/{date_path}/{file_name}"


def _transcript_request_hash(
    video_id: str,
    languages: tuple[str, ...],
    preserve_formatting: bool,
) -> str:
    payload = {
        "languages": list(languages),
        "preserveFormatting": preserve_formatting,
        "videoId": video_id,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _storage_response(location: TranscriptStorageLocation) -> TranscriptStorageResponse:
    return TranscriptStorageResponse(
        bucket=location.bucket,
        objectName=location.object_name,
        uri=location.uri,
    )


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _with_scheme_for_youtube_url(value: str) -> str:
    lower_value = value.lower()
    if "://" in value:
        return value
    if lower_value.startswith(SCHEMELESS_YOUTUBE_PREFIXES):
        return f"https://{value}"
    return value


def _first_path_part(path: str) -> str | None:
    for part in path.split("/"):
        if part:
            return part
    return None
