from __future__ import annotations

from collections.abc import Iterable

from fastapi.concurrency import run_in_threadpool
from typing_extensions import override
from youtube_transcript_api import (
    AgeRestricted,
    FetchedTranscript,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeRequestFailed,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)
from youtube_transcript_api.proxies import GenericProxyConfig

from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    InvalidYouTubeVideo,
    YouTubeTranscriptForbidden,
    YouTubeTranscriptNotFound,
    YouTubeTranscriptUpstreamError,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptFetchRequest,
    YouTubeTranscriptFetchResult,
    YouTubeTranscriptPort,
    YouTubeTranscriptSegment,
)
from codex_sdk_cli.settings import CliSettings


class YouTubeTranscriptClient(YouTubeTranscriptPort):
    def __init__(self, api: YouTubeTranscriptApi) -> None:
        self._api = api

    @classmethod
    def from_settings(cls, settings: CliSettings) -> YouTubeTranscriptClient:
        proxy_config = None
        if settings.youtube_http_proxy or settings.youtube_https_proxy:
            proxy_config = GenericProxyConfig(
                http_url=settings.youtube_http_proxy,
                https_url=settings.youtube_https_proxy,
            )
        return cls(YouTubeTranscriptApi(proxy_config=proxy_config))

    @override
    async def fetch_transcript(
        self,
        request: YouTubeTranscriptFetchRequest,
    ) -> YouTubeTranscriptFetchResult:
        try:
            transcript = await run_in_threadpool(
                self._fetch_sync,
                request.video_id,
                request.languages,
                request.preserve_formatting,
            )
        except InvalidVideoId as exc:
            raise InvalidYouTubeVideo("Video must be a valid YouTube video ID.") from exc
        except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, VideoUnplayable) as exc:
            raise YouTubeTranscriptNotFound(
                "No retrievable transcript was found for this YouTube video."
            ) from exc
        except AgeRestricted as exc:
            raise YouTubeTranscriptForbidden(
                "This YouTube video is age-restricted and cannot be transcribed anonymously."
            ) from exc
        except (RequestBlocked, IpBlocked, YouTubeRequestFailed) as exc:
            raise YouTubeTranscriptUpstreamError(
                "YouTube transcript request was blocked or failed upstream."
            ) from exc
        except YouTubeTranscriptApiException as exc:
            raise YouTubeTranscriptUpstreamError("YouTube transcript request failed.") from exc

        return YouTubeTranscriptFetchResult(
            video_id=transcript.video_id,
            language=transcript.language,
            language_code=transcript.language_code,
            is_generated=transcript.is_generated,
            segments=tuple(
                YouTubeTranscriptSegment(
                    text=snippet.text,
                    start=snippet.start,
                    duration=snippet.duration,
                )
                for snippet in transcript
            ),
        )

    def _fetch_sync(
        self,
        video_id: str,
        languages: Iterable[str],
        preserve_formatting: bool,
    ) -> FetchedTranscript:
        return self._api.fetch(
            video_id,
            languages=languages,
            preserve_formatting=preserve_formatting,
        )
