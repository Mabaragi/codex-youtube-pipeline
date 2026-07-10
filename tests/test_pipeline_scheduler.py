from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

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
    PipelineJobCreate,
    PipelineJobDetailRecord,
    PipelineJobListQuery,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
    PipelineJobStatus,
    PipelineJobSummaryRecord,
)
from codex_sdk_cli.domains.pipeline_scheduler.use_cases import (
    PipelineSchedulerConfig,
    RunPipelineSchedulerTickUseCase,
)
from codex_sdk_cli.domains.video_tasks.ports import (
    VideoTaskCreate,
    VideoTaskListQuery,
    VideoTaskListRecord,
    VideoTaskRecord,
    VideoTaskRepositoryPort,
    VideoTaskWithVideoRecord,
)
from codex_sdk_cli.domains.video_tasks.schemas import (
    CollectAllTranscriptTasksRequest,
    CollectAllTranscriptTasksResponse,
    CollectChannelTranscriptTasksRequest,
    CollectChannelTranscriptTasksResponse,
)
from codex_sdk_cli.domains.video_tasks.use_cases import CollectChannelTranscriptTasksUseCase
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.videos.schemas import CollectChannelVideosResponse
from codex_sdk_cli.domains.videos.use_cases import CollectChannelVideosUseCase

NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def test_scheduler_skips_recent_video_collect_and_rechecks_no_transcript() -> None:
    channel = _channel(1)
    video = _video(10, channel_id=channel.id)
    channels = FakeChannelRepository([channel])
    pipeline_jobs = FakePipelineJobRepository(
        summaries=[
            _job_summary(
                job_id=1,
                step="video_collect",
                status="succeeded",
                channel_id=channel.id,
                completed_at=NOW - timedelta(hours=1),
            )
        ]
    )
    video_tasks = FakeVideoTaskRepository(
        due_no_transcript=[VideoTaskWithVideoRecord(task=_task(video.id), video=video)]
    )
    collect_videos = FakeCollectVideos()
    collect_transcripts = FakeCollectTranscripts()
    events = FakeEventRecorder()

    result = asyncio.run(_scheduler(
        channels=channels,
        pipeline_jobs=pipeline_jobs,
        video_tasks=video_tasks,
        collect_videos=collect_videos,
        collect_transcripts=collect_transcripts,
        events=events,
    ).execute_once())

    assert collect_videos.calls == []
    assert result.skipped_channel_count == 1
    assert result.no_transcript_recheck_requested_count == 1
    assert result.no_transcript_recheck_no_transcript_count == 1
    assert collect_transcripts.selected_requests[0].collect_new is False
    assert collect_transcripts.selected_requests[0].recheck_no_transcript is True
    assert [event.event_type for event in events.events] == [
        "pipeline_scheduler.tick_started",
        "pipeline_scheduler.channel_skipped",
        "pipeline_scheduler.tick_succeeded",
    ]


def test_scheduler_processes_due_channel_and_collects_transcripts() -> None:
    channel = _channel(1)
    channels = FakeChannelRepository([channel])
    pipeline_jobs = FakePipelineJobRepository(
        summaries=[
            _job_summary(
                job_id=1,
                step="video_collect",
                status="succeeded",
                channel_id=channel.id,
                completed_at=NOW - timedelta(days=2),
            )
        ]
    )
    collect_videos = FakeCollectVideos(created_count=2)
    collect_transcripts = FakeCollectTranscripts(
        channel_response=_channel_transcript_response(channel.id, requested=5, succeeded=2)
    )
    events = FakeEventRecorder()

    result = asyncio.run(_scheduler(
        channels=channels,
        pipeline_jobs=pipeline_jobs,
        collect_videos=collect_videos,
        collect_transcripts=collect_transcripts,
        events=events,
    ).execute_once())

    assert collect_videos.calls == [(channel.id, "system")]
    assert collect_transcripts.channel_calls == [(channel.id, 5, "system")]
    assert result.processed_channel_count == 1
    assert result.created_video_count == 2
    assert result.transcript_succeeded_count == 2
    assert "pipeline_scheduler.channel_processed" in {
        event.event_type for event in events.events
    }


def test_scheduler_continues_after_channel_failure() -> None:
    failed_channel = _channel(1)
    processed_channel = _channel(2)
    channels = FakeChannelRepository([failed_channel, processed_channel])
    collect_videos = FakeCollectVideos(fail_channel_ids={failed_channel.id})
    events = FakeEventRecorder()

    result = asyncio.run(_scheduler(
        channels=channels,
        collect_videos=collect_videos,
        events=events,
    ).execute_once())

    assert result.failed_channel_count == 1
    assert result.processed_channel_count == 1
    assert collect_videos.calls == [
        (failed_channel.id, "system"),
        (processed_channel.id, "system"),
    ]
    assert "pipeline_scheduler.channel_failed" in {event.event_type for event in events.events}


def test_pipeline_scheduler_worker_imports() -> None:
    import codex_sdk_cli.workers.pipeline_scheduler as pipeline_scheduler

    assert pipeline_scheduler.run is not None


def _scheduler(
    *,
    channels: FakeChannelRepository | None = None,
    pipeline_jobs: FakePipelineJobRepository | None = None,
    video_tasks: FakeVideoTaskRepository | None = None,
    collect_videos: FakeCollectVideos | None = None,
    collect_transcripts: FakeCollectTranscripts | None = None,
    events: FakeEventRecorder | None = None,
) -> RunPipelineSchedulerTickUseCase:
    return RunPipelineSchedulerTickUseCase(
        channels=channels or FakeChannelRepository([_channel(1)]),
        video_tasks=video_tasks or FakeVideoTaskRepository(),
        pipeline_jobs=pipeline_jobs or FakePipelineJobRepository(),
        collect_videos=cast(
            CollectChannelVideosUseCase,
            collect_videos or FakeCollectVideos(),
        ),
        collect_transcripts=cast(
            CollectChannelTranscriptTasksUseCase,
            collect_transcripts or FakeCollectTranscripts(),
        ),
        events=events or FakeEventRecorder(),
        config=PipelineSchedulerConfig(
            channel_interval_seconds=86400,
            transcript_limit=5,
            no_transcript_recheck_interval_seconds=604800,
            no_transcript_limit=2,
        ),
        now=lambda: NOW,
    )


class FakeChannelRepository(ChannelRepositoryPort):
    def __init__(self, channels: list[ChannelRecord]) -> None:
        self.channels = channels

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        raise NotImplementedError

    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        if streamer_id is None:
            return self.channels
        return [channel for channel in self.channels if channel.streamer_id == streamer_id]

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        return next((channel for channel in self.channels if channel.id == channel_id), None)

    async def get_channel_by_youtube_channel_id(
        self,
        youtube_channel_id: str,
    ) -> ChannelRecord | None:
        return next(
            (
                channel
                for channel in self.channels
                if channel.youtube_channel_id == youtube_channel_id
            ),
            None,
        )

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        raise NotImplementedError

    async def update_uploads_playlist_id(
        self,
        channel_id: int,
        uploads_playlist_id: str,
    ) -> ChannelRecord | None:
        raise NotImplementedError

    async def delete_channel(self, channel_id: int) -> bool:
        raise NotImplementedError


class FakePipelineJobRepository(PipelineJobRepositoryPort):
    def __init__(
        self,
        *,
        summaries: list[PipelineJobSummaryRecord] | None = None,
        running_channel_ids: set[int] | None = None,
    ) -> None:
        self.summaries = summaries or []
        self.running_channel_ids = running_channel_ids or set()

    async def create_job(self, job: PipelineJobCreate) -> PipelineJobRecord:
        raise NotImplementedError

    async def get_job(self, job_id: int) -> PipelineJobRecord | None:
        raise NotImplementedError

    async def list_job_summaries(
        self,
        query: PipelineJobListQuery,
    ) -> list[PipelineJobSummaryRecord]:
        if query.status == "running" and query.subject_id in self.running_channel_ids:
            return [
                _job_summary(
                    job_id=99,
                    step=query.step or "video_collect",
                    status="running",
                    channel_id=query.subject_id or 1,
                    completed_at=None,
                )
            ]
        rows = [
            summary
            for summary in self.summaries
            if (query.step is None or summary.job.step == query.step)
            and (query.status is None or summary.job.status == query.status)
            and (query.subject_type is None or summary.job.subject_type == query.subject_type)
            and (query.subject_id is None or summary.job.subject_id == query.subject_id)
        ]
        return rows[: query.limit]

    async def get_job_detail(self, job_id: int) -> PipelineJobDetailRecord | None:
        raise NotImplementedError

    async def create_attempt(
        self,
        *,
        job_id: int,
        worker_id: str | None = None,
    ) -> PipelineJobAttemptRecord:
        raise NotImplementedError

    async def mark_attempt_succeeded(
        self,
        attempt_id: int,
        *,
        output_json: JsonObject,
    ) -> PipelineJobAttemptRecord:
        raise NotImplementedError

    async def mark_attempt_failed(
        self,
        attempt_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> PipelineJobAttemptRecord:
        raise NotImplementedError

    async def mark_job_succeeded(self, job_id: int) -> PipelineJobRecord:
        raise NotImplementedError

    async def mark_job_failed(self, job_id: int) -> PipelineJobRecord:
        raise NotImplementedError

    async def mark_job_running(self, job_id: int) -> PipelineJobRecord:
        raise NotImplementedError


class FakeVideoTaskRepository(VideoTaskRepositoryPort):
    def __init__(
        self,
        *,
        due_no_transcript: list[VideoTaskWithVideoRecord] | None = None,
    ) -> None:
        self.due_no_transcript = due_no_transcript or []

    async def get_task(self, task_id: int) -> VideoTaskRecord | None:
        raise NotImplementedError

    async def get_task_for_input(
        self,
        *,
        video_id: int,
        task_name: str,
        task_version: str,
        input_hash: str,
    ) -> VideoTaskRecord | None:
        raise NotImplementedError

    async def get_or_create_task(self, task: VideoTaskCreate) -> VideoTaskRecord:
        raise NotImplementedError

    async def list_tasks(self, query: VideoTaskListQuery) -> list[VideoTaskListRecord]:
        raise NotImplementedError

    async def list_latest_succeeded_tasks(
        self,
        *,
        task_name: str,
        channel_id: int | None,
        limit: int,
    ) -> list[VideoTaskWithVideoRecord]:
        raise NotImplementedError

    async def list_no_transcript_tasks_due_for_recheck(
        self,
        *,
        task_name: str,
        completed_before: datetime,
        limit: int,
    ) -> list[VideoTaskWithVideoRecord]:
        return self.due_no_transcript[:limit]

    async def get_latest_succeeded_task_for_video(
        self,
        *,
        video_id: int,
        task_name: str,
    ) -> VideoTaskRecord | None:
        raise NotImplementedError

    async def get_latest_task_for_video(self, video_id: int) -> VideoTaskRecord | None:
        raise NotImplementedError

    async def count_running(self, *, task_name: str) -> int:
        raise NotImplementedError

    async def claim_next_pending_task(
        self,
        *,
        task_name: str,
        worker_id: str,
    ) -> VideoTaskRecord | None:
        raise NotImplementedError

    async def claim_next_pending_task_excluding_running_video(
        self,
        *,
        task_name: str,
        worker_id: str,
    ) -> VideoTaskRecord | None:
        raise NotImplementedError

    async def reset_task_to_pending(
        self,
        task_id: int,
        *,
        timeout_seconds: int,
        input_json: JsonObject,
    ) -> VideoTaskRecord:
        raise NotImplementedError

    async def attach_task_execution(
        self,
        task_id: int,
        *,
        job_id: int,
        job_attempt_id: int,
    ) -> VideoTaskRecord:
        raise NotImplementedError

    async def mark_task_running(
        self,
        task_id: int,
        *,
        worker_id: str,
        timeout_seconds: int,
        job_id: int,
        job_attempt_id: int,
    ) -> VideoTaskRecord:
        raise NotImplementedError

    async def mark_task_succeeded(
        self,
        task_id: int,
        *,
        output_transcript_id: int | None,
        output_json: JsonObject,
    ) -> VideoTaskRecord:
        raise NotImplementedError

    async def mark_task_failed(
        self,
        task_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        raise NotImplementedError

    async def mark_task_timed_out(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        raise NotImplementedError

    async def mark_task_no_transcript(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        raise NotImplementedError

    async def cancel_pending_tasks(
        self,
        task_ids: list[int],
        *,
        error_type: str,
        error_message: str,
    ) -> list[VideoTaskRecord]:
        raise NotImplementedError

    async def cancel_pending_tasks_for_video(
        self,
        *,
        video_id: int,
        task_names: tuple[str, ...],
        error_type: str,
        error_message: str,
    ) -> list[VideoTaskRecord]:
        raise NotImplementedError


class FakeCollectVideos:
    def __init__(
        self,
        *,
        created_count: int = 0,
        fail_channel_ids: set[int] | None = None,
    ) -> None:
        self.created_count = created_count
        self.fail_channel_ids = fail_channel_ids or set()
        self.calls: list[tuple[int, str]] = []

    async def execute(
        self,
        channel_id: int,
        *,
        actor_type: str = "manual_api",
    ) -> CollectChannelVideosResponse:
        self.calls.append((channel_id, actor_type))
        if channel_id in self.fail_channel_ids:
            raise RuntimeError("video collect failed")
        return _collect_videos_response(channel_id, self.created_count)


class FakeCollectTranscripts:
    def __init__(
        self,
        *,
        channel_response: CollectChannelTranscriptTasksResponse | None = None,
        selected_response: CollectAllTranscriptTasksResponse | None = None,
    ) -> None:
        self.channel_response = channel_response
        self.selected_response = selected_response
        self.channel_calls: list[tuple[int, int, str]] = []
        self.selected_requests: list[CollectAllTranscriptTasksRequest] = []

    async def execute(
        self,
        channel_id: int,
        request: CollectChannelTranscriptTasksRequest,
        *,
        actor_type: str = "manual_api",
    ) -> CollectChannelTranscriptTasksResponse:
        self.channel_calls.append((channel_id, request.limit, actor_type))
        return self.channel_response or _channel_transcript_response(channel_id)

    async def execute_selected(
        self,
        videos: list[VideoRecord],
        request: CollectAllTranscriptTasksRequest,
        *,
        subject_type: str,
        subject_id: int | None,
        external_key: str | None,
        actor_type: str = "manual_api",
    ) -> CollectAllTranscriptTasksResponse:
        del subject_type, subject_id, external_key, actor_type
        self.selected_requests.append(request)
        return self.selected_response or _all_transcript_response(
            requested=len(videos),
            no_transcript=len(videos),
        )


class FakeEventRecorder(OperationEventRecorderPort):
    def __init__(self) -> None:
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.events.append(event)


def _channel(channel_id: int) -> ChannelRecord:
    return ChannelRecord(
        id=channel_id,
        streamer_id=1,
        handle=f"@channel-{channel_id}",
        name=f"Channel {channel_id}",
        youtube_channel_id=f"UC-{channel_id}",
        uploads_playlist_id=f"UU-{channel_id}",
        source_api_call_id=None,
        source_job_id=None,
    )


def _video(video_id: int, *, channel_id: int) -> VideoRecord:
    return VideoRecord(
        id=video_id,
        channel_id=channel_id,
        youtube_video_id=f"yt-{video_id}",
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


def _task(video_id: int) -> VideoTaskRecord:
    return VideoTaskRecord(
        id=video_id + 100,
        video_id=video_id,
        task_name="transcript_collect",
        task_version="v1",
        input_hash="a" * 64,
        status="no_transcript",
        worker_id=None,
        timeout_seconds=600,
        job_id=None,
        job_attempt_id=None,
        output_transcript_id=None,
        output_json=None,
        error_type="YouTubeTranscriptNotFound",
        error_message="No transcript.",
        started_at=NOW - timedelta(days=8),
        completed_at=NOW - timedelta(days=8),
        created_at=NOW - timedelta(days=8),
        updated_at=NOW - timedelta(days=8),
    )


def _job_summary(
    *,
    job_id: int,
    step: str,
    status: PipelineJobStatus,
    channel_id: int,
    completed_at: datetime | None,
) -> PipelineJobSummaryRecord:
    return PipelineJobSummaryRecord(
        job=PipelineJobRecord(
            id=job_id,
            step=step,
            status=status,
            subject_type="channel",
            subject_id=channel_id,
            external_key=f"UC-{channel_id}",
            input_json={"channelId": channel_id},
            input_hash="0" * 64,
            parent_job_id=None,
            created_at=NOW - timedelta(days=2),
            updated_at=completed_at or NOW,
            completed_at=completed_at,
        ),
        latest_attempt_id=job_id,
        latest_attempt_status="running" if status == "running" else "succeeded",
        attempt_count=1,
    )


def _collect_videos_response(
    channel_id: int,
    created_count: int,
) -> CollectChannelVideosResponse:
    return CollectChannelVideosResponse.model_validate(
        {
            "channelId": channel_id,
            "youtubeChannelId": f"UC-{channel_id}",
            "jobId": 10 + channel_id,
            "jobAttemptId": 20 + channel_id,
            "createdCount": created_count,
            "createdVideoIds": list(range(1, created_count + 1)),
            "firstExistingYoutubeVideoId": None,
            "stoppedReason": "no_next_page",
            "pagesFetched": 1,
            "listingApiCallIds": [1],
            "videoDetailsApiCallIds": [2],
            "skippedMissingDetailsYoutubeVideoIds": [],
        }
    )


def _channel_transcript_response(
    channel_id: int,
    *,
    requested: int = 0,
    succeeded: int = 0,
) -> CollectChannelTranscriptTasksResponse:
    return CollectChannelTranscriptTasksResponse.model_validate(
        {
            "channelId": channel_id,
            "requestedCount": requested,
            "succeededCount": succeeded,
            "skippedCount": 0,
            "failedCount": 0,
            "timeoutCount": 0,
            "noTranscriptCount": 0,
            "items": [],
        }
    )


def _all_transcript_response(
    *,
    requested: int,
    no_transcript: int,
) -> CollectAllTranscriptTasksResponse:
    return CollectAllTranscriptTasksResponse.model_validate(
        {
            "requestedCount": requested,
            "succeededCount": 0,
            "skippedCount": 0,
            "failedCount": 0,
            "timeoutCount": 0,
            "noTranscriptCount": no_transcript,
            "items": [],
        }
    )
