from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AsrTranscriptResult:
    transcript_id: int
    segment_count: int
    response_sha256: str
    storage_object_name: str
    device: str
    compute_type: str
    duration_seconds: float
    elapsed_seconds: float


class AsrTranscriberPort(Protocol):
    async def transcribe(
        self,
        *,
        work_item_id: int,
        youtube_video_id: str,
        model: str,
        language: str,
        device: str,
        compute_type: str,
        chunk_minutes: int,
        overlap_seconds: int,
        beam_size: int,
        vad_filter: bool,
    ) -> AsrTranscriptResult: ...
