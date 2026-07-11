from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .ports import TranscriptCueCreate


@dataclass(frozen=True, slots=True)
class TranscriptCueSegmentInput:
    text: str
    start_seconds: float
    duration_seconds: float


def build_transcript_cues(
    transcript_id: int,
    segments: Iterable[TranscriptCueSegmentInput],
    *,
    source_job_id: int | None = None,
    source_job_attempt_id: int | None = None,
    source_work_item_id: int | None = None,
    source_work_attempt_id: int | None = None,
) -> list[TranscriptCueCreate]:
    cues: list[TranscriptCueCreate] = []
    for segment_index, segment in enumerate(segments):
        cue_index = segment_index + 1
        start_ms = _seconds_to_ms(segment.start_seconds)
        duration_ms = max(0, _seconds_to_ms(segment.duration_seconds))
        cues.append(
            TranscriptCueCreate(
                transcript_id=transcript_id,
                cue_id=f"tr{transcript_id}-c{cue_index:06d}",
                cue_index=cue_index,
                text=segment.text,
                start_ms=start_ms,
                end_ms=max(start_ms, start_ms + duration_ms),
                duration_ms=duration_ms,
                source_segment_index=segment_index,
                source_job_id=source_job_id,
                source_job_attempt_id=source_job_attempt_id,
                source_work_item_id=source_work_item_id,
                source_work_attempt_id=source_work_attempt_id,
            )
        )
    return cues


def _seconds_to_ms(value: float) -> int:
    return round(value * 1000)
