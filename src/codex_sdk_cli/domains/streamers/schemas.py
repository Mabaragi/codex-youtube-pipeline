from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StreamerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StreamerUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def require_name(self) -> Self:
        if "name" not in self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        if self.name is None:
            raise ValueError("name cannot be null.")
        return self


class StreamerResponse(BaseModel):
    id: int
    name: str


class ChannelCreateRequest(BaseModel):
    streamer_id: int = Field(alias="streamerId", ge=1)
    handle: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    youtube_channel_id: str | None = Field(
        default=None,
        alias="youtubeChannelId",
        min_length=1,
        max_length=255,
    )

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class ChannelUpdateRequest(BaseModel):
    streamer_id: int | None = Field(default=None, alias="streamerId", ge=1)
    handle: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    youtube_channel_id: str | None = Field(
        default=None,
        alias="youtubeChannelId",
        min_length=1,
        max_length=255,
    )

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    @model_validator(mode="after")
    def require_update_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        for field_name in ("streamer_id", "handle", "name"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null.")
        return self


class ChannelResponse(BaseModel):
    id: int
    streamer_id: int = Field(alias="streamerId")
    handle: str
    name: str
    youtube_channel_id: str | None = Field(alias="youtubeChannelId")

    model_config = ConfigDict(populate_by_name=True)


class DeleteResponse(BaseModel):
    success: bool

