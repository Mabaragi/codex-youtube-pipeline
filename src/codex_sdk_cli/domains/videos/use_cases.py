from __future__ import annotations

import hashlib
import json

from codex_sdk_cli.domains.channels.exceptions import ChannelNotFound
from codex_sdk_cli.domains.channels.ports import ChannelRecord, ChannelRepositoryPort
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobAttemptRecord,
    PipelineJobCreate,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
)
from codex_sdk_cli.domains.youtube_data.ports import (
    YouTubeDataClientPort,
    YouTubeVideoDetails,
    YouTubeVideoListing,
)

from .exceptions import ChannelMissingYouTubeId
from .ports import VideoCreate, VideoRecord, VideoRepositoryPort
from .schemas import CollectChannelVideosResponse, VideoCollectStoppedReason, VideoResponse

VIDEO_COLLECT_STEP = "video_collect"
LISTING_PAGE_LIMIT = 10
LISTING_CANDIDATE_LIMIT = 500


class ListChannelVideosUseCase:
    def __init__(
        self,
        channels: ChannelRepositoryPort,
        videos: VideoRepositoryPort,
    ) -> None:
        self._channels = channels
        self._videos = videos

    async def execute(self, channel_id: int) -> list[VideoResponse]:
        await _get_channel_or_raise(self._channels, channel_id)
        records = await self._videos.list_videos(channel_id=channel_id)
        return [_video_response(record) for record in records]


class CollectChannelVideosUseCase:
    def __init__(
        self,
        client: YouTubeDataClientPort,
        channels: ChannelRepositoryPort,
        videos: VideoRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
    ) -> None:
        self._client = client
        self._channels = channels
        self._videos = videos
        self._pipeline_jobs = pipeline_jobs

    async def execute(self, channel_id: int) -> CollectChannelVideosResponse:
        channel = await _get_channel_or_raise(self._channels, channel_id)
        youtube_channel_id = _required_youtube_channel_id(channel)
        input_json: dict[str, object] = {
            "channelId": channel_id,
            "youtubeChannelId": youtube_channel_id,
        }
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step=VIDEO_COLLECT_STEP,
                status="running",
                subject_type="channel",
                subject_id=channel_id,
                external_key=youtube_channel_id,
                input_json=input_json,
                input_hash=_input_hash(input_json),
            )
        )
        attempt = await self._pipeline_jobs.create_attempt(job_id=job.id)
        return await self.execute_job_attempt(
            job,
            attempt,
            channel_id=channel_id,
            youtube_channel_id=youtube_channel_id,
        )

    async def execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        *,
        channel_id: int,
        youtube_channel_id: str,
    ) -> CollectChannelVideosResponse:
        try:
            channel = await _get_channel_or_raise(self._channels, channel_id)
            if _required_youtube_channel_id(channel) != youtube_channel_id:
                raise ChannelMissingYouTubeId(
                    "Channel YouTube ID changed since this pipeline job was created."
                )
            uploads_playlist_id = await self._get_or_refresh_uploads_playlist_id(
                channel,
                attempt_id=attempt.id,
            )
            collected = await self._collect_candidate_videos(
                channel_id=channel_id,
                uploads_playlist_id=uploads_playlist_id,
                attempt_id=attempt.id,
            )
            created = await self._create_video_rows(
                channel_id=channel_id,
                job_id=job.id,
                attempt_id=attempt.id,
                collected=collected,
            )
            response = CollectChannelVideosResponse(
                channelId=channel_id,
                youtubeChannelId=youtube_channel_id,
                jobId=job.id,
                jobAttemptId=attempt.id,
                createdCount=len(created.records),
                createdVideoIds=[record.id for record in created.records],
                firstExistingYoutubeVideoId=collected.first_existing_youtube_video_id,
                stoppedReason=collected.stopped_reason,
                pagesFetched=collected.pages_fetched,
                listingApiCallIds=collected.listing_api_call_ids,
                videoDetailsApiCallIds=created.video_details_api_call_ids,
                skippedMissingDetailsYoutubeVideoIds=(
                    created.skipped_missing_details_youtube_video_ids
                ),
            )
        except Exception as exc:
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            raise

        await self._pipeline_jobs.mark_attempt_succeeded(
            attempt.id,
            output_json=response.model_dump(by_alias=True),
        )
        await self._pipeline_jobs.mark_job_succeeded(job.id)
        return response

    async def _get_or_refresh_uploads_playlist_id(
        self,
        channel: ChannelRecord,
        *,
        attempt_id: int,
    ) -> str:
        if channel.uploads_playlist_id is not None:
            return channel.uploads_playlist_id
        if channel.youtube_channel_id is None:
            raise ChannelMissingYouTubeId("Channel does not have a YouTube channel ID.")
        result = await self._client.get_channel_uploads_playlist(
            channel.youtube_channel_id,
            pipeline_job_attempt_id=attempt_id,
        )
        updated = await self._channels.update_uploads_playlist_id(
            channel.id,
            result.uploads_playlist_id,
        )
        if updated is None:
            raise ChannelNotFound("Channel not found.")
        return updated.uploads_playlist_id or result.uploads_playlist_id

    async def _collect_candidate_videos(
        self,
        *,
        channel_id: int,
        uploads_playlist_id: str,
        attempt_id: int,
    ) -> _CollectedVideoIds:
        page_token: str | None = None
        pages_fetched = 0
        candidate_ids: list[str] = []
        listing_api_call_ids: list[int] = []
        listings_by_video_id: dict[str, YouTubeVideoListing] = {}
        seen: set[str] = set()
        first_existing: str | None = None

        while True:
            if pages_fetched >= LISTING_PAGE_LIMIT or len(candidate_ids) >= LISTING_CANDIDATE_LIMIT:
                stopped_reason: VideoCollectStoppedReason = "listing_limit_reached"
                break

            page = await self._client.list_upload_playlist_videos(
                uploads_playlist_id,
                page_token=page_token,
                pipeline_job_attempt_id=attempt_id,
            )
            pages_fetched += 1
            listing_api_call_ids.append(page.source_api_call_id)
            page_video_ids = tuple(video.youtube_video_id for video in page.videos)

            first_existing = await self._videos.find_existing_youtube_video_id(
                channel_id=channel_id,
                youtube_video_ids=page_video_ids,
            )
            page_candidate_videos = list(page.videos)
            if first_existing is not None:
                page_candidate_videos = page_candidate_videos[
                    : page_video_ids.index(first_existing)
                ]

            for video in page_candidate_videos:
                youtube_video_id = video.youtube_video_id
                if youtube_video_id in seen or len(candidate_ids) >= LISTING_CANDIDATE_LIMIT:
                    continue
                seen.add(youtube_video_id)
                candidate_ids.append(youtube_video_id)
                listings_by_video_id[youtube_video_id] = video

            if first_existing is not None:
                stopped_reason = "existing_video"
                break
            if not page.next_page_token:
                stopped_reason = "no_next_page"
                break
            if pages_fetched >= LISTING_PAGE_LIMIT or len(candidate_ids) >= LISTING_CANDIDATE_LIMIT:
                stopped_reason = "listing_limit_reached"
                break
            page_token = page.next_page_token

        return _CollectedVideoIds(
            youtube_video_ids=tuple(candidate_ids),
            listings_by_video_id=listings_by_video_id,
            first_existing_youtube_video_id=first_existing,
            stopped_reason=stopped_reason,
            pages_fetched=pages_fetched,
            listing_api_call_ids=listing_api_call_ids,
        )

    async def _create_video_rows(
        self,
        *,
        channel_id: int,
        job_id: int,
        attempt_id: int,
        collected: _CollectedVideoIds,
    ) -> _CreatedVideos:
        video_details_api_call_ids: list[int] = []
        details_by_id: dict[str, YouTubeVideoDetails] = {}
        for batch in _chunks(collected.youtube_video_ids, 50):
            details = await self._client.get_video_details(
                batch,
                pipeline_job_attempt_id=attempt_id,
            )
            video_details_api_call_ids.append(details.source_api_call_id)
            for video in details.videos:
                details_by_id[video.youtube_video_id] = video

        skipped = [
            youtube_video_id
            for youtube_video_id in collected.youtube_video_ids
            if youtube_video_id not in details_by_id
        ]
        records = await self._videos.create_videos(
            [
                _video_create(
                    collected.listings_by_video_id[youtube_video_id],
                    details_by_id[youtube_video_id],
                    channel_id=channel_id,
                    source_job_id=job_id,
                )
                for youtube_video_id in collected.youtube_video_ids
                if youtube_video_id in details_by_id
            ]
        )
        return _CreatedVideos(
            records=records,
            video_details_api_call_ids=video_details_api_call_ids,
            skipped_missing_details_youtube_video_ids=skipped,
        )


class _CollectedVideoIds:
    def __init__(
        self,
        *,
        youtube_video_ids: tuple[str, ...],
        listings_by_video_id: dict[str, YouTubeVideoListing],
        first_existing_youtube_video_id: str | None,
        stopped_reason: VideoCollectStoppedReason,
        pages_fetched: int,
        listing_api_call_ids: list[int],
    ) -> None:
        self.youtube_video_ids = youtube_video_ids
        self.listings_by_video_id = listings_by_video_id
        self.first_existing_youtube_video_id = first_existing_youtube_video_id
        self.stopped_reason = stopped_reason
        self.pages_fetched = pages_fetched
        self.listing_api_call_ids = listing_api_call_ids


class _CreatedVideos:
    def __init__(
        self,
        *,
        records: list[VideoRecord],
        video_details_api_call_ids: list[int],
        skipped_missing_details_youtube_video_ids: list[str],
    ) -> None:
        self.records = records
        self.video_details_api_call_ids = video_details_api_call_ids
        self.skipped_missing_details_youtube_video_ids = skipped_missing_details_youtube_video_ids


async def _get_channel_or_raise(
    repository: ChannelRepositoryPort,
    channel_id: int,
) -> ChannelRecord:
    channel = await repository.get_channel(channel_id)
    if channel is None:
        raise ChannelNotFound("Channel not found.")
    return channel


def _required_youtube_channel_id(channel: ChannelRecord) -> str:
    if channel.youtube_channel_id is None:
        raise ChannelMissingYouTubeId("Channel does not have a YouTube channel ID.")
    return channel.youtube_channel_id


def _video_create(
    listing: YouTubeVideoListing,
    details: YouTubeVideoDetails,
    *,
    channel_id: int,
    source_job_id: int,
) -> VideoCreate:
    return VideoCreate(
        channel_id=channel_id,
        youtube_video_id=listing.youtube_video_id,
        title=listing.title,
        description=listing.description,
        published_at=listing.published_at,
        duration=details.duration,
        thumbnail_url=listing.thumbnail_url,
        source_listing_api_call_id=listing.source_api_call_id,
        source_details_api_call_id=details.source_api_call_id,
        source_job_id=source_job_id,
    )


def _video_response(record: VideoRecord) -> VideoResponse:
    return VideoResponse(
        videoId=record.id,
        channelId=record.channel_id,
        youtubeVideoId=record.youtube_video_id,
        title=record.title,
        description=record.description,
        publishedAt=record.published_at,
        duration=record.duration,
        thumbnailUrl=record.thumbnail_url,
        sourceListingApiCallId=record.source_listing_api_call_id,
        sourceDetailsApiCallId=record.source_details_api_call_id,
        sourceJobId=record.source_job_id,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def _input_hash(input_json: dict[str, object]) -> str:
    payload = json.dumps(
        input_json,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _chunks(values: tuple[str, ...], size: int) -> list[tuple[str, ...]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
