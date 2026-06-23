from __future__ import annotations

from datetime import datetime
from typing import Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ports import AliasKind, ApplyScope, Certainty, PromptPolicy


class DomainEntryTypeCreateRequest(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    sort_order: int = Field(default=100, alias="sortOrder", ge=0)
    is_system: bool = Field(default=False, alias="isSystem")

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class DomainEntryTypeResponse(BaseModel):
    type_id: int = Field(alias="typeId")
    key: str
    label: str
    description: str | None
    sort_order: int = Field(alias="sortOrder")
    is_system: bool = Field(alias="isSystem")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class DomainEntryAliasCreateRequest(BaseModel):
    surface_form: str = Field(alias="surfaceForm", min_length=1, max_length=255)
    alias_kind: AliasKind = Field(default=cast(AliasKind, "ALIAS"), alias="aliasKind")
    certainty: Certainty = "MEDIUM"
    apply_scope: ApplyScope = Field(default="SEARCH_ONLY", alias="applyScope")
    language_code: str | None = Field(default=None, alias="languageCode", max_length=16)
    note: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class DomainEntryAliasUpdateRequest(BaseModel):
    surface_form: str | None = Field(
        default=None,
        alias="surfaceForm",
        min_length=1,
        max_length=255,
    )
    alias_kind: AliasKind | None = Field(default=None, alias="aliasKind")
    certainty: Certainty | None = None
    apply_scope: ApplyScope | None = Field(default=None, alias="applyScope")
    language_code: str | None = Field(default=None, alias="languageCode", max_length=16)
    note: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    @model_validator(mode="after")
    def require_any_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        return self


class DomainEntryStreamerLinkRequest(BaseModel):
    streamer_id: int = Field(alias="streamerId", ge=1)
    relevance: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class DomainEntryCreateRequest(BaseModel):
    type_id: int | None = Field(default=None, alias="typeId", ge=1)
    type_key: str | None = Field(default=None, alias="typeKey", min_length=1, max_length=128)
    type_label: str | None = Field(
        default=None,
        alias="typeLabel",
        min_length=1,
        max_length=255,
    )
    canonical_name: str = Field(alias="canonicalName", min_length=1, max_length=255)
    display_name: str | None = Field(
        default=None,
        alias="displayName",
        max_length=255,
    )
    disambiguation: str | None = Field(default=None, max_length=500)
    detail: str | None = Field(default=None, max_length=10_000)
    prompt_policy: PromptPolicy = Field(default="AUTO_ON_MATCH", alias="promptPolicy")
    priority: int = Field(default=50, ge=0, le=1000)
    is_active: bool = Field(default=True, alias="isActive")
    source_note: str | None = Field(default=None, alias="sourceNote", max_length=2000)
    streamer_ids: list[int] = Field(default_factory=list, alias="streamerIds")
    aliases: list[DomainEntryAliasCreateRequest] = Field(default_factory=list)

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    @model_validator(mode="after")
    def require_type_reference(self) -> Self:
        if self.type_id is None and self.type_label is None and self.type_key is None:
            raise ValueError("typeId or typeLabel/typeKey is required.")
        return self


class DomainEntryUpdateRequest(BaseModel):
    type_id: int | None = Field(default=None, alias="typeId", ge=1)
    type_key: str | None = Field(default=None, alias="typeKey", min_length=1, max_length=128)
    type_label: str | None = Field(
        default=None,
        alias="typeLabel",
        min_length=1,
        max_length=255,
    )
    canonical_name: str | None = Field(
        default=None,
        alias="canonicalName",
        min_length=1,
        max_length=255,
    )
    display_name: str | None = Field(default=None, alias="displayName", max_length=255)
    disambiguation: str | None = Field(default=None, max_length=500)
    detail: str | None = Field(default=None, max_length=10_000)
    prompt_policy: PromptPolicy | None = Field(default=None, alias="promptPolicy")
    priority: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = Field(default=None, alias="isActive")
    source_note: str | None = Field(default=None, alias="sourceNote", max_length=2000)

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    @model_validator(mode="after")
    def require_any_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        return self


class DomainEntryStreamerResponse(BaseModel):
    streamer_id: int = Field(alias="streamerId")
    streamer_name: str = Field(alias="streamerName")
    relevance: str | None
    note: str | None
    created_at: datetime = Field(alias="createdAt")


class DomainEntryAliasResponse(BaseModel):
    alias_id: int = Field(alias="aliasId")
    entry_id: int = Field(alias="entryId")
    surface_form: str = Field(alias="surfaceForm")
    alias_kind: AliasKind = Field(alias="aliasKind")
    certainty: Certainty
    apply_scope: ApplyScope = Field(alias="applyScope")
    language_code: str | None = Field(alias="languageCode")
    note: str | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class DomainEntryResponse(BaseModel):
    entry_id: int = Field(alias="entryId")
    type_id: int = Field(alias="typeId")
    type_key: str = Field(alias="typeKey")
    type_label: str = Field(alias="typeLabel")
    canonical_name: str = Field(alias="canonicalName")
    display_name: str | None = Field(alias="displayName")
    disambiguation: str | None
    detail: str | None
    prompt_policy: PromptPolicy = Field(alias="promptPolicy")
    priority: int
    is_active: bool = Field(alias="isActive")
    source_note: str | None = Field(alias="sourceNote")
    streamers: list[DomainEntryStreamerResponse]
    aliases: list[DomainEntryAliasResponse]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class DomainEntryListResponse(BaseModel):
    items: list[DomainEntryResponse]


class DeleteResponse(BaseModel):
    success: bool
