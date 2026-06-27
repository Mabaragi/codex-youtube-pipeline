from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
class YouTubeTranscriptStorageReadRequest:
    object_name: str


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


@dataclass(frozen=True, slots=True)
class YouTubeTranscriptMetadataRecord:
    id: int
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
    notes: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class YouTubeTranscriptMetadataFilters:
    video_id: str | None = None
    language_code: str | None = None
    limit: int = 50
    offset: int = 0


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

    async def read_transcript(
        self,
        request: YouTubeTranscriptStorageReadRequest,
    ) -> bytes:
        """Read a stored transcript response JSON payload."""


class YouTubeTranscriptRepositoryPort(Protocol):
    async def save_transcript_record(
        self,
        record: YouTubeTranscriptRecord,
    ) -> YouTubeTranscriptMetadataRecord:
        """Persist transcript metadata after object storage succeeds."""

    async def find_transcript_metadata_for_request(
        self,
        *,
        video_id: str,
        requested_languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> YouTubeTranscriptMetadataRecord | None:
        """Return the latest metadata row for the exact transcript request."""

    async def list_transcript_metadata(
        self,
        filters: YouTubeTranscriptMetadataFilters,
    ) -> list[YouTubeTranscriptMetadataRecord]:
        """List stored transcript metadata rows."""

    async def get_transcript_metadata(
        self,
        transcript_id: int,
    ) -> YouTubeTranscriptMetadataRecord | None:
        """Return one stored transcript metadata row by ID."""

    async def update_transcript_notes(
        self,
        transcript_id: int,
        notes: str | None,
    ) -> YouTubeTranscriptMetadataRecord | None:
        """Update the operator notes for a stored transcript metadata row."""

    async def delete_transcript_metadata(self, transcript_id: int) -> bool:
        """Delete one stored transcript metadata row without deleting object storage."""
