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
    publish_profile_id: int = Field(
        ge=1,
        alias="publishProfileId",
        description="Active publication profile assigned to the streamer.",
    )

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
        json_schema_extra={
            "examples": [{"name": "Chzzk Archive", "publishProfileId": 1}]
        },
    )


class StreamerUpdateRequest(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New display name of the streamer.",
        examples=["Chzzk Archive KR"],
    )
    publish_profile_id: int | None = Field(
        default=None,
        ge=1,
        alias="publishProfileId",
        description="New active publication profile assignment.",
    )

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
        json_schema_extra={
            "examples": [{"name": "Chzzk Archive KR", "publishProfileId": 2}]
        },
    )

    @model_validator(mode="after")
    def require_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null.")
        if "publish_profile_id" in self.model_fields_set and self.publish_profile_id is None:
            raise ValueError("publishProfileId cannot be null.")
        return self


class StreamerResponse(BaseModel):
    id: int
    name: str
    publish_profile_id: int = Field(alias="publishProfileId")

    model_config = ConfigDict(populate_by_name=True)


class DeleteResponse(BaseModel):
    success: bool
