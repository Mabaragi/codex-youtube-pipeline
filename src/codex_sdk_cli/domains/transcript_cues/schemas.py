from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TranscriptCueResponse(BaseModel):
    id: int
    transcript_id: int = Field(alias="transcriptId")
    cue_id: str = Field(alias="cueId")
    cue_index: int = Field(alias="cueIndex")
    text: str
    start_ms: int = Field(alias="startMs")
    end_ms: int = Field(alias="endMs")
    duration_ms: int = Field(alias="durationMs")
    source_segment_index: int = Field(alias="sourceSegmentIndex")
    source_job_id: int | None = Field(alias="sourceJobId")
    source_job_attempt_id: int | None = Field(alias="sourceJobAttemptId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class TranscriptCueListResponse(BaseModel):
    transcript_id: int = Field(alias="transcriptId")
    cue_count: int = Field(alias="cueCount")
    items: list[TranscriptCueResponse]

    model_config = ConfigDict(populate_by_name=True)


class PromptCueResponse(BaseModel):
    cue_id: str = Field(alias="cueId")
    cue_index: int = Field(alias="cueIndex")
    text: str

    model_config = ConfigDict(populate_by_name=True)


class TranscriptPromptCuesResponse(BaseModel):
    transcript_id: int = Field(alias="transcriptId")
    cue_count: int = Field(alias="cueCount")
    prompt_text: str = Field(alias="promptText")
    cues: list[PromptCueResponse]

    model_config = ConfigDict(populate_by_name=True)


class TranscriptCueGenerateResponse(BaseModel):
    transcript_id: int = Field(alias="transcriptId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    job_id: int = Field(alias="jobId")
    job_attempt_id: int = Field(alias="jobAttemptId")
    cue_count: int = Field(alias="cueCount")
    first_cue_id: str | None = Field(alias="firstCueId")
    last_cue_id: str | None = Field(alias="lastCueId")

    model_config = ConfigDict(populate_by_name=True)
