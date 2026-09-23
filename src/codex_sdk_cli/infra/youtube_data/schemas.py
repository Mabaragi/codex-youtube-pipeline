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


class YouTubeChannelRelatedPlaylists(BaseModel):
    uploads: str = Field(min_length=1)

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeChannelContentDetails(BaseModel):
    related_playlists: YouTubeChannelRelatedPlaylists = Field(alias="relatedPlaylists")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeChannelResource(BaseModel):
    kind: str
    etag: str
    youtube_channel_id: str = Field(alias="id", min_length=1)
    snippet: YouTubeChannelSnippet
    content_details: YouTubeChannelContentDetails = Field(alias="contentDetails")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeChannelsListResponse(BaseModel):
    kind: str
    etag: str
    page_info: YouTubePageInfo = Field(alias="pageInfo")
    items: list[YouTubeChannelResource]

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeThumbnail(BaseModel):
    url: str = Field(min_length=1)

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubePlaylistItemContentDetails(BaseModel):
    video_id: str = Field(alias="videoId", min_length=1)
    video_published_at: datetime = Field(alias="videoPublishedAt")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubePlaylistItemSnippet(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    thumbnails: dict[str, YouTubeThumbnail] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubePlaylistItemResource(BaseModel):
    snippet: YouTubePlaylistItemSnippet
    content_details: YouTubePlaylistItemContentDetails = Field(alias="contentDetails")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubePlaylistItemsListResponse(BaseModel):
    kind: str
    etag: str
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    page_info: YouTubePageInfo = Field(alias="pageInfo")
    items: list[YouTubePlaylistItemResource]

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideoContentDetails(BaseModel):
    duration: str | None = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideoStatus(BaseModel):
    embeddable: bool | None = None
    privacy_status: str | None = Field(default=None, alias="privacyStatus")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideoSnippet(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    published_at: datetime = Field(alias="publishedAt")
    channel_id: str = Field(alias="channelId", min_length=1)
    channel_title: str = Field(alias="channelTitle", min_length=1)
    thumbnails: dict[str, YouTubeThumbnail] = Field(default_factory=dict)

    @property
    def thumbnail_url(self) -> str | None:
        for key in ("maxres", "standard", "high", "medium", "default"):
            thumbnail = self.thumbnails.get(key)
            if thumbnail is not None:
                return thumbnail.url
        return None

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideoResource(BaseModel):
    youtube_video_id: str = Field(alias="id", min_length=1)
    snippet: YouTubeVideoSnippet | None = None
    content_details: YouTubeVideoContentDetails | None = Field(
        default=None,
        alias="contentDetails",
    )
    status: YouTubeVideoStatus | None = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class YouTubeVideosListResponse(BaseModel):
    kind: str
    etag: str
    page_info: YouTubePageInfo = Field(alias="pageInfo")
    items: list[YouTubeVideoResource]

    model_config = ConfigDict(extra="allow", populate_by_name=True)
