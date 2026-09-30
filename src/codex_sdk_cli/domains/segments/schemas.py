from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import SegmentCategory


class RawSegment(BaseModel):
    start_episode: int = Field(alias="startEpisode", ge=1)
    end_episode: int = Field(alias="endEpisode", ge=1)
    category: SegmentCategory
    label: str = Field(min_length=1, max_length=200)
    phase: Literal["opening", "main", "closing"]
    game: str | None
    game_uncertain: bool = Field(alias="gameUncertain")
    content: str | None
    collab: bool
    partners: list[str]

    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)


class SegmentOutput(BaseModel):
    segments: list[RawSegment]

    model_config = ConfigDict(extra="forbid")
