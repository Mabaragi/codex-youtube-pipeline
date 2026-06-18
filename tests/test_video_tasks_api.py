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
    get_video_task_repository,
    get_youtube_data_client,
    get_youtube_transcript_client,
    get_youtube_transcript_repository,
    get_youtube_transcript_storage,
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
from codex_sdk_cli.domains.video_tasks.ports import (
    VideoTaskCreate,
    VideoTaskListQuery,
    VideoTaskListRecord,
    VideoTaskRecord,
    VideoTaskRepositoryPort,
    VideoTaskStatus,
)
from codex_sdk_cli.domains.video_tasks.schemas import CollectChannelTranscriptTasksRequest
from codex_sdk_cli.domains.video_tasks.use_cases import CollectChannelTranscriptTasksUseCase
from codex_sdk_cli.domains.videos.ports import VideoCreate, VideoRecord, VideoRepositoryPort
from codex_sdk_cli.domains.youtube_transcripts.exceptions import YouTubeTranscriptNotFound
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    TranscriptStorageLocation,
    YouTubeTranscriptFetchRequest,
    YouTubeTranscriptFetchResult,
    YouTubeTranscriptMetadataFilters,
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptPort,
    YouTubeTranscriptRecord,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptSegment,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageReadRequest,
    YouTubeTranscriptStorageSaveRequest,
)
from codex_sdk_cli.domains.youtube_transcripts.use_cases import FetchYouTubeTranscriptUseCase
from codex_sdk_cli.settings import CliSettings

YOUTUBE_VIDEO_ID = "abc123DEF45"
NOW = datetime(2026, 6, 16, 1, 2, tzinfo=UTC)


class FakeChannelRepository(ChannelRepositoryPort):
    def __init__(self) -> None:
        self.channels: dict[int, ChannelRecord] = {}

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        raise NotImplementedError

    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        return list(self.channels.values())

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        return self.channels.get(channel_id)

    async def get_channel_by_youtube_channel_id(
        self,
        youtube_channel_id: str,
    ) -> ChannelRecord | None:
        return None

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        return None

    async def update_uploads_playlist_id(
        self,
        channel_id: int,
        uploads_playlist_id: str,
    ) -> ChannelRecord | None:
        return None

    async def delete_channel(self, channel_id: int) -> bool:
        return False


class FakeVideoRepository(VideoRepositoryPort):
    def __init__(self) -> None:
        self.videos: dict[int, VideoRecord] = {}

    async def list_all_videos(self) -> list[VideoRecord]:
        return sorted(
            self.videos.values(),
            key=lambda record: (record.published_at, record.id),
            reverse=True,
        )

    async def list_videos(self, *, channel_id: int) -> list[VideoRecord]:
        records = [record for record in self.videos.values() if record.channel_id == channel_id]
        return sorted(records, key=lambda record: (record.published_at, record.id), reverse=True)

    async def find_existing_youtube_video_id(
        self,
        *,
        channel_id: int,
        youtube_video_ids: tuple[str, ...],
    ) -> str | None:
        return None

    async def create_videos(self, videos: list[VideoCreate]) -> list[VideoRecord]:
        return []


class FakeVideoTaskRepository(VideoTaskRepositoryPort):
    def __init__(self, videos: FakeVideoRepository) -> None:
        self.videos = videos
        self.tasks: dict[int, VideoTaskRecord] = {}
        self.next_id = 1

    async def get_task(self, task_id: int) -> VideoTaskRecord | None:
        return self.tasks.get(task_id)

    async def get_task_for_input(
        self,
        *,
        video_id: int,
        task_name: str,
        task_version: str,
        input_hash: str,
    ) -> VideoTaskRecord | None:
        return self._find(video_id, task_name, task_version, input_hash)

    async def get_or_create_task(self, task: VideoTaskCreate) -> VideoTaskRecord:
        existing = self._find(
            task.video_id,
            task.task_name,
            task.task_version,
            task.input_hash,
        )
        if existing is not None:
            return existing
        record = VideoTaskRecord(
            id=self.next_id,
            video_id=task.video_id,
            task_name=task.task_name,
            task_version=task.task_version,
            input_hash=task.input_hash,
            status=task.status,
            worker_id=None,
            timeout_seconds=task.timeout_seconds,
            job_id=None,
            job_attempt_id=None,
            output_transcript_id=None,
            output_json=None,
            error_type=None,
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
        self.tasks[record.id] = record
        self.next_id += 1
        return record

    async def list_tasks(self, query: VideoTaskListQuery) -> list[VideoTaskListRecord]:
        records: list[VideoTaskListRecord] = []
        for task in self.tasks.values():
            video = self.videos.videos[task.video_id]
            if video.channel_id != query.channel_id:
                continue
            if query.task_name is not None and task.task_name != query.task_name:
                continue
            if query.status is not None and task.status != query.status:
                continue
            records.append(VideoTaskListRecord(task=task, youtube_video_id=video.youtube_video_id))
        return sorted(records, key=lambda record: record.task.id, reverse=True)[
            query.offset : query.offset + query.limit
        ]

    async def count_running(self, *, task_name: str) -> int:
        return sum(
            task.task_name == task_name and task.status == "running"
            for task in self.tasks.values()
        )

    async def mark_task_running(
        self,
        task_id: int,
        *,
        worker_id: str,
        timeout_seconds: int,
        job_id: int,
        job_attempt_id: int,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="running",
            worker_id=worker_id,
            timeout_seconds=timeout_seconds,
            job_id=job_id,
            job_attempt_id=job_attempt_id,
            error_type=None,
            error_message=None,
            started_at=NOW,
            completed_at=None,
        )

    async def mark_task_succeeded(
        self,
        task_id: int,
        *,
        output_transcript_id: int | None,
        output_json: JsonObject,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="succeeded",
            output_transcript_id=output_transcript_id,
            output_json=output_json,
            error_type=None,
            error_message=None,
            completed_at=NOW,
        )

    async def mark_task_failed(
        self,
        task_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="failed",
            output_json=output_json,
            error_type=error_type,
            error_message=error_message,
            completed_at=NOW,
        )

    async def mark_task_timed_out(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="timed_out",
            output_json=output_json,
            error_type="TimeoutError",
            error_message=error_message,
            completed_at=NOW,
        )

    def _find(
        self,
        video_id: int,
        task_name: str,
        task_version: str,
        input_hash: str,
    ) -> VideoTaskRecord | None:
        return next(
            (
                task
                for task in self.tasks.values()
                if task.video_id == video_id
                and task.task_name == task_name
                and task.task_version == task_version
                and task.input_hash == input_hash
            ),
            None,
        )

    def _update(self, task_id: int, **updates: Any) -> VideoTaskRecord:
        updated = replace(self.tasks[task_id], updated_at=NOW, **updates)
        self.tasks[task_id] = updated
        return updated


class FakePipelineJobRepository(PipelineJobRepositoryPort):
    def __init__(self) -> None:
        self.jobs: dict[int, PipelineJobRecord] = {}
        self.attempts: dict[int, PipelineJobAttemptRecord] = {}
        self.next_job_id = 1
        self.next_attempt_id = 1

    async def create_job(self, job: PipelineJobCreate) -> PipelineJobRecord:
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
            created_at=NOW,
            updated_at=NOW,
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
        records = list(self.jobs.values())
        if query.step is not None:
            records = [record for record in records if record.step == query.step]
        if query.status is not None:
            records = [record for record in records if record.status == query.status]
        if query.subject_type is not None:
            records = [
                record for record in records if record.subject_type == query.subject_type
            ]
        if query.subject_id is not None:
            records = [record for record in records if record.subject_id == query.subject_id]
        if query.external_key is not None:
            records = [record for record in records if record.external_key == query.external_key]
        if query.cursor is not None:
            records = [record for record in records if record.id < query.cursor]
        records = sorted(records, key=lambda record: record.id, reverse=True)[: query.limit]

        summaries: list[PipelineJobSummaryRecord] = []
        for record in records:
            latest = self._latest_attempt(record.id)
            summaries.append(
                PipelineJobSummaryRecord(
                    job=record,
                    latest_attempt_id=latest.id if latest is not None else None,
                    latest_attempt_status=latest.status if latest is not None else None,
                    attempt_count=sum(
                        attempt.job_id == record.id for attempt in self.attempts.values()
                    ),
                )
            )
        return summaries

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
        attempt = PipelineJobAttemptRecord(
            id=self.next_attempt_id,
            job_id=job_id,
            attempt_no=sum(item.job_id == job_id for item in self.attempts.values()) + 1,
            status="running",
            started_at=NOW,
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
        return self._update_job(job_id, status="running")

    def _update_attempt(
        self,
        attempt_id: int,
        *,
        status: PipelineJobAttemptStatus,
        output_json: JsonObject | None,
        error_type: str | None,
        error_message: str | None,
    ) -> PipelineJobAttemptRecord:
        updated = replace(
            self.attempts[attempt_id],
            status=status,
            finished_at=NOW,
            output_json=output_json,
            error_type=error_type,
            error_message=error_message,
        )
        self.attempts[attempt_id] = updated
        return updated

    def _latest_attempt(self, job_id: int) -> PipelineJobAttemptRecord | None:
        attempts = [
            attempt for attempt in self.attempts.values() if attempt.job_id == job_id
        ]
        return max(attempts, key=lambda attempt: attempt.attempt_no, default=None)

    def _update_job(self, job_id: int, *, status: PipelineJobStatus) -> PipelineJobRecord:
        completed_at = None if status == "running" else NOW
        updated = replace(
            self.jobs[job_id],
            status=status,
            updated_at=NOW,
            completed_at=completed_at,
        )
        self.jobs[job_id] = updated
        return updated


class FakeYouTubeTranscriptClient(YouTubeTranscriptPort):
    def __init__(self) -> None:
        self.requests: list[YouTubeTranscriptFetchRequest] = []
        self.error: Exception | None = None
        self.sleep_seconds = 0.0

    async def fetch_transcript(
        self,
        request: YouTubeTranscriptFetchRequest,
    ) -> YouTubeTranscriptFetchResult:
        self.requests.append(request)
        if self.sleep_seconds:
            await asyncio.sleep(self.sleep_seconds)
        if self.error is not None:
            raise self.error
        return YouTubeTranscriptFetchResult(
            video_id=request.video_id,
            language="Korean",
            language_code=request.languages[0],
            is_generated=True,
            segments=(YouTubeTranscriptSegment(text="hello", start=0.0, duration=1.0),),
        )


class FakeYouTubeTranscriptStorage(YouTubeTranscriptStoragePort):
    def __init__(self) -> None:
        self.saves: list[YouTubeTranscriptStorageSaveRequest] = []

    def location_for(self, object_name: str) -> TranscriptStorageLocation:
        return TranscriptStorageLocation(
            bucket="raw",
            object_name=object_name,
            uri=f"s3://raw/{object_name}",
        )

    async def save_transcript(
        self,
        request: YouTubeTranscriptStorageSaveRequest,
    ) -> TranscriptStorageLocation:
        self.saves.append(request)
        return self.location_for(request.object_name)

    async def read_transcript(
        self,
        request: YouTubeTranscriptStorageReadRequest,
    ) -> bytes:
        raise NotImplementedError


class FakeYouTubeTranscriptRepository(YouTubeTranscriptRepositoryPort):
    def __init__(self) -> None:
        self.records: list[YouTubeTranscriptRecord] = []
        self.metadata_records: list[YouTubeTranscriptMetadataRecord] = []

    async def save_transcript_record(
        self,
        record: YouTubeTranscriptRecord,
    ) -> YouTubeTranscriptMetadataRecord:
        self.records.append(record)
        metadata = _metadata_record(
            id=len(self.metadata_records) + 1,
            video_id=record.video_id,
            requested_languages=record.requested_languages,
            preserve_formatting=record.preserve_formatting,
            language_code=record.language_code,
        )
        self.metadata_records.append(metadata)
        return metadata

    async def find_transcript_metadata_for_request(
        self,
        *,
        video_id: str,
        requested_languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return next(
            (
                record
                for record in reversed(self.metadata_records)
                if record.video_id == video_id
                and record.requested_languages == requested_languages
                and record.preserve_formatting == preserve_formatting
            ),
            None,
        )

    async def list_transcript_metadata(
        self,
        filters: YouTubeTranscriptMetadataFilters,
    ) -> list[YouTubeTranscriptMetadataRecord]:
        return self.metadata_records

    async def get_transcript_metadata(
        self,
        transcript_id: int,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return next(
            (record for record in self.metadata_records if record.id == transcript_id),
            None,
        )

    async def update_transcript_notes(
        self,
        transcript_id: int,
        notes: str | None,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return None

    async def delete_transcript_metadata(self, transcript_id: int) -> bool:
        return False


class FakeOperationEventRecorder(OperationEventRecorderPort):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        if self.fail:
            raise RuntimeError("event recorder unavailable")
        self.events.append(event)


def test_channel_transcript_collect_creates_video_task_job_and_metadata() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos)

    response = asyncio.run(_collect(fakes))

    assert response["requestedCount"] == 1
    assert response["succeededCount"] == 1
    assert response["items"][0]["status"] == "succeeded"
    assert response["items"][0]["reason"] == "collected"
    assert response["items"][0]["transcriptId"] == 1
    assert fakes.pipeline_jobs.jobs[1].step == "transcript_collect_batch"
    assert fakes.pipeline_jobs.jobs[1].subject_type == "channel"
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert fakes.pipeline_jobs.jobs[2].step == "transcript_collect"
    assert fakes.pipeline_jobs.jobs[2].subject_type == "video"
    assert fakes.pipeline_jobs.jobs[2].parent_job_id == 1
    assert fakes.pipeline_jobs.attempts[1].status == "succeeded"
    assert fakes.pipeline_jobs.attempts[2].status == "succeeded"
    assert fakes.video_tasks.tasks[1].status == "succeeded"
    assert fakes.transcript_client.requests[0].video_id == YOUTUBE_VIDEO_ID
    assert [event.event_type for event in fakes.events.events] == [
        "transcript_collect.batch_requested",
        "transcript_collect.task_selected",
        "transcript_collect.task_running",
        "transcript_collect.task_succeeded",
        "transcript_collect.batch_succeeded",
    ]


def test_all_transcript_collect_creates_tasks_for_all_stored_videos() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels, channel_id=1)
    _seed_channel(fakes.channels, channel_id=2, handle="@other", name="Other")
    _seed_video(fakes.videos, video_id=1, channel_id=1, youtube_video_id=YOUTUBE_VIDEO_ID)
    _seed_video(fakes.videos, video_id=2, channel_id=2, youtube_video_id="def456GHI78")

    response = asyncio.run(_collect_all(fakes))

    assert "channelId" not in response
    assert response["requestedCount"] == 2
    assert response["succeededCount"] == 2
    assert [request.video_id for request in fakes.transcript_client.requests] == [
        "def456GHI78",
        YOUTUBE_VIDEO_ID,
    ]
    assert fakes.pipeline_jobs.jobs[1].step == "transcript_collect_batch"
    assert fakes.pipeline_jobs.jobs[1].subject_type == "all_videos"
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    parent_job_ids = {
        fakes.pipeline_jobs.jobs[2].parent_job_id,
        fakes.pipeline_jobs.jobs[3].parent_job_id,
    }
    assert parent_job_ids == {1}
    event = fakes.events.events[0]
    assert event.event_type == "transcript_collect.batch_requested"
    assert event.subject_type == "all_videos"
    assert event.job_id == 1
    assert event.channel_id is None
    assert event.metadata_json["selectedVideoCount"] == 2
    assert event.metadata_json["languages"] == ["ko", "en"]


def test_all_transcript_collect_reuses_metadata_and_skips_failed_without_retry() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels, channel_id=1)
    _seed_channel(fakes.channels, channel_id=2, handle="@other", name="Other")
    _seed_video(fakes.videos, video_id=1, channel_id=1, youtube_video_id=YOUTUBE_VIDEO_ID)
    _seed_video(fakes.videos, video_id=2, channel_id=2, youtube_video_id="def456GHI78")
    fakes.transcripts.metadata_records.append(
        _metadata_record(
            id=7,
            video_id=YOUTUBE_VIDEO_ID,
            requested_languages=("ko", "en"),
            preserve_formatting=False,
            language_code="ko",
        )
    )
    _seed_task(fakes.video_tasks, video_id=2, status="failed")

    response = asyncio.run(_collect_all(fakes))

    items = {item["videoId"]: item for item in response["items"]}
    assert response["requestedCount"] == 2
    assert response["succeededCount"] == 1
    assert response["skippedCount"] == 1
    assert items[1]["status"] == "succeeded"
    assert items[1]["reason"] == "existing_transcript"
    assert items[1]["transcriptId"] == 7
    assert items[2]["status"] == "skipped"
    assert items[2]["reason"] == "previously_failed"
    assert fakes.transcript_client.requests == []


def test_channel_transcript_collect_uses_existing_metadata_without_fetch() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos)
    fakes.transcripts.metadata_records.append(
        _metadata_record(
            id=7,
            video_id=YOUTUBE_VIDEO_ID,
            requested_languages=("ko", "en"),
            preserve_formatting=False,
            language_code="ko",
        )
    )

    response = asyncio.run(_collect(fakes))

    assert response["items"][0]["status"] == "succeeded"
    assert response["items"][0]["reason"] == "existing_transcript"
    assert response["items"][0]["transcriptId"] == 7
    assert fakes.transcript_client.requests == []
    assert fakes.pipeline_jobs.jobs[1].step == "transcript_collect_batch"
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert fakes.video_tasks.tasks[1].status == "succeeded"
    assert fakes.events.events[-2].event_type == "transcript_collect.task_succeeded"
    assert fakes.events.events[-2].metadata_json["reason"] == "existing_transcript"
    assert fakes.events.events[-1].event_type == "transcript_collect.batch_succeeded"


def test_channel_transcript_collect_skips_running_and_failed_until_retry_requested() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos)
    running = _seed_task(fakes.video_tasks, video_id=1, status="running")

    running_response = asyncio.run(_collect(fakes, expected_status=409))

    assert running_response == {"detail": "Transcript collection is already running."}

    fakes.video_tasks.tasks[running.id] = replace(
        running,
        status="failed",
        error_type="YouTubeTranscriptNotFound",
        error_message="No transcript.",
    )
    skipped_failed = asyncio.run(_collect(fakes))
    retried = asyncio.run(_collect(fakes, json={"retryFailed": True}))

    assert skipped_failed["items"][0]["status"] == "skipped"
    assert skipped_failed["items"][0]["reason"] == "previously_failed"
    assert retried["items"][0]["status"] == "succeeded"
    assert fakes.transcript_client.requests


def test_channel_transcript_collect_rejects_when_batch_is_running() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos)
    _seed_running_transcript_batch(fakes.pipeline_jobs)

    response = asyncio.run(_collect(fakes, expected_status=409))

    assert response == {"detail": "Transcript collection is already running."}
    assert fakes.transcript_client.requests == []


def test_channel_transcript_collect_marks_item_failed_and_continues() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos, video_id=1, youtube_video_id=YOUTUBE_VIDEO_ID)
    _seed_video(fakes.videos, video_id=2, youtube_video_id="xyz123DEF45")
    fakes.transcript_client.error = YouTubeTranscriptNotFound("No transcript.")

    response = asyncio.run(_collect(fakes, json={"limit": 2}))

    assert response["requestedCount"] == 2
    assert response["failedCount"] == 2
    assert {item["status"] for item in response["items"]} == {"failed"}
    assert all(task.status == "failed" for task in fakes.video_tasks.tasks.values())
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert all(
        job.status == "failed"
        for job in fakes.pipeline_jobs.jobs.values()
        if job.parent_job_id == 1
    )


def test_channel_transcript_collect_marks_timeout() -> None:
    fakes = _fakes(timeout_seconds=1)
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos)
    fakes.transcript_client.sleep_seconds = 2

    response = asyncio.run(_collect(fakes))

    assert response["timeoutCount"] == 1
    assert response["items"][0]["status"] == "timed_out"
    assert response["items"][0]["errorType"] == "TimeoutError"
    assert fakes.video_tasks.tasks[1].status == "timed_out"
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert fakes.pipeline_jobs.jobs[2].status == "failed"
    assert fakes.events.events[-2].event_type == "transcript_collect.task_timed_out"
    assert fakes.events.events[-1].event_type == "transcript_collect.batch_succeeded"


def test_channel_transcript_collect_sleeps_between_fetch_attempts() -> None:
    fakes = _fakes(delay_seconds=300)
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos, video_id=1, youtube_video_id=YOUTUBE_VIDEO_ID)
    _seed_video(fakes.videos, video_id=2, youtube_video_id="def456GHI78")
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        assert fakes.pipeline_jobs.jobs[1].step == "transcript_collect_batch"
        assert fakes.pipeline_jobs.jobs[1].status == "running"
        sleep_calls.append(seconds)

    response = asyncio.run(
        CollectChannelTranscriptTasksUseCase(
            channels=fakes.channels,
            videos=fakes.videos,
            video_tasks=fakes.video_tasks,
            pipeline_jobs=fakes.pipeline_jobs,
            transcripts=fakes.transcripts,
            fetch_transcript=FetchYouTubeTranscriptUseCase(
                fakes.transcript_client,
                fakes.storage,
                fakes.transcripts,
            ),
            timeout_seconds=600,
            concurrency_limit=1,
            delay_seconds=300,
            sleep=fake_sleep,
            events=fakes.events,
        ).execute(
            1,
            CollectChannelTranscriptTasksRequest(limit=2),
        )
    )

    assert response.requested_count == 2
    assert sleep_calls == [300]
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert [request.video_id for request in fakes.transcript_client.requests] == [
        "def456GHI78",
        YOUTUBE_VIDEO_ID,
    ]


def test_channel_video_tasks_list_and_openapi() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos)
    _seed_task(fakes.video_tasks, video_id=1, status="succeeded")

    response = asyncio.run(_list_tasks(fakes))
    schema = create_app().openapi()

    assert response[0]["youtubeVideoId"] == YOUTUBE_VIDEO_ID
    assert response[0]["status"] == "succeeded"
    assert schema["paths"]["/channels/{channel_id}/video-tasks"]["get"]["tags"] == [
        "video-tasks"
    ]
    assert schema["paths"]["/channels/{channel_id}/video-tasks/transcript-collect"]["post"][
        "tags"
    ] == ["video-tasks"]
    assert schema["paths"]["/video-tasks/transcript-collect"]["post"]["tags"] == [
        "video-tasks"
    ]
    assert schema["paths"]["/video-tasks/transcript-collect"]["post"]["responses"]["201"][
        "content"
    ]["application/json"]["schema"]["$ref"].endswith(
        "/CollectAllTranscriptTasksResponse"
    )


def test_transcript_collect_accepts_limit_above_twenty() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos)

    response = asyncio.run(
        _collect(
            fakes,
            json={
                "limit": 21,
                "languages": ["ko", "en"],
                "preserveFormatting": False,
                "retryFailed": False,
            },
        )
    )

    assert response["requestedCount"] == 1
    assert response["items"][0]["status"] == "succeeded"


def test_channel_video_tasks_missing_channel_returns_not_found() -> None:
    response = asyncio.run(_collect(_fakes(), expected_status=404))

    assert response == {"detail": "Channel not found."}


def test_transcript_collect_retry_reexecutes_failed_video_task_job() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos)
    task = _seed_task(fakes.video_tasks, video_id=1, status="failed")
    _seed_failed_transcript_collect_job(fakes.pipeline_jobs, task)

    response = asyncio.run(_retry(fakes, job_id=1))

    assert response["step"] == "transcript_collect"
    assert response["status"] == "succeeded"
    assert response["result"]["status"] == "succeeded"
    assert fakes.pipeline_jobs.attempts[2].status == "succeeded"
    assert fakes.video_tasks.tasks[task.id].status == "succeeded"
    assert fakes.transcript_client.requests[0].video_id == YOUTUBE_VIDEO_ID
    assert "pipeline_retry.succeeded" in {
        event.event_type for event in fakes.events.events
    }


def test_transcript_collect_retry_reports_failed_job_status() -> None:
    fakes = _fakes()
    _seed_channel(fakes.channels)
    _seed_video(fakes.videos)
    task = _seed_task(fakes.video_tasks, video_id=1, status="failed")
    _seed_failed_transcript_collect_job(fakes.pipeline_jobs, task)
    fakes.transcript_client.error = YouTubeTranscriptNotFound("No transcript.")

    response = asyncio.run(_retry(fakes, job_id=1))

    assert response["status"] == "failed"
    assert response["result"]["status"] == "failed"
    assert fakes.pipeline_jobs.attempts[2].status == "failed"
    assert fakes.video_tasks.tasks[task.id].status == "failed"
    assert fakes.events.events[-1].event_type == "pipeline_retry.failed"


async def _collect(
    fakes: _Fakes,
    *,
    json: dict[str, Any] | None = None,
    expected_status: int = 201,
) -> Any:
    app = _app(fakes)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/channels/1/video-tasks/transcript-collect",
            json=json,
        )

    assert response.status_code == expected_status, response.text
    return response.json()


async def _collect_all(
    fakes: _Fakes,
    *,
    json: dict[str, Any] | None = None,
    expected_status: int = 201,
) -> Any:
    app = _app(fakes)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/video-tasks/transcript-collect",
            json=json,
        )

    assert response.status_code == expected_status, response.text
    return response.json()


async def _retry(fakes: _Fakes, *, job_id: int, expected_status: int = 201) -> Any:
    app = _app(fakes)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(f"/pipeline/jobs/{job_id}/retry")

    assert response.status_code == expected_status, response.text
    return response.json()


async def _list_tasks(fakes: _Fakes, *, expected_status: int = 200) -> Any:
    app = _app(fakes)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/channels/1/video-tasks")

    assert response.status_code == expected_status, response.text
    return response.json()


class _Fakes:
    def __init__(self, *, timeout_seconds: int = 600, delay_seconds: int = 0) -> None:
        self.channels = FakeChannelRepository()
        self.videos = FakeVideoRepository()
        self.video_tasks = FakeVideoTaskRepository(self.videos)
        self.pipeline_jobs = FakePipelineJobRepository()
        self.transcript_client = FakeYouTubeTranscriptClient()
        self.storage = FakeYouTubeTranscriptStorage()
        self.transcripts = FakeYouTubeTranscriptRepository()
        self.events = FakeOperationEventRecorder()
        self.settings = CliSettings(
            transcript_collect_timeout_seconds=timeout_seconds,
            transcript_collect_concurrency_limit=1,
            transcript_collect_delay_seconds=delay_seconds,
        )


def _fakes(*, timeout_seconds: int = 600, delay_seconds: int = 0) -> _Fakes:
    return _Fakes(timeout_seconds=timeout_seconds, delay_seconds=delay_seconds)


def _app(fakes: _Fakes) -> Any:
    app = create_app()
    app.dependency_overrides[get_channel_repository] = lambda: fakes.channels
    app.dependency_overrides[get_video_repository] = lambda: fakes.videos
    app.dependency_overrides[get_video_task_repository] = lambda: fakes.video_tasks
    app.dependency_overrides[get_pipeline_job_repository] = lambda: fakes.pipeline_jobs
    app.dependency_overrides[get_youtube_data_client] = lambda: object()
    app.dependency_overrides[get_youtube_transcript_client] = lambda: fakes.transcript_client
    app.dependency_overrides[get_youtube_transcript_storage] = lambda: fakes.storage
    app.dependency_overrides[get_youtube_transcript_repository] = lambda: fakes.transcripts
    app.dependency_overrides[get_operation_event_recorder] = lambda: fakes.events
    app.dependency_overrides[get_settings] = lambda: fakes.settings
    return app


def _seed_channel(
    channels: FakeChannelRepository,
    *,
    channel_id: int = 1,
    handle: str = "@creator",
    name: str = "Creator",
) -> None:
    channels.channels[channel_id] = ChannelRecord(
        id=channel_id,
        streamer_id=1,
        handle=handle,
        name=name,
        youtube_channel_id=f"UC-test-{channel_id}",
        uploads_playlist_id=f"UU-test-{channel_id}",
        source_api_call_id=None,
        source_job_id=None,
    )


def _seed_video(
    videos: FakeVideoRepository,
    *,
    video_id: int = 1,
    channel_id: int = 1,
    youtube_video_id: str = YOUTUBE_VIDEO_ID,
) -> None:
    videos.videos[video_id] = VideoRecord(
        id=video_id,
        channel_id=channel_id,
        youtube_video_id=youtube_video_id,
        title=f"Video {video_id}",
        description="Description",
        published_at=NOW,
        duration="PT1M",
        thumbnail_url=None,
        source_listing_api_call_id=None,
        source_details_api_call_id=None,
        source_job_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _seed_task(
    video_tasks: FakeVideoTaskRepository,
    *,
    video_id: int,
    status: VideoTaskStatus,
) -> VideoTaskRecord:
    video = video_tasks.videos.videos.get(video_id)
    record = VideoTaskRecord(
        id=video_tasks.next_id,
        video_id=video_id,
        task_name="transcript_collect",
        task_version="v1",
        input_hash=_input_hash(
            video.youtube_video_id if video is not None else YOUTUBE_VIDEO_ID
        ),
        status=status,
        worker_id=None,
        timeout_seconds=600,
        job_id=None,
        job_attempt_id=None,
        output_transcript_id=None,
        output_json=None,
        error_type=None,
        error_message=None,
        started_at=None,
        completed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    video_tasks.tasks[record.id] = record
    video_tasks.next_id += 1
    return record


def _seed_failed_transcript_collect_job(
    pipeline_jobs: FakePipelineJobRepository,
    task: VideoTaskRecord,
) -> None:
    pipeline_jobs.jobs[1] = PipelineJobRecord(
        id=1,
        step="transcript_collect",
        status="failed",
        subject_type="video",
        subject_id=task.video_id,
        external_key=YOUTUBE_VIDEO_ID,
        input_json={
            "videoTaskId": task.id,
            "videoId": task.video_id,
            "youtubeVideoId": YOUTUBE_VIDEO_ID,
            "languages": ["ko", "en"],
            "preserveFormatting": False,
            "timeoutSeconds": 600,
            "taskVersion": "v1",
            "inputHash": task.input_hash,
        },
        input_hash=task.input_hash,
        parent_job_id=None,
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
    )
    pipeline_jobs.attempts[1] = PipelineJobAttemptRecord(
        id=1,
        job_id=1,
        attempt_no=1,
        status="failed",
        started_at=NOW,
        finished_at=NOW,
        worker_id=None,
        error_type="YouTubeTranscriptNotFound",
        error_message="No transcript.",
        output_json=None,
    )
    pipeline_jobs.next_job_id = 2
    pipeline_jobs.next_attempt_id = 2


def _seed_running_transcript_batch(pipeline_jobs: FakePipelineJobRepository) -> None:
    pipeline_jobs.jobs[1] = PipelineJobRecord(
        id=1,
        step="transcript_collect_batch",
        status="running",
        subject_type="channel",
        subject_id=1,
        external_key=None,
        input_json={
            "scope": "channel",
            "channelId": 1,
            "selectedVideoCount": 1,
        },
        input_hash="b" * 64,
        parent_job_id=None,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
    )
    pipeline_jobs.attempts[1] = PipelineJobAttemptRecord(
        id=1,
        job_id=1,
        attempt_no=1,
        status="running",
        started_at=NOW,
        finished_at=None,
        worker_id="manual-api",
        error_type=None,
        error_message=None,
        output_json=None,
    )
    pipeline_jobs.next_job_id = 2
    pipeline_jobs.next_attempt_id = 2


def _metadata_record(
    *,
    id: int,
    video_id: str,
    requested_languages: tuple[str, ...],
    preserve_formatting: bool,
    language_code: str,
) -> YouTubeTranscriptMetadataRecord:
    return YouTubeTranscriptMetadataRecord(
        id=id,
        video_id=video_id,
        language="Korean",
        language_code=language_code,
        is_generated=True,
        requested_languages=requested_languages,
        preserve_formatting=preserve_formatting,
        storage_bucket="raw",
        storage_object_name=f"youtube/transcripts/{video_id}.json",
        storage_uri=f"s3://raw/youtube/transcripts/{video_id}.json",
        response_sha256="a" * 64,
        segment_count=1,
        text_length=5,
        notes=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _input_hash(youtube_video_id: str) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(
            {
                "languages": ["ko", "en"],
                "preserveFormatting": False,
                "taskVersion": "v1",
                "youtubeVideoId": youtube_video_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
