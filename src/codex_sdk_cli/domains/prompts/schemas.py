from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .constants import PromptKey, PromptSource, PromptStatus


class PromptVersionCreateRequest(BaseModel):
    version_label: str = Field(alias="versionLabel", min_length=1, max_length=128)
    body: str = Field(min_length=1)
    source_note: str | None = Field(default=None, alias="sourceNote", max_length=4000)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PromptVersionUpdateRequest(BaseModel):
    body: str | None = Field(default=None, min_length=1)
    source_note: str | None = Field(default=None, alias="sourceNote", max_length=4000)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PromptVersionResponse(BaseModel):
    id: int
    prompt_key: PromptKey = Field(alias="promptKey")
    version_label: str = Field(alias="versionLabel")
    body_sha256: str = Field(alias="bodySha256")
    status: PromptStatus
    source_note: str | None = Field(alias="sourceNote")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    published_at: datetime | None = Field(alias="publishedAt")
    archived_at: datetime | None = Field(alias="archivedAt")
    is_active: bool = Field(alias="isActive")

    model_config = ConfigDict(populate_by_name=True)


class PromptBodyResponse(BaseModel):
    key: PromptKey
    version_id: int | None = Field(alias="versionId")
    version_label: str = Field(alias="versionLabel")
    body: str
    body_sha256: str = Field(alias="bodySha256")
    source: PromptSource

    model_config = ConfigDict(populate_by_name=True)


class PromptSummaryResponse(BaseModel):
    key: PromptKey
    active: PromptBodyResponse
    version_count: int = Field(alias="versionCount")

    model_config = ConfigDict(populate_by_name=True)


class PromptDetailResponse(BaseModel):
    key: PromptKey
    active: PromptBodyResponse
    versions: list[PromptVersionResponse]

    model_config = ConfigDict(populate_by_name=True)


class PromptCacheInvalidateRequest(BaseModel):
    prompt_key: PromptKey | None = Field(default=None, alias="promptKey")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PromptCacheInvalidateResponse(BaseModel):
    invalidated_count: int = Field(alias="invalidatedCount")

    model_config = ConfigDict(populate_by_name=True)
