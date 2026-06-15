from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from codex_sdk_cli.domains.youtube.exceptions import InvalidYouTubeVideo
from codex_sdk_cli.domains.youtube.ports import (
    TranscriptStorageLocation,
    YouTubeTranscriptFetchRequest,
    YouTubeTranscriptFetchResult,
    YouTubeTranscriptPort,
    YouTubeTranscriptRecord,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptSegment,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageSaveRequest,
)
from codex_sdk_cli.domains.youtube.schemas import TranscriptRequest
from codex_sdk_cli.domains.youtube.use_cases import (
    FetchYouTubeTranscriptUseCase,
    build_transcript_object_name,
    normalize_video_id,
)

VIDEO_ID = "dQw4w9WgXcQ"


class FakeYouTubeTranscriptClient(YouTubeTranscriptPort):
    def __init__(self) -> None:
        self.request: YouTubeTranscriptFetchRequest | None = None

    async def fetch_transcript(
        self,
        request: YouTubeTranscriptFetchRequest,
    ) -> YouTubeTranscriptFetchResult:
        self.request = request
        return YouTubeTranscriptFetchResult(
            video_id=request.video_id,
            language="English",
            language_code=request.languages[0],
            is_generated=False,
            segments=(
                YouTubeTranscriptSegment(text="hello", start=0.0, duration=1.0),
                YouTubeTranscriptSegment(text="world", start=1.0, duration=1.0),
            ),
        )


class FakeYouTubeTranscriptStorage(YouTubeTranscriptStoragePort):
    def __init__(self) -> None:
        self.saves: list[YouTubeTranscriptStorageSaveRequest] = []

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
        return self.location_for(request.object_name)


class FakeYouTubeTranscriptRepository(YouTubeTranscriptRepositoryPort):
    def __init__(self) -> None:
        self.records: list[YouTubeTranscriptRecord] = []

    async def save_transcript_record(self, record: YouTubeTranscriptRecord) -> None:
        self.records.append(record)


@pytest.mark.parametrize(
    ("video", "expected"),
    [
        (f"https://www.youtube.com/watch?v={VIDEO_ID}&list=ignored", VIDEO_ID),
        (f"https://youtu.be/{VIDEO_ID}?t=10", VIDEO_ID),
        (f"https://www.youtube.com/shorts/{VIDEO_ID}?feature=share", VIDEO_ID),
        (f"https://www.youtube.com/embed/{VIDEO_ID}?start=3", VIDEO_ID),
        (f"www.youtube.com/watch?v={VIDEO_ID}", VIDEO_ID),
        (VIDEO_ID, VIDEO_ID),
    ],
)
def test_normalize_video_id_accepts_supported_inputs(video: str, expected: str) -> None:
    assert normalize_video_id(video) == expected


@pytest.mark.parametrize(
    "video",
    [
        "",
        "not-a-video!",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?list=missing-video",
        "https://www.youtube.com/shorts/too-short",
    ],
)
def test_normalize_video_id_rejects_invalid_inputs(video: str) -> None:
    with pytest.raises(InvalidYouTubeVideo):
        normalize_video_id(video)


def test_fetch_transcript_use_case_uses_fake_client_without_network() -> None:
    fake = FakeYouTubeTranscriptClient()
    storage = FakeYouTubeTranscriptStorage()
    repository = FakeYouTubeTranscriptRepository()
    use_case = FetchYouTubeTranscriptUseCase(
        fake,
        storage,
        repository,
        storage_prefix="youtube/transcripts",
        date_provider=lambda: date(2026, 6, 15),
    )

    response = asyncio.run(
        use_case.execute(
            TranscriptRequest(
                video=f"https://www.youtube.com/embed/{VIDEO_ID}",
                languages=[" en "],
                preserveFormatting=True,
            )
        )
    )
    expected_object_name = build_transcript_object_name(
        prefix="youtube/transcripts",
        storage_date=date(2026, 6, 15),
        video_id=VIDEO_ID,
        languages=("en",),
        preserve_formatting=True,
    )

    assert fake.request == YouTubeTranscriptFetchRequest(
        video_id=VIDEO_ID,
        languages=("en",),
        preserve_formatting=True,
    )
    assert response.text == "hello\nworld"
    assert response.language_code == "en"
    assert [segment.text for segment in response.segments] == ["hello", "world"]
    assert response.storage.bucket == "raw"
    assert response.storage.object_name == expected_object_name
    assert response.storage.uri == f"s3://raw/{expected_object_name}"
    assert storage.saves[0].object_name == expected_object_name
    assert json.loads(storage.saves[0].payload.decode("utf-8")) == response.model_dump(
        by_alias=True
    )
    assert repository.records == [
        YouTubeTranscriptRecord(
            video_id=VIDEO_ID,
            language="English",
            language_code="en",
            is_generated=False,
            requested_languages=("en",),
            preserve_formatting=True,
            storage_bucket="raw",
            storage_object_name=expected_object_name,
            storage_uri=f"s3://raw/{expected_object_name}",
            response_sha256=repository.records[0].response_sha256,
            segment_count=2,
            text_length=len("hello\nworld"),
        )
    ]
    assert len(repository.records[0].response_sha256) == 64
