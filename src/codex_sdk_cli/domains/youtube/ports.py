from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class YouTubeTranscriptSegment:
    text: str
    start: float
    duration: float


@dataclass(frozen=True, slots=True)
class YouTubeTranscriptFetchRequest:
    video_id: str
    languages: tuple[str, ...]
    preserve_formatting: bool


@dataclass(frozen=True, slots=True)
class YouTubeTranscriptFetchResult:
    video_id: str
    language: str
    language_code: str
    is_generated: bool
    segments: tuple[YouTubeTranscriptSegment, ...]


class YouTubeTranscriptPort(Protocol):
    async def fetch_transcript(
        self,
        request: YouTubeTranscriptFetchRequest,
    ) -> YouTubeTranscriptFetchResult:
        """Fetch a transcript for a YouTube video."""

