from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResolveYouTubeChannelRequest(BaseModel):
    streamer_id: int = Field(
        alias="streamerId",
        ge=1,
        description="Local streamer ID that will own the created channel row.",
        examples=[1],
    )
    handle: str = Field(
        min_length=1,
        max_length=255,
        description="YouTube handle to resolve. The leading @ is optional.",
        examples=["@GoogleDevelopers"],
    )

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "streamerId": 1,
                    "handle": "@GoogleDevelopers",
                }
            ]
        },
    )

    @field_validator("handle")
    @classmethod
    def require_handle_body(cls, value: str) -> str:
        if not value.removeprefix("@").strip():
            raise ValueError("handle must include a name after optional @.")
        return value


class ResolveYouTubeChannelResponse(BaseModel):
    channel_id: int = Field(alias="channelId")
    streamer_id: int = Field(alias="streamerId")
    handle: str
    name: str
    youtube_channel_id: str = Field(alias="youtubeChannelId")
    source_api_call_id: int = Field(alias="sourceApiCallId")
    job_id: int = Field(alias="jobId")
    job_attempt_id: int = Field(alias="jobAttemptId")

    model_config = ConfigDict(populate_by_name=True)
