from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class TranscriptMetadataResponse(BaseModel):
    id: int
    video_id: str = Field(alias="videoId")
    language: str
    language_code: str = Field(alias="languageCode")
    is_generated: bool = Field(alias="isGenerated")
    requested_languages: list[str] = Field(alias="requestedLanguages")
    preserve_formatting: bool = Field(alias="preserveFormatting")
    storage: TranscriptStorageResponse
    response_sha256: str = Field(alias="responseSha256")
    segment_count: int = Field(alias="segmentCount")
    text_length: int = Field(alias="textLength")
    notes: str | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class TranscriptMetadataUpdateRequest(BaseModel):
    notes: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def require_notes(self) -> Self:
        if "notes" not in self.model_fields_set:
            raise ValueError("notes must be provided.")
        return self


class DeleteResponse(BaseModel):
    success: bool
