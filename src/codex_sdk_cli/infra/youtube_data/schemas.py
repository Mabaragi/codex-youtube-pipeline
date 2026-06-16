from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class YouTubePageInfo(BaseModel):
    total_results: int = Field(alias="totalResults", ge=0)
    results_per_page: int = Field(alias="resultsPerPage", ge=0)

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeChannelSnippet(BaseModel):
    title: str = Field(min_length=1)

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class YouTubeChannelResource(BaseModel):
    kind: str
    etag: str
    youtube_channel_id: str = Field(alias="id", min_length=1)
    snippet: YouTubeChannelSnippet

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeChannelsListResponse(BaseModel):
    kind: str
    etag: str
    page_info: YouTubePageInfo = Field(alias="pageInfo")
    items: list[YouTubeChannelResource]

    model_config = ConfigDict(extra="allow", populate_by_name=True)
