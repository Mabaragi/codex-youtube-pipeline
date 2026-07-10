from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from codex_sdk_cli.domains.channels.ports import ChannelRecord, ChannelRepositoryPort
from codex_sdk_cli.domains.operation_events.ports import (
    JsonObject,
    OperationEventCreate,
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.operation_events.recording import record_operation_event
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobListQuery,
    PipelineJobRepositoryPort,
    PipelineJobSummaryRecord,
)
from codex_sdk_cli.domains.video_tasks.constants import TRANSCRIPT_COLLECT_TASK_NAME
from codex_sdk_cli.domains.video_tasks.exceptions import TranscriptCollectAlreadyRunning
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRepositoryPort
from codex_sdk_cli.domains.video_tasks.schemas import (
    CollectAllTranscriptTasksRequest,
    CollectAllTranscriptTasksResponse,
    CollectChannelTranscriptTasksRequest,
    CollectChannelTranscriptTasksResponse,
)
from codex_sdk_cli.domains.video_tasks.use_cases import CollectChannelTranscriptTasksUseCase
from codex_sdk_cli.domains.videos.schemas import CollectChannelVideosResponse
from codex_sdk_cli.domains.videos.use_cases import (
    VIDEO_COLLECT_STEP,
    CollectChannelVideosUseCase,
)

Now = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class PipelineSchedulerConfig:
    channel_interval_seconds: int
    transcript_limit: int
    no_transcript_recheck_interval_seconds: int
    no_transcript_limit: int


@dataclass(frozen=True, slots=True)
class PipelineSchedulerChannelResult:
    channel_id: int
    status: str
    reason: str
    created_video_count: int = 0
    transcript_requested_count: int = 0
    transcript_succeeded_count: int = 0
    transcript_no_transcript_count: int = 0


@dataclass(frozen=True, slots=True)
class PipelineSchedulerTickResult:
    channel_count: int
    processed_channel_count: int
    skipped_channel_count: int
    failed_channel_count: int
    created_video_count: int
    transcript_requested_count: int
    transcript_succeeded_count: int
    transcript_no_transcript_count: int
    no_transcript_recheck_requested_count: int
    no_transcript_recheck_no_transcript_count: int
    channels: list[PipelineSchedulerChannelResult]


class RunPipelineSchedulerTickUseCase:
    def __init__(
        self,
        *,
        channels: ChannelRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        collect_videos: CollectChannelVideosUseCase,
        collect_transcripts: CollectChannelTranscriptTasksUseCase,
        events: OperationEventRecorderPort,
        config: PipelineSchedulerConfig,
        now: Now | None = None,
    ) -> None:
        self._channels = channels
        self._video_tasks = video_tasks
        self._pipeline_jobs = pipeline_jobs
        self._collect_videos = collect_videos
        self._collect_transcripts = collect_transcripts
        self._events = events
        self._config = config
        self._now = now or (lambda: datetime.now(UTC))

    async def execute_once(self) -> PipelineSchedulerTickResult:
        started_at = self._aware_now()
        await self._record_event(
            "pipeline_scheduler.tick_started",
            "info",
            "Pipeline scheduler tick started.",
            metadata_json={"startedAt": started_at.isoformat()},
        )
        try:
            result = await self._execute_once(started_at)
        except Exception as exc:
            await self._record_event(
                "pipeline_scheduler.tick_failed",
                "error",
                "Pipeline scheduler tick failed.",
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
            )
            raise
        await self._record_event(
            "pipeline_scheduler.tick_succeeded",
            "info",
            "Pipeline scheduler tick finished.",
            metadata_json=_tick_metadata(result),
        )
        return result

    async def _execute_once(self, now: datetime) -> PipelineSchedulerTickResult:
        channel_results: list[PipelineSchedulerChannelResult] = []
        channels = [
            channel
            for channel in await self._channels.list_channels()
            if channel.youtube_channel_id is not None
        ]
        for channel in channels:
            channel_results.append(await self._process_channel(channel, now))

        no_transcript_response = await self._recheck_no_transcript(now)
        return _tick_result(
            channel_count=len(channels),
            channel_results=channel_results,
            no_transcript_response=no_transcript_response,
        )

    async def _process_channel(
        self,
        channel: ChannelRecord,
        now: datetime,
    ) -> PipelineSchedulerChannelResult:
        if await self._has_running_video_collect(channel.id):
            result = PipelineSchedulerChannelResult(
                channel_id=channel.id,
                status="skipped",
                reason="video_collect_running",
            )
            await self._record_channel_skipped(channel, result)
            return result

        latest_succeeded = await self._latest_succeeded_video_collect(channel.id)
        if latest_succeeded is not None and not _is_due(
            latest_succeeded.job.completed_at or latest_succeeded.job.updated_at,
            now,
            self._config.channel_interval_seconds,
        ):
            result = PipelineSchedulerChannelResult(
                channel_id=channel.id,
                status="skipped",
                reason="channel_interval_not_due",
            )
            await self._record_channel_skipped(channel, result)
            return result

        try:
            collect_response = await self._collect_videos.execute(
                channel.id,
                actor_type="system",
            )
        except Exception as exc:
            result = PipelineSchedulerChannelResult(
                channel_id=channel.id,
                status="failed",
                reason=exc.__class__.__name__,
            )
            await self._record_channel_failed(channel, result, exc)
            return result

        try:
            transcript_response = await self._collect_transcripts.execute(
                channel.id,
                CollectChannelTranscriptTasksRequest.model_validate(
                    {
                        "limit": self._config.transcript_limit,
                        "collectNew": True,
                        "retryFailed": False,
                        "recheckNoTranscript": False,
                    }
                ),
                actor_type="system",
            )
        except TranscriptCollectAlreadyRunning:
            result = PipelineSchedulerChannelResult(
                channel_id=channel.id,
                status="skipped",
                reason="transcript_collect_running",
                created_video_count=collect_response.created_count,
            )
            await self._record_channel_skipped(channel, result)
            return result
        except Exception as exc:
            result = PipelineSchedulerChannelResult(
                channel_id=channel.id,
                status="failed",
                reason=exc.__class__.__name__,
            )
            await self._record_channel_failed(channel, result, exc)
            return result

        result = _channel_result(channel.id, collect_response, transcript_response)
        await self._record_event(
            "pipeline_scheduler.channel_processed",
            "info",
            "Pipeline scheduler processed a channel.",
            channel_id=channel.id,
            subject_type="channel",
            subject_id=channel.id,
            external_key=channel.youtube_channel_id,
            metadata_json=_channel_metadata(result),
        )
        return result

    async def _recheck_no_transcript(
        self,
        now: datetime,
    ) -> CollectAllTranscriptTasksResponse | None:
        cutoff = now - timedelta(
            seconds=self._config.no_transcript_recheck_interval_seconds
        )
        candidates = await self._video_tasks.list_no_transcript_tasks_due_for_recheck(
            task_name=TRANSCRIPT_COLLECT_TASK_NAME,
            completed_before=cutoff,
            limit=self._config.no_transcript_limit,
        )
        if not candidates:
            return None
        try:
            return await self._collect_transcripts.execute_selected(
                [candidate.video for candidate in candidates],
                CollectAllTranscriptTasksRequest.model_validate(
                    {
                        "collectNew": False,
                        "retryFailed": False,
                        "recheckNoTranscript": True,
                    }
                ),
                subject_type="scheduler",
                subject_id=None,
                external_key=None,
                actor_type="system",
            )
        except TranscriptCollectAlreadyRunning:
            await self._record_event(
                "pipeline_scheduler.no_transcript_recheck_skipped",
                "warning",
                "No-transcript recheck was skipped because transcript collection "
                "is already running.",
                metadata_json={"candidateCount": len(candidates)},
            )
            return None

    async def _has_running_video_collect(self, channel_id: int) -> bool:
        records = await self._pipeline_jobs.list_job_summaries(
            PipelineJobListQuery(
                step=VIDEO_COLLECT_STEP,
                status="running",
                subject_type="channel",
                subject_id=channel_id,
                limit=1,
            )
        )
        return bool(records)

    async def _latest_succeeded_video_collect(
        self,
        channel_id: int,
    ) -> PipelineJobSummaryRecord | None:
        records = await self._pipeline_jobs.list_job_summaries(
            PipelineJobListQuery(
                step=VIDEO_COLLECT_STEP,
                status="succeeded",
                subject_type="channel",
                subject_id=channel_id,
                limit=1,
            )
        )
        return records[0] if records else None

    async def _record_channel_skipped(
        self,
        channel: ChannelRecord,
        result: PipelineSchedulerChannelResult,
    ) -> None:
        await self._record_event(
            "pipeline_scheduler.channel_skipped",
            "info",
            "Pipeline scheduler skipped a channel.",
            channel_id=channel.id,
            subject_type="channel",
            subject_id=channel.id,
            external_key=channel.youtube_channel_id,
            metadata_json=_channel_metadata(result),
        )

    async def _record_channel_failed(
        self,
        channel: ChannelRecord,
        result: PipelineSchedulerChannelResult,
        exc: Exception,
    ) -> None:
        await self._record_event(
            "pipeline_scheduler.channel_failed",
            "error",
            "Pipeline scheduler failed while processing a channel.",
            channel_id=channel.id,
            subject_type="channel",
            subject_id=channel.id,
            external_key=channel.youtube_channel_id,
            error_type=exc.__class__.__name__,
            error_message=str(exc) or exc.__class__.__name__,
            metadata_json=_channel_metadata(result),
        )

    async def _record_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        *,
        metadata_json: JsonObject | None = None,
        channel_id: int | None = None,
        subject_type: str | None = None,
        subject_id: int | None = None,
        external_key: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity="error" if severity == "error" else "warning"
                if severity == "warning"
                else "info",
                message=message,
                actor_type="system",
                source="pipeline_scheduler",
                channel_id=channel_id,
                subject_type=subject_type,
                subject_id=subject_id,
                external_key=external_key,
                error_type=error_type,
                error_message=error_message,
                metadata_json=metadata_json or {},
            ),
        )

    def _aware_now(self) -> datetime:
        return _ensure_aware(self._now())


def _tick_result(
    *,
    channel_count: int,
    channel_results: list[PipelineSchedulerChannelResult],
    no_transcript_response: CollectAllTranscriptTasksResponse | None,
) -> PipelineSchedulerTickResult:
    return PipelineSchedulerTickResult(
        channel_count=channel_count,
        processed_channel_count=sum(
            result.status == "processed" for result in channel_results
        ),
        skipped_channel_count=sum(result.status == "skipped" for result in channel_results),
        failed_channel_count=sum(result.status == "failed" for result in channel_results),
        created_video_count=sum(result.created_video_count for result in channel_results),
        transcript_requested_count=sum(
            result.transcript_requested_count for result in channel_results
        ),
        transcript_succeeded_count=sum(
            result.transcript_succeeded_count for result in channel_results
        ),
        transcript_no_transcript_count=sum(
            result.transcript_no_transcript_count for result in channel_results
        ),
        no_transcript_recheck_requested_count=(
            no_transcript_response.requested_count
            if no_transcript_response is not None
            else 0
        ),
        no_transcript_recheck_no_transcript_count=(
            no_transcript_response.no_transcript_count
            if no_transcript_response is not None
            else 0
        ),
        channels=channel_results,
    )


def _channel_result(
    channel_id: int,
    collect_response: CollectChannelVideosResponse,
    transcript_response: CollectChannelTranscriptTasksResponse,
) -> PipelineSchedulerChannelResult:
    return PipelineSchedulerChannelResult(
        channel_id=channel_id,
        status="processed",
        reason="processed",
        created_video_count=collect_response.created_count,
        transcript_requested_count=transcript_response.requested_count,
        transcript_succeeded_count=transcript_response.succeeded_count,
        transcript_no_transcript_count=transcript_response.no_transcript_count,
    )


def _is_due(last_finished_at: datetime, now: datetime, interval_seconds: int) -> bool:
    return _ensure_aware(last_finished_at) <= now - timedelta(seconds=interval_seconds)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _channel_metadata(result: PipelineSchedulerChannelResult) -> JsonObject:
    return {
        "channelId": result.channel_id,
        "status": result.status,
        "reason": result.reason,
        "createdVideoCount": result.created_video_count,
        "transcriptRequestedCount": result.transcript_requested_count,
        "transcriptSucceededCount": result.transcript_succeeded_count,
        "transcriptNoTranscriptCount": result.transcript_no_transcript_count,
    }


def _tick_metadata(result: PipelineSchedulerTickResult) -> JsonObject:
    return {
        "channelCount": result.channel_count,
        "processedChannelCount": result.processed_channel_count,
        "skippedChannelCount": result.skipped_channel_count,
        "failedChannelCount": result.failed_channel_count,
        "createdVideoCount": result.created_video_count,
        "transcriptRequestedCount": result.transcript_requested_count,
        "transcriptSucceededCount": result.transcript_succeeded_count,
        "transcriptNoTranscriptCount": result.transcript_no_transcript_count,
        "noTranscriptRecheckRequestedCount": (
            result.no_transcript_recheck_requested_count
        ),
        "noTranscriptRecheckNoTranscriptCount": (
            result.no_transcript_recheck_no_transcript_count
        ),
    }
