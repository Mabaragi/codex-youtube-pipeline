from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VideoCollectStoppedReason = Literal[
    "existing_video",
    "no_next_page",
    "listing_limit_reached",
]


class VideoResponse(BaseModel):
    id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    description: str
    published_at: datetime = Field(alias="publishedAt")
    duration: str | None
    is_embeddable: bool | None = Field(alias="isEmbeddable")
    embed_status_checked_at: datetime | None = Field(alias="embedStatusCheckedAt")
    thumbnail_url: str | None = Field(alias="thumbnailUrl")
    source_listing_api_call_id: int | None = Field(alias="sourceListingApiCallId")
    source_details_api_call_id: int | None = Field(alias="sourceDetailsApiCallId")
    source_embed_status_api_call_id: int | None = Field(alias="sourceEmbedStatusApiCallId")
    source_job_id: int | None = Field(alias="sourceJobId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class CollectChannelVideosResponse(BaseModel):
    channel_id: int = Field(alias="channelId")
    youtube_channel_id: str = Field(alias="youtubeChannelId")
    job_id: int = Field(alias="jobId")
    job_attempt_id: int = Field(alias="jobAttemptId")
    created_count: int = Field(alias="createdCount")
    created_video_ids: list[int] = Field(alias="createdVideoIds")
    first_existing_youtube_video_id: str | None = Field(alias="firstExistingYoutubeVideoId")
    stopped_reason: VideoCollectStoppedReason = Field(alias="stoppedReason")
    pages_fetched: int = Field(alias="pagesFetched")
    listing_api_call_ids: list[int] = Field(alias="listingApiCallIds")
    video_details_api_call_ids: list[int] = Field(alias="videoDetailsApiCallIds")
    skipped_missing_details_youtube_video_ids: list[str] = Field(
        alias="skippedMissingDetailsYoutubeVideoIds"
    )

    model_config = ConfigDict(populate_by_name=True)


VideoCollectAllChannelStatus = Literal["succeeded", "failed", "skipped"]


class CollectAllChannelsVideosResult(BaseModel):
    channel_id: int = Field(alias="channelId")
    status: VideoCollectAllChannelStatus
    created_count: int = Field(default=0, alias="createdCount")
    created_video_ids: list[int] = Field(default_factory=list, alias="createdVideoIds")
    job_id: int | None = Field(default=None, alias="jobId")
    job_attempt_id: int | None = Field(default=None, alias="jobAttemptId")
    error_type: str | None = Field(default=None, alias="errorType")
    error_message: str | None = Field(default=None, alias="errorMessage")
    collection: CollectChannelVideosResponse | None = None

    model_config = ConfigDict(populate_by_name=True)


class CollectAllChannelsVideosResponse(BaseModel):
    channel_count: int = Field(alias="channelCount")
    processed_count: int = Field(alias="processedCount")
    succeeded_count: int = Field(alias="succeededCount")
    failed_count: int = Field(alias="failedCount")
    skipped_count: int = Field(alias="skippedCount")
    results: list[CollectAllChannelsVideosResult]

    model_config = ConfigDict(populate_by_name=True)
