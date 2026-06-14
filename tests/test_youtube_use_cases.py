from __future__ import annotations

import asyncio

import pytest

from codex_sdk_cli.domains.youtube.exceptions import InvalidYouTubeVideo
from codex_sdk_cli.domains.youtube.ports import (
    YouTubeTranscriptFetchRequest,
    YouTubeTranscriptFetchResult,
    YouTubeTranscriptPort,
    YouTubeTranscriptSegment,
)
from codex_sdk_cli.domains.youtube.schemas import TranscriptRequest
from codex_sdk_cli.domains.youtube.use_cases import (
    FetchYouTubeTranscriptUseCase,
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
    use_case = FetchYouTubeTranscriptUseCase(fake)

    response = asyncio.run(
        use_case.execute(
            TranscriptRequest(
                video=f"https://www.youtube.com/embed/{VIDEO_ID}",
                languages=[" en "],
                preserveFormatting=True,
            )
        )
    )

    assert fake.request == YouTubeTranscriptFetchRequest(
        video_id=VIDEO_ID,
        languages=("en",),
        preserve_formatting=True,
    )
    assert response.text == "hello\nworld"
    assert response.language_code == "en"
    assert [segment.text for segment in response.segments] == ["hello", "world"]
