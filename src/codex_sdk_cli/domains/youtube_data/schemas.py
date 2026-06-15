from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResolveYouTubeChannelRequest(BaseModel):
    handle: str = Field(
        min_length=1,
        max_length=255,
        description="YouTube handle to resolve. The leading @ is optional.",
        examples=["@GoogleDevelopers"],
    )

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"handle": "@GoogleDevelopers"}]},
    )

    @field_validator("handle")
    @classmethod
    def require_handle_body(cls, value: str) -> str:
        if not value.removeprefix("@").strip():
            raise ValueError("handle must include a name after optional @.")
        return value


class ResolveYouTubeChannelResponse(BaseModel):
    handle: str
    youtube_channel_id: str = Field(alias="youtubeChannelId")
    updated_channel_ids: list[int] = Field(alias="updatedChannelIds")

    model_config = ConfigDict(populate_by_name=True)

