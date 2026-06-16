from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VideoCollectStoppedReason = Literal[
    "existing_video",
    "no_next_page",
    "search_limit_reached",
]


class VideoResponse(BaseModel):
    id: int = Field(alias="videoId")
    channel_id: int = Field(alias="channelId")
    youtube_video_id: str = Field(alias="youtubeVideoId")
    title: str
    description: str
    published_at: datetime = Field(alias="publishedAt")
    duration: str | None
    privacy_status: str | None = Field(alias="privacyStatus")
    upload_status: str | None = Field(alias="uploadStatus")
    live_broadcast_content: str | None = Field(alias="liveBroadcastContent")
    view_count: int | None = Field(alias="viewCount")
    like_count: int | None = Field(alias="likeCount")
    comment_count: int | None = Field(alias="commentCount")
    thumbnail_url: str | None = Field(alias="thumbnailUrl")
    source_search_api_call_id: int | None = Field(alias="sourceSearchApiCallId")
    source_details_api_call_id: int | None = Field(alias="sourceDetailsApiCallId")
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
    search_api_call_ids: list[int] = Field(alias="searchApiCallIds")
    video_details_api_call_ids: list[int] = Field(alias="videoDetailsApiCallIds")
    skipped_missing_details_youtube_video_ids: list[str] = Field(
        alias="skippedMissingDetailsYoutubeVideoIds"
    )

    model_config = ConfigDict(populate_by_name=True)
