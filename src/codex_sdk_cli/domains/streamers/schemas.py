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


class DeleteResponse(BaseModel):
    success: bool
