from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_channel_repository,
    get_operation_event_recorder,
    get_pipeline_job_repository,
    get_settings,
    get_video_repository,
    get_youtube_data_client,
)
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.channels.ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelRepositoryPort,
    ChannelUpdate,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobAttemptStatus,
    PipelineJobCreate,
    PipelineJobDetailRecord,
    PipelineJobListQuery,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
    PipelineJobStatus,
    PipelineJobSummaryRecord,
)
from codex_sdk_cli.domains.videos.ports import VideoCreate, VideoRecord, VideoRepositoryPort
from codex_sdk_cli.domains.youtube_data.exceptions import YouTubeDataUpstreamError
from codex_sdk_cli.domains.youtube_data.ports import (
    YouTubeChannelResolution,
    YouTubeChannelUploadsPlaylist,
    YouTubeDataClientPort,
    YouTubeVideoDetails,
    YouTubeVideoDetailsBatch,
    YouTubeVideoListing,
    YouTubeVideoListingPage,
)
from codex_sdk_cli.settings import CliSettings


class FakeYouTubeDataClient(YouTubeDataClientPort):
    def __init__(self) -> None:
        self.listing_pages: list[YouTubeVideoListingPage] = []
        self.details_by_id: dict[str, YouTubeVideoDetails] = {}
        self.uploads_requests: list[tuple[str, int | None]] = []
        self.listing_requests: list[tuple[str, str | None, int | None]] = []
        self.detail_requests: list[tuple[tuple[str, ...], int | None]] = []
        self.listing_error: YouTubeDataUpstreamError | None = None
        self.next_uploads_call_id = 50
        self.next_details_call_id = 100

    async def resolve_youtube_channel_by_handle(
        self,
        handle: str,
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeChannelResolution:
        return YouTubeChannelResolution(
            handle=handle,
            youtube_channel_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
            title="Google for Developers",
            uploads_playlist_id="UU_x5XG1OV2P6uZZ5FSM9Ttw",
            source_api_call_id=1,
        )

    async def get_channel_uploads_playlist(
        self,
        youtube_channel_id: str,
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeChannelUploadsPlaylist:
        self.uploads_requests.append((youtube_channel_id, pipeline_job_attempt_id))
        call_id = self.next_uploads_call_id
        self.next_uploads_call_id += 1
        return YouTubeChannelUploadsPlaylist(
            youtube_channel_id=youtube_channel_id,
            uploads_playlist_id="UU_x5XG1OV2P6uZZ5FSM9Ttw",
            source_api_call_id=call_id,
        )

    async def list_upload_playlist_videos(
        self,
        uploads_playlist_id: str,
        *,
        page_token: str | None = None,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoListingPage:
        self.listing_requests.append(
            (uploads_playlist_id, page_token, pipeline_job_attempt_id)
        )
        if self.listing_error is not None:
            raise self.listing_error
        if not self.listing_pages:
            return YouTubeVideoListingPage(
                videos=(),
                next_page_token=None,
                source_api_call_id=99,
            )
        return self.listing_pages.pop(0)

    async def get_video_details(
        self,
        youtube_video_ids: tuple[str, ...],
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoDetailsBatch:
        self.detail_requests.append((youtube_video_ids, pipeline_job_attempt_id))
        call_id = self.next_details_call_id
        self.next_details_call_id += 1
        return YouTubeVideoDetailsBatch(
            videos=tuple(
                replace(self.details_by_id[youtube_video_id], source_api_call_id=call_id)
                for youtube_video_id in youtube_video_ids
                if youtube_video_id in self.details_by_id
            ),
            source_api_call_id=call_id,
        )


class FakeChannelRepository(ChannelRepositoryPort):
    def __init__(self) -> None:
        self.channels: dict[int, ChannelRecord] = {}

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        record = ChannelRecord(
            id=max(self.channels, default=0) + 1,
            streamer_id=channel.streamer_id,
            handle=channel.handle,
            name=channel.name,
            youtube_channel_id=channel.youtube_channel_id,
            uploads_playlist_id=channel.uploads_playlist_id,
            source_api_call_id=channel.source_api_call_id,
            source_job_id=channel.source_job_id,
        )
        self.channels[record.id] = record
        return record

    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        records = list(self.channels.values())
        if streamer_id is None:
            return records
        return [record for record in records if record.streamer_id == streamer_id]

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        return self.channels.get(channel_id)

    async def get_channel_by_youtube_channel_id(
        self,
        youtube_channel_id: str,
    ) -> ChannelRecord | None:
        return next(
            (
                record
                for record in self.channels.values()
                if record.youtube_channel_id == youtube_channel_id
            ),
            None,
        )

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        record = self.channels.get(channel_id)
        if record is None:
            return None
        updated = replace(
            record,
            handle=update.handle if update.handle is not None else record.handle,
            name=update.name if update.name is not None else record.name,
            youtube_channel_id=(
                update.youtube_channel_id
                if update.youtube_channel_id_set
                else record.youtube_channel_id
            ),
        )
        self.channels[channel_id] = updated
        return updated

    async def update_uploads_playlist_id(
        self,
        channel_id: int,
        uploads_playlist_id: str,
    ) -> ChannelRecord | None:
        record = self.channels.get(channel_id)
        if record is None:
            return None
        updated = replace(record, uploads_playlist_id=uploads_playlist_id)
        self.channels[channel_id] = updated
        return updated

    async def delete_channel(self, channel_id: int) -> bool:
        return self.channels.pop(channel_id, None) is not None


class FakeVideoRepository(VideoRepositoryPort):
    def __init__(self) -> None:
        self.videos: dict[int, VideoRecord] = {}
        self.next_video_id = 1

    async def list_videos(self, *, channel_id: int) -> list[VideoRecord]:
        records = [record for record in self.videos.values() if record.channel_id == channel_id]
        return sorted(records, key=lambda record: (record.published_at, record.id), reverse=True)

    async def find_existing_youtube_video_id(
        self,
        *,
        channel_id: int,
        youtube_video_ids: tuple[str, ...],
    ) -> str | None:
        existing = {
            record.youtube_video_id
            for record in self.videos.values()
            if record.channel_id == channel_id
        }
        return next(
            (
                youtube_video_id
                for youtube_video_id in youtube_video_ids
                if youtube_video_id in existing
            ),
            None,
        )

    async def create_videos(self, videos: list[VideoCreate]) -> list[VideoRecord]:
        now = datetime.now(UTC)
        records: list[VideoRecord] = []
        for video in videos:
            record = VideoRecord(
                id=self.next_video_id,
                channel_id=video.channel_id,
                youtube_video_id=video.youtube_video_id,
                title=video.title,
                description=video.description,
                published_at=video.published_at,
                duration=video.duration,
                thumbnail_url=video.thumbnail_url,
                source_listing_api_call_id=video.source_listing_api_call_id,
                source_details_api_call_id=video.source_details_api_call_id,
                source_job_id=video.source_job_id,
                created_at=now,
                updated_at=now,
            )
            self.videos[record.id] = record
            records.append(record)
            self.next_video_id += 1
        return records


class FakePipelineJobRepository(PipelineJobRepositoryPort):
    def __init__(self) -> None:
        self.jobs: dict[int, PipelineJobRecord] = {}
        self.attempts: dict[int, PipelineJobAttemptRecord] = {}
        self.next_job_id = 1
        self.next_attempt_id = 1

    async def create_job(self, job: PipelineJobCreate) -> PipelineJobRecord:
        now = datetime.now(UTC)
        record = PipelineJobRecord(
            id=self.next_job_id,
            step=job.step,
            status=job.status,
            subject_type=job.subject_type,
            subject_id=job.subject_id,
            external_key=job.external_key,
            input_json=job.input_json,
            input_hash=job.input_hash,
            parent_job_id=job.parent_job_id,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self.jobs[record.id] = record
        self.next_job_id += 1
        return record

    async def get_job(self, job_id: int) -> PipelineJobRecord | None:
        return self.jobs.get(job_id)

    async def list_job_summaries(
        self,
        query: PipelineJobListQuery,
    ) -> list[PipelineJobSummaryRecord]:
        return []

    async def get_job_detail(self, job_id: int) -> PipelineJobDetailRecord | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return PipelineJobDetailRecord(
            job=job,
            attempts=[
                attempt for attempt in self.attempts.values() if attempt.job_id == job_id
            ],
            external_api_calls=[],
            channels=[],
            videos=[],
        )

    async def create_attempt(
        self,
        *,
        job_id: int,
        worker_id: str | None = None,
    ) -> PipelineJobAttemptRecord:
        now = datetime.now(UTC)
        attempt = PipelineJobAttemptRecord(
            id=self.next_attempt_id,
            job_id=job_id,
            attempt_no=sum(item.job_id == job_id for item in self.attempts.values()) + 1,
            status="running",
            started_at=now,
            finished_at=None,
            worker_id=worker_id,
            error_type=None,
            error_message=None,
            output_json=None,
        )
        self.attempts[attempt.id] = attempt
        self.next_attempt_id += 1
        return attempt

    async def mark_attempt_succeeded(
        self,
        attempt_id: int,
        *,
        output_json: JsonObject,
    ) -> PipelineJobAttemptRecord:
        return self._update_attempt(
            attempt_id,
            status="succeeded",
            output_json=output_json,
            error_type=None,
            error_message=None,
        )

    async def mark_attempt_failed(
        self,
        attempt_id: int,
        *,
        error_type: str,
        error_message: str,
    ) -> PipelineJobAttemptRecord:
        return self._update_attempt(
            attempt_id,
            status="failed",
            output_json=None,
            error_type=error_type,
            error_message=error_message,
        )

    async def mark_job_succeeded(self, job_id: int) -> PipelineJobRecord:
        return self._update_job(job_id, status="succeeded")

    async def mark_job_failed(self, job_id: int) -> PipelineJobRecord:
        return self._update_job(job_id, status="failed")

    async def mark_job_running(self, job_id: int) -> PipelineJobRecord:
        job = self.jobs[job_id]
        updated = replace(job, status="running", completed_at=None)
        self.jobs[job_id] = updated
        return updated

    def _update_attempt(
        self,
        attempt_id: int,
        *,
        status: PipelineJobAttemptStatus,
        output_json: JsonObject | None,
        error_type: str | None,
        error_message: str | None,
    ) -> PipelineJobAttemptRecord:
        attempt = self.attempts[attempt_id]
        updated = replace(
            attempt,
            status=status,
            finished_at=datetime.now(UTC),
            output_json=output_json,
            error_type=error_type,
            error_message=error_message,
        )
        self.attempts[attempt_id] = updated
        return updated

    def _update_job(self, job_id: int, *, status: PipelineJobStatus) -> PipelineJobRecord:
        job = self.jobs[job_id]
        now = datetime.now(UTC)
        updated = replace(job, status=status, updated_at=now, completed_at=now)
        self.jobs[job_id] = updated
        return updated


class FakeOperationEventRecorder(OperationEventRecorderPort):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        if self.fail:
            raise RuntimeError("event recorder unavailable")
        self.events.append(event)


def test_collect_channel_videos_stops_at_first_existing_video() -> None:
    client, channels, videos, pipeline_jobs = _fakes()
    events = FakeOperationEventRecorder()
    _seed_channel(channels)
    _seed_existing_video(videos)
    client.listing_pages.append(
        _listing_page(
            ("new-1", "new-2", "existing-1", "ignored"),
            next_page_token="older",
            source_api_call_id=10,
        )
    )
    _seed_details(client, "new-1", "new-2")

    response = asyncio.run(_collect(client, channels, videos, pipeline_jobs, events=events))

    assert response["createdCount"] == 2
    assert response["createdVideoIds"] == [2, 3]
    assert response["firstExistingYoutubeVideoId"] == "existing-1"
    assert response["stoppedReason"] == "existing_video"
    assert response["pagesFetched"] == 1
    assert response["listingApiCallIds"] == [10]
    assert response["videoDetailsApiCallIds"] == [100]
    assert client.detail_requests == [(("new-1", "new-2"), 1)]
    assert pipeline_jobs.jobs[1].step == "video_collect"
    assert pipeline_jobs.jobs[1].status == "succeeded"
    assert pipeline_jobs.attempts[1].output_json == response
    assert [event.event_type for event in events.events] == [
        "video_collect.requested",
        "video_collect.started",
        "video_collect.succeeded",
    ]


def test_collect_channel_videos_first_item_existing_skips_details_call() -> None:
    client, channels, videos, pipeline_jobs = _fakes()
    _seed_channel(channels)
    _seed_existing_video(videos)
    client.listing_pages.append(
        _listing_page(
            ("existing-1", "older"),
            next_page_token="older",
            source_api_call_id=10,
        )
    )

    response = asyncio.run(_collect(client, channels, videos, pipeline_jobs))

    assert response["createdCount"] == 0
    assert response["createdVideoIds"] == []
    assert response["firstExistingYoutubeVideoId"] == "existing-1"
    assert response["stoppedReason"] == "existing_video"
    assert response["videoDetailsApiCallIds"] == []
    assert client.detail_requests == []


def test_collect_channel_videos_listing_limit_reached() -> None:
    client, channels, videos, pipeline_jobs = _fakes()
    _seed_channel(channels)
    video_ids = [f"video-{index:03}" for index in range(500)]
    for page_index in range(10):
        page_ids = tuple(video_ids[page_index * 50 : (page_index + 1) * 50])
        client.listing_pages.append(
            _listing_page(
                page_ids,
                next_page_token=f"page-{page_index + 1}",
                source_api_call_id=10 + page_index,
            )
        )
        _seed_details(client, *page_ids)

    response = asyncio.run(_collect(client, channels, videos, pipeline_jobs))

    assert response["createdCount"] == 500
    assert response["stoppedReason"] == "listing_limit_reached"
    assert response["pagesFetched"] == 10
    assert len(response["listingApiCallIds"]) == 10
    assert len(response["videoDetailsApiCallIds"]) == 10


def test_collect_channel_videos_refreshes_missing_uploads_playlist_id() -> None:
    client, channels, videos, pipeline_jobs = _fakes()
    _seed_channel(channels, uploads_playlist_id=None)
    client.listing_pages.append(
        _listing_page(
            ("new-1",),
            next_page_token=None,
            source_api_call_id=10,
        )
    )
    _seed_details(client, "new-1")

    response = asyncio.run(_collect(client, channels, videos, pipeline_jobs))

    assert response["createdCount"] == 1
    assert client.uploads_requests == [("UC_x5XG1OV2P6uZZ5FSM9Ttw", 1)]
    assert channels.channels[1].uploads_playlist_id == "UU_x5XG1OV2P6uZZ5FSM9Ttw"


def test_collect_channel_videos_maps_missing_channel_and_youtube_id() -> None:
    client, channels, videos, pipeline_jobs = _fakes()

    missing = asyncio.run(
        _collect(client, channels, videos, pipeline_jobs, expected_status=404)
    )

    _seed_channel(channels, youtube_channel_id=None)
    missing_youtube_id = asyncio.run(
        _collect(client, channels, videos, pipeline_jobs, expected_status=400)
    )

    assert missing == {"detail": "Channel not found."}
    assert missing_youtube_id == {"detail": "Channel does not have a YouTube channel ID."}
    assert pipeline_jobs.jobs == {}


def test_collect_channel_videos_requires_youtube_data_api_key() -> None:
    _client, channels, videos, pipeline_jobs = _fakes()
    _seed_channel(channels)

    response = asyncio.run(
        _collect_without_client_override(channels, videos, pipeline_jobs, expected_status=503)
    )

    assert response == {"detail": "YouTube Data API key is not configured."}
    assert pipeline_jobs.jobs == {}


def test_collect_channel_videos_records_failed_attempt_on_listing_error() -> None:
    client, channels, videos, pipeline_jobs = _fakes()
    events = FakeOperationEventRecorder()
    _seed_channel(channels)
    client.listing_error = YouTubeDataUpstreamError(
        "YouTube Data API request failed upstream."
    )

    response = asyncio.run(
        _collect(client, channels, videos, pipeline_jobs, events=events, expected_status=502)
    )

    assert response == {"detail": "YouTube Data API request failed upstream."}
    assert videos.videos == {}
    assert pipeline_jobs.jobs[1].status == "failed"
    assert pipeline_jobs.attempts[1].status == "failed"
    assert pipeline_jobs.attempts[1].error_type == "YouTubeDataUpstreamError"
    assert events.events[-1].event_type == "video_collect.failed"
    assert events.events[-1].error_type == "YouTubeDataUpstreamError"


def test_collect_channel_videos_ignores_event_recorder_failure() -> None:
    client, channels, videos, pipeline_jobs = _fakes()
    events = FakeOperationEventRecorder(fail=True)
    _seed_channel(channels)
    client.listing_pages.append(
        _listing_page(
            ("new-1",),
            next_page_token=None,
            source_api_call_id=10,
        )
    )
    _seed_details(client, "new-1")

    response = asyncio.run(_collect(client, channels, videos, pipeline_jobs, events=events))

    assert response["createdCount"] == 1
    assert pipeline_jobs.jobs[1].status == "succeeded"


def test_video_collect_retry_reexecutes_failed_job() -> None:
    client, channels, videos, pipeline_jobs = _fakes()
    events = FakeOperationEventRecorder()
    _seed_channel(channels)
    _seed_failed_video_collect_job(pipeline_jobs)
    client.listing_pages.append(
        _listing_page(
            ("new-1",),
            next_page_token=None,
            source_api_call_id=10,
        )
    )
    _seed_details(client, "new-1")

    response = asyncio.run(
        _retry(
            client,
            channels,
            videos,
            pipeline_jobs,
            events=events,
            job_id=1,
            expected_status=201,
        )
    )

    assert response["step"] == "video_collect"
    assert response["status"] == "succeeded"
    assert response["result"]["createdCount"] == 1
    assert response["result"]["stoppedReason"] == "no_next_page"
    assert pipeline_jobs.attempts[2].status == "succeeded"
    assert client.listing_requests == [("UU_x5XG1OV2P6uZZ5FSM9Ttw", None, 2)]
    assert "pipeline_retry.succeeded" in {
        event.event_type for event in events.events
    }


def test_video_routes_are_in_openapi() -> None:
    schema = create_app().openapi()

    assert schema["paths"]["/channels/{channel_id}/videos"]["get"]["tags"] == ["videos"]
    assert schema["paths"]["/channels/{channel_id}/videos/collect"]["post"]["tags"] == [
        "videos"
    ]
    response_schema = schema["components"]["schemas"]["CollectChannelVideosResponse"]
    assert {
        "createdCount",
        "createdVideoIds",
        "firstExistingYoutubeVideoId",
        "stoppedReason",
        "skippedMissingDetailsYoutubeVideoIds",
    }.issubset(response_schema["properties"])


def _fakes() -> tuple[
    FakeYouTubeDataClient,
    FakeChannelRepository,
    FakeVideoRepository,
    FakePipelineJobRepository,
]:
    return (
        FakeYouTubeDataClient(),
        FakeChannelRepository(),
        FakeVideoRepository(),
        FakePipelineJobRepository(),
    )


async def _collect(
    youtube_data_client: FakeYouTubeDataClient,
    channels: FakeChannelRepository,
    videos: FakeVideoRepository,
    pipeline_jobs: FakePipelineJobRepository,
    *,
    events: FakeOperationEventRecorder | None = None,
    expected_status: int = 201,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_youtube_data_client] = lambda: youtube_data_client
    app.dependency_overrides[get_channel_repository] = lambda: channels
    app.dependency_overrides[get_video_repository] = lambda: videos
    app.dependency_overrides[get_pipeline_job_repository] = lambda: pipeline_jobs
    app.dependency_overrides[get_operation_event_recorder] = lambda: (
        events or FakeOperationEventRecorder()
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/channels/1/videos/collect")

    assert response.status_code == expected_status, response.text
    return response.json()


async def _collect_without_client_override(
    channels: FakeChannelRepository,
    videos: FakeVideoRepository,
    pipeline_jobs: FakePipelineJobRepository,
    *,
    expected_status: int,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: CliSettings(youtube_data_api_key=None)
    app.dependency_overrides[get_channel_repository] = lambda: channels
    app.dependency_overrides[get_video_repository] = lambda: videos
    app.dependency_overrides[get_pipeline_job_repository] = lambda: pipeline_jobs
    app.dependency_overrides[get_operation_event_recorder] = lambda: FakeOperationEventRecorder()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/channels/1/videos/collect")

    assert response.status_code == expected_status, response.text
    return response.json()


async def _retry(
    youtube_data_client: FakeYouTubeDataClient,
    channels: FakeChannelRepository,
    videos: FakeVideoRepository,
    pipeline_jobs: FakePipelineJobRepository,
    *,
    events: FakeOperationEventRecorder | None = None,
    job_id: int,
    expected_status: int,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_youtube_data_client] = lambda: youtube_data_client
    app.dependency_overrides[get_channel_repository] = lambda: channels
    app.dependency_overrides[get_video_repository] = lambda: videos
    app.dependency_overrides[get_pipeline_job_repository] = lambda: pipeline_jobs
    app.dependency_overrides[get_operation_event_recorder] = lambda: (
        events or FakeOperationEventRecorder()
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(f"/pipeline/jobs/{job_id}/retry")

    assert response.status_code == expected_status, response.text
    return response.json()


def _seed_channel(
    channels: FakeChannelRepository,
    *,
    youtube_channel_id: str | None = "UC_x5XG1OV2P6uZZ5FSM9Ttw",
    uploads_playlist_id: str | None = "UU_x5XG1OV2P6uZZ5FSM9Ttw",
) -> None:
    channels.channels[1] = ChannelRecord(
        id=1,
        streamer_id=1,
        handle="@GoogleDevelopers",
        name="Google for Developers",
        youtube_channel_id=youtube_channel_id,
        uploads_playlist_id=uploads_playlist_id,
        source_api_call_id=42,
        source_job_id=99,
    )


def _seed_existing_video(videos: FakeVideoRepository) -> None:
    now = datetime.now(UTC)
    videos.videos[1] = VideoRecord(
        id=1,
        channel_id=1,
        youtube_video_id="existing-1",
        title="Existing",
        description="already stored",
        published_at=now,
        duration="PT1M",
        thumbnail_url=None,
        source_listing_api_call_id=1,
        source_details_api_call_id=2,
        source_job_id=3,
        created_at=now,
        updated_at=now,
    )
    videos.next_video_id = 2


def _seed_details(client: FakeYouTubeDataClient, *youtube_video_ids: str) -> None:
    for youtube_video_id in youtube_video_ids:
        client.details_by_id[youtube_video_id] = YouTubeVideoDetails(
            youtube_video_id=youtube_video_id,
            duration="PT1M",
            source_api_call_id=0,
        )


def _listing_page(
    youtube_video_ids: tuple[str, ...],
    *,
    next_page_token: str | None,
    source_api_call_id: int,
) -> YouTubeVideoListingPage:
    return YouTubeVideoListingPage(
        videos=tuple(
            YouTubeVideoListing(
                youtube_video_id=youtube_video_id,
                title=f"Title {youtube_video_id}",
                description=f"Description {youtube_video_id}",
                published_at=datetime(2026, 6, 16, 1, index, tzinfo=UTC),
                thumbnail_url=None,
                source_api_call_id=source_api_call_id,
            )
            for index, youtube_video_id in enumerate(youtube_video_ids)
        ),
        next_page_token=next_page_token,
        source_api_call_id=source_api_call_id,
    )


def _seed_failed_video_collect_job(pipeline_jobs: FakePipelineJobRepository) -> None:
    now = datetime.now(UTC)
    pipeline_jobs.jobs[1] = PipelineJobRecord(
        id=1,
        step="video_collect",
        status="failed",
        subject_type="channel",
        subject_id=1,
        external_key="youtube-channel-test",
        input_json={
            "channelId": 1,
            "youtubeChannelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
        },
        input_hash="0" * 64,
        parent_job_id=None,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    pipeline_jobs.attempts[1] = PipelineJobAttemptRecord(
        id=1,
        job_id=1,
        attempt_no=1,
        status="failed",
        started_at=now,
        finished_at=now,
        worker_id=None,
        error_type="YouTubeDataUpstreamError",
        error_message="failed",
        output_json=None,
    )
    pipeline_jobs.next_job_id = 2
    pipeline_jobs.next_attempt_id = 2
