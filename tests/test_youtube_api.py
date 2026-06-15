from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_youtube_transcript_client,
    get_youtube_transcript_storage,
)
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.youtube.exceptions import (
    YouTubeDomainError,
    YouTubeTranscriptForbidden,
    YouTubeTranscriptNotFound,
    YouTubeTranscriptStorageError,
    YouTubeTranscriptUpstreamError,
)
from codex_sdk_cli.domains.youtube.ports import (
    TranscriptStorageLocation,
    YouTubeTranscriptFetchRequest,
    YouTubeTranscriptFetchResult,
    YouTubeTranscriptPort,
    YouTubeTranscriptSegment,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageSaveRequest,
)

VIDEO_ID = "dQw4w9WgXcQ"


class FakeYouTubeTranscriptClient(YouTubeTranscriptPort):
    def __init__(self) -> None:
        self.requests: list[YouTubeTranscriptFetchRequest] = []
        self.error: YouTubeDomainError | None = None

    async def fetch_transcript(
        self,
        request: YouTubeTranscriptFetchRequest,
    ) -> YouTubeTranscriptFetchResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return YouTubeTranscriptFetchResult(
            video_id=request.video_id,
            language="Korean",
            language_code=request.languages[0],
            is_generated=True,
            segments=(
                YouTubeTranscriptSegment(text="first line", start=0.0, duration=1.25),
                YouTubeTranscriptSegment(text="second line", start=1.25, duration=2.5),
            ),
        )


class FakeYouTubeTranscriptStorage(YouTubeTranscriptStoragePort):
    def __init__(self) -> None:
        self.saves: list[YouTubeTranscriptStorageSaveRequest] = []
        self.error: YouTubeTranscriptStorageError | None = None

    def location_for(self, object_name: str) -> TranscriptStorageLocation:
        return TranscriptStorageLocation(
            bucket="raw",
            object_name=object_name,
            uri=f"s3://raw/{object_name}",
        )

    async def save_transcript(
        self,
        request: YouTubeTranscriptStorageSaveRequest,
    ) -> TranscriptStorageLocation:
        self.saves.append(request)
        if self.error is not None:
            raise self.error
        return self.location_for(request.object_name)


def test_transcript_endpoint_normalizes_url_and_raw_video_id() -> None:
    fake = FakeYouTubeTranscriptClient()

    url_response = asyncio.run(
        _request(
            fake,
            json={"video": f"https://www.youtube.com/watch?v={VIDEO_ID}&list=ignored"},
        )
    )
    raw_response = asyncio.run(_request(fake, json={"video": VIDEO_ID}))

    assert url_response["videoId"] == VIDEO_ID
    assert raw_response["videoId"] == VIDEO_ID
    assert [request.video_id for request in fake.requests] == [VIDEO_ID, VIDEO_ID]


def test_transcript_endpoint_applies_default_languages_and_formatting() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(_request(fake, json={"video": f"https://youtu.be/{VIDEO_ID}?t=10"}))

    assert response["languageCode"] == "ko"
    assert fake.requests == [
        YouTubeTranscriptFetchRequest(
            video_id=VIDEO_ID,
            languages=("ko", "en"),
            preserve_formatting=False,
        )
    ]


def test_transcript_endpoint_passes_custom_languages_and_formatting() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            json={
                "video": f"https://www.youtube.com/shorts/{VIDEO_ID}?feature=share",
                "languages": ["ja", "en"],
                "preserveFormatting": True,
            },
        )
    )

    assert response["languageCode"] == "ja"
    assert fake.requests == [
        YouTubeTranscriptFetchRequest(
            video_id=VIDEO_ID,
            languages=("ja", "en"),
            preserve_formatting=True,
        )
    ]


def test_transcript_endpoint_returns_text_segments_and_camel_case_metadata() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(fake, json={"video": f"https://www.youtube.com/embed/{VIDEO_ID}"})
    )

    assert response["videoId"] == VIDEO_ID
    assert response["language"] == "Korean"
    assert response["languageCode"] == "ko"
    assert response["isGenerated"] is True
    assert response["text"] == "first line\nsecond line"
    assert response["segments"] == [
        {"text": "first line", "start": 0.0, "duration": 1.25},
        {"text": "second line", "start": 1.25, "duration": 2.5},
    ]
    assert response["storage"]["bucket"] == "raw"
    assert response["storage"]["objectName"].startswith("youtube/transcripts/")
    assert response["storage"]["objectName"].endswith(".json")
    assert response["storage"]["uri"] == f"s3://raw/{response['storage']['objectName']}"


def test_transcript_endpoint_rejects_extra_fields() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            json={"video": VIDEO_ID, "format": "srt"},
            expected_status=422,
        )
    )

    assert fake.requests == []
    assert response["detail"][0]["type"] == "extra_forbidden"
    assert response["detail"][0]["loc"] == ["body", "format"]


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (YouTubeTranscriptNotFound("No transcript."), 404),
        (YouTubeTranscriptForbidden("Age restricted."), 403),
        (YouTubeTranscriptUpstreamError("Blocked upstream."), 502),
    ],
)
def test_transcript_endpoint_maps_domain_errors(
    error: YouTubeDomainError,
    expected_status: int,
) -> None:
    fake = FakeYouTubeTranscriptClient()
    fake.error = error

    response = asyncio.run(
        _request(fake, json={"video": VIDEO_ID}, expected_status=expected_status)
    )

    assert response == {"detail": error.message}


def test_transcript_endpoint_maps_invalid_domain_to_bad_request() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            json={"video": f"https://example.com/watch?v={VIDEO_ID}"},
            expected_status=400,
        )
    )

    assert fake.requests == []
    assert response == {"detail": "Video must be a supported YouTube URL or video ID."}


def test_transcript_endpoint_maps_storage_errors_to_unavailable() -> None:
    fake = FakeYouTubeTranscriptClient()
    storage = FakeYouTubeTranscriptStorage()
    storage.error = YouTubeTranscriptStorageError("Storage unavailable.")

    response = asyncio.run(
        _request(
            fake,
            youtube_storage=storage,
            json={"video": VIDEO_ID},
            expected_status=503,
        )
    )

    assert response == {"detail": "Storage unavailable."}
    assert len(fake.requests) == 1
    assert len(storage.saves) == 1


def test_transcript_endpoint_does_not_store_when_fetch_fails() -> None:
    fake = FakeYouTubeTranscriptClient()
    fake.error = YouTubeTranscriptUpstreamError("Blocked upstream.")
    storage = FakeYouTubeTranscriptStorage()

    response = asyncio.run(
        _request(
            fake,
            youtube_storage=storage,
            json={"video": VIDEO_ID},
            expected_status=502,
        )
    )

    assert response == {"detail": "Blocked upstream."}
    assert storage.saves == []


async def _request(
    youtube_client: FakeYouTubeTranscriptClient,
    *,
    youtube_storage: FakeYouTubeTranscriptStorage | None = None,
    json: dict[str, Any],
    expected_status: int = 200,
) -> Any:
    app = create_app()
    storage = youtube_storage or FakeYouTubeTranscriptStorage()
    app.dependency_overrides[get_youtube_transcript_client] = lambda: youtube_client
    app.dependency_overrides[get_youtube_transcript_storage] = lambda: storage

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/youtube/transcripts", json=json)

    assert response.status_code == expected_status, response.text
    return response.json()
