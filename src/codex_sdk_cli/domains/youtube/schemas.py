from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TranscriptRequest(BaseModel):
    video: str = Field(min_length=1)
    languages: list[str] | None = None
    preserve_formatting: bool = Field(default=False, alias="preserveFormatting")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class TranscriptSegmentResponse(BaseModel):
    text: str
    start: float
    duration: float


class TranscriptStorageResponse(BaseModel):
    bucket: str
    object_name: str = Field(alias="objectName")
    uri: str

    model_config = ConfigDict(populate_by_name=True)


class TranscriptResponse(BaseModel):
    video_id: str = Field(alias="videoId")
    language: str
    language_code: str = Field(alias="languageCode")
    is_generated: bool = Field(alias="isGenerated")
    text: str
    segments: list[TranscriptSegmentResponse]
    storage: TranscriptStorageResponse

    model_config = ConfigDict(populate_by_name=True)
