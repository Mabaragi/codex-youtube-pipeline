from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

JsonObject = dict[str, object]


@dataclass(frozen=True, slots=True)
class TranscriptCueCreate:
    transcript_id: int
    cue_id: str
    cue_index: int
    text: str
    start_ms: int
    end_ms: int
    duration_ms: int
    source_segment_index: int
    source_job_id: int | None
    source_job_attempt_id: int | None


@dataclass(frozen=True, slots=True)
class TranscriptCueRecord:
    id: int
    transcript_id: int
    cue_id: str
    cue_index: int
    text: str
    start_ms: int
    end_ms: int
    duration_ms: int
    source_segment_index: int
    source_job_id: int | None
    source_job_attempt_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TranscriptCueSummaryRecord:
    transcript_id: int
    cue_count: int
    first_cue_id: str | None
    last_cue_id: str | None
    source_job_id: int | None


class TranscriptCueRepositoryPort(Protocol):
    async def replace_cues(
        self,
        transcript_id: int,
        cues: list[TranscriptCueCreate],
    ) -> list[TranscriptCueRecord]:
        """Replace all cues for one transcript in a single persistence boundary."""

    async def list_cues(self, transcript_id: int) -> list[TranscriptCueRecord]:
        """Return cues for one transcript ordered by cue_index."""

    async def summarize_cues(self, transcript_id: int) -> TranscriptCueSummaryRecord:
        """Return cue count and edge cue IDs for one transcript."""
