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


@dataclass(frozen=True, slots=True)
class TranscriptStorageLocation:
    bucket: str
    object_name: str
    uri: str


@dataclass(frozen=True, slots=True)
class YouTubeTranscriptStorageSaveRequest:
    object_name: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class YouTubeTranscriptRecord:
    video_id: str
    language: str
    language_code: str
    is_generated: bool
    requested_languages: tuple[str, ...]
    preserve_formatting: bool
    storage_bucket: str
    storage_object_name: str
    storage_uri: str
    response_sha256: str
    segment_count: int
    text_length: int


class YouTubeTranscriptPort(Protocol):
    async def fetch_transcript(
        self,
        request: YouTubeTranscriptFetchRequest,
    ) -> YouTubeTranscriptFetchResult:
        """Fetch a transcript for a YouTube video."""


class YouTubeTranscriptStoragePort(Protocol):
    def location_for(self, object_name: str) -> TranscriptStorageLocation:
        """Return the object storage location for an object key."""

    async def save_transcript(
        self,
        request: YouTubeTranscriptStorageSaveRequest,
    ) -> TranscriptStorageLocation:
        """Persist a transcript response JSON payload."""


class YouTubeTranscriptRepositoryPort(Protocol):
    async def save_transcript_record(self, record: YouTubeTranscriptRecord) -> None:
        """Persist transcript metadata after object storage succeeds."""
