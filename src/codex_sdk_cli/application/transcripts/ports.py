from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import Protocol


@dataclass(frozen=True, slots=True)
class StoredTranscript:
    transcript_id: int
    youtube_video_id: str
    language_code: str
    response_sha256: str
    reused_existing: bool = False


@dataclass(frozen=True, slots=True)
class GeneratedCues:
    transcript_id: int
    cue_count: int
    first_cue_id: str | None
    last_cue_id: str | None


class TranscriptFetcherPort(Protocol):
    async def fetch(
        self,
        *,
        youtube_video_id: str,
        languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> StoredTranscript | None: ...


class TranscriptMetadataReaderPort(Protocol):
    async def get(self, transcript_id: int) -> StoredTranscript | None: ...

    async def find_for_request(
        self,
        *,
        youtube_video_id: str,
        requested_languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> StoredTranscript | None: ...


class TranscriptCueGeneratorPort(Protocol):
    async def generate(
        self,
        *,
        transcript_id: int,
        work_item_id: int,
        work_attempt_id: int,
    ) -> GeneratedCues: ...
