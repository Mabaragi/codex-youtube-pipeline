from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StreamerCreateRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Display name of the streamer.",
        examples=["Chzzk Archive"],
    )

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"name": "Chzzk Archive"}]},
    )


class StreamerUpdateRequest(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New display name of the streamer.",
        examples=["Chzzk Archive KR"],
    )

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"name": "Chzzk Archive KR"}]},
    )

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
    streamer_id: int = Field(
        alias="streamerId",
        ge=1,
        description="ID of the streamer that owns this channel.",
        examples=[1],
    )
    handle: str = Field(
        min_length=1,
        max_length=255,
        description="Public channel handle or short identifier.",
        examples=["@archive-live"],
    )
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Display name of the channel.",
        examples=["Archive Live"],
    )
    youtube_channel_id: str | None = Field(
        default=None,
        alias="youtubeChannelId",
        min_length=1,
        max_length=255,
        description="Optional YouTube channel ID, not the handle.",
        examples=["UC_x5XG1OV2P6uZZ5FSM9Ttw"],
    )

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "streamerId": 1,
                    "handle": "@archive-live",
                    "name": "Archive Live",
                    "youtubeChannelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
                }
            ]
        },
    )


class ChannelUpdateRequest(BaseModel):
    streamer_id: int | None = Field(
        default=None,
        alias="streamerId",
        ge=1,
        description="New owning streamer ID.",
        examples=[2],
    )
    handle: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New public channel handle or short identifier.",
        examples=["@archive-shorts"],
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New display name of the channel.",
        examples=["Archive Shorts"],
    )
    youtube_channel_id: str | None = Field(
        default=None,
        alias="youtubeChannelId",
        min_length=1,
        max_length=255,
        description="New YouTube channel ID. Use null to clear this optional field.",
        examples=["UC_x5XG1OV2P6uZZ5FSM9Ttw"],
    )

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "streamerId": 2,
                    "handle": "@archive-shorts",
                    "name": "Archive Shorts",
                    "youtubeChannelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
                }
            ]
        },
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
    source_api_call_id: int | None = Field(alias="sourceApiCallId")
    source_job_id: int | None = Field(alias="sourceJobId")

    model_config = ConfigDict(populate_by_name=True)


class DeleteResponse(BaseModel):
    success: bool
