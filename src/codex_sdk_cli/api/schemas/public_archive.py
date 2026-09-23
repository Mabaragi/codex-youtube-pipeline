from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from codex_sdk_cli.application.public_archive.queries import (
    PublicArchiveStreamer,
    PublicArchiveVideo,
    PublicArchiveVideoPage,
)


class PublicArchiveStreamerMetadataResponse(BaseModel):
    id: str | None
    name: str | None


class PublicArchiveChannelResponse(BaseModel):
    id: int | None
    name: str | None
    handle: str | None
    youtube_channel_id: str | None = Field(alias="youtubeChannelId")

    model_config = ConfigDict(populate_by_name=True)


class PublicArchiveTimelineVariantResponse(BaseModel):
    key: str
    url: str
    version: str


class PublicArchiveTopicMatchResponse(BaseModel):
    id: str
    label: str


class PublicArchiveSearchMatchesResponse(BaseModel):
    topics: list[PublicArchiveTopicMatchResponse]


class PublicArchiveVideoResponse(BaseModel):
    environment: str
    id: int
    youtube_id: str = Field(alias="youtubeId")
    title: str
    streamer_id: str | None = Field(alias="streamerId")
    streamer: PublicArchiveStreamerMetadataResponse
    channel: PublicArchiveChannelResponse
    published_at: str | None = Field(alias="publishedAt")
    duration_text: str | None = Field(alias="durationText")
    duration_seconds: float | None = Field(alias="durationSeconds")
    thumbnail_url: str | None = Field(alias="thumbnailUrl")
    is_embeddable: bool | None = Field(alias="isEmbeddable")
    display_title: str | None = Field(alias="displayTitle")
    display_summary: str | None = Field(alias="displaySummary")
    main_topics: list[str] = Field(alias="mainTopics")
    episode_count: int = Field(alias="episodeCount")
    event_count: int = Field(alias="eventCount")
    topic_cluster_count: int = Field(alias="topicClusterCount")
    block_count: int = Field(alias="blockCount")
    timeline_variants: list[PublicArchiveTimelineVariantResponse] = Field(alias="timelineVariants")
    timeline_url: str = Field(alias="timelineUrl")
    updated_at: datetime = Field(alias="updatedAt")
    open_count: int = Field(alias="openCount")
    timeline_load_count: int = Field(alias="timelineLoadCount")
    episode_click_count: int = Field(alias="episodeClickCount")
    search_matches: PublicArchiveSearchMatchesResponse | None = Field(
        default=None,
        alias="searchMatches",
    )

    model_config = ConfigDict(populate_by_name=True)


class PublicArchiveVideosResponse(BaseModel):
    items: list[PublicArchiveVideoResponse]
    next_cursor: str | None = Field(alias="nextCursor")
    total_count: int = Field(alias="totalCount")

    model_config = ConfigDict(populate_by_name=True)


class PublicArchiveVideoItemResponse(BaseModel):
    item: PublicArchiveVideoResponse


class PublicArchiveStreamerResponse(BaseModel):
    id: str | None
    name: str | None
    video_count: int = Field(alias="videoCount")

    model_config = ConfigDict(populate_by_name=True)


class PublicArchiveStreamersResponse(BaseModel):
    items: list[PublicArchiveStreamerResponse]


class PublicArchiveCatalogVersionResponse(BaseModel):
    version: str


def public_archive_video_response(video: PublicArchiveVideo) -> PublicArchiveVideoResponse:
    return PublicArchiveVideoResponse(
        environment=video.environment,
        id=video.id,
        youtubeId=video.youtube_id,
        title=video.title,
        streamerId=video.streamer_id,
        streamer=PublicArchiveStreamerMetadataResponse(
            id=video.streamer_id,
            name=video.streamer_name,
        ),
        channel=PublicArchiveChannelResponse(
            id=video.channel_id,
            name=video.channel_name,
            handle=video.channel_handle,
            youtubeChannelId=video.youtube_channel_id,
        ),
        publishedAt=video.published_at,
        durationText=video.duration_text,
        durationSeconds=video.duration_seconds,
        thumbnailUrl=video.thumbnail_url,
        isEmbeddable=video.is_embeddable,
        displayTitle=video.display_title,
        displaySummary=video.display_summary,
        mainTopics=list(video.main_topics),
        episodeCount=video.episode_count,
        eventCount=video.event_count,
        topicClusterCount=video.topic_cluster_count,
        blockCount=video.block_count,
        timelineVariants=[
            PublicArchiveTimelineVariantResponse(
                key=item.key,
                url=item.url,
                version=item.version,
            )
            for item in video.timeline_variants
        ],
        timelineUrl=video.timeline_url,
        updatedAt=video.updated_at,
        openCount=video.open_count,
        timelineLoadCount=video.timeline_load_count,
        episodeClickCount=video.episode_click_count,
        searchMatches=(
            PublicArchiveSearchMatchesResponse(
                topics=[
                    PublicArchiveTopicMatchResponse(id=item.id, label=item.label)
                    for item in video.search_matches
                ]
            )
            if video.search_matches
            else None
        ),
    )


def public_archive_videos_response(
    page: PublicArchiveVideoPage,
) -> PublicArchiveVideosResponse:
    return PublicArchiveVideosResponse(
        items=[public_archive_video_response(item) for item in page.items],
        nextCursor=page.next_cursor,
        totalCount=page.total_count,
    )


def public_archive_streamer_response(
    streamer: PublicArchiveStreamer,
) -> PublicArchiveStreamerResponse:
    return PublicArchiveStreamerResponse(
        id=streamer.id,
        name=streamer.name,
        videoCount=streamer.video_count,
    )
