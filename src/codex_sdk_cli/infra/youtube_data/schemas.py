from __future__ import annotations

from datetime import datetime

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


class YouTubeSearchVideoId(BaseModel):
    video_id: str = Field(alias="videoId", min_length=1)

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeSearchResultResource(BaseModel):
    id: YouTubeSearchVideoId

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeSearchListResponse(BaseModel):
    kind: str
    etag: str
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    page_info: YouTubePageInfo = Field(alias="pageInfo")
    items: list[YouTubeSearchResultResource]

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeThumbnail(BaseModel):
    url: str = Field(min_length=1)

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideoSnippet(BaseModel):
    published_at: datetime = Field(alias="publishedAt")
    title: str = Field(min_length=1)
    description: str = ""
    thumbnails: dict[str, YouTubeThumbnail] = Field(default_factory=dict)
    live_broadcast_content: str | None = Field(default=None, alias="liveBroadcastContent")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideoContentDetails(BaseModel):
    duration: str | None = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideoStatus(BaseModel):
    upload_status: str | None = Field(default=None, alias="uploadStatus")
    privacy_status: str | None = Field(default=None, alias="privacyStatus")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideoStatistics(BaseModel):
    view_count: str | None = Field(default=None, alias="viewCount")
    like_count: str | None = Field(default=None, alias="likeCount")
    comment_count: str | None = Field(default=None, alias="commentCount")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideoResource(BaseModel):
    youtube_video_id: str = Field(alias="id", min_length=1)
    snippet: YouTubeVideoSnippet
    content_details: YouTubeVideoContentDetails | None = Field(
        default=None,
        alias="contentDetails",
    )
    status: YouTubeVideoStatus | None = None
    statistics: YouTubeVideoStatistics | None = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideosListResponse(BaseModel):
    kind: str
    etag: str
    page_info: YouTubePageInfo = Field(alias="pageInfo")
    items: list[YouTubeVideoResource]

    model_config = ConfigDict(extra="allow", populate_by_name=True)
