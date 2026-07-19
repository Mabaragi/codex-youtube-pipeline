from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from codex_sdk_cli.application.operations.selection import ChannelVideos, SelectedVideos
from codex_sdk_cli.application.transcripts.commands import (
    TRANSCRIPT_COLLECT_TASK,
    CollectTranscriptsCommand,
    CollectTranscriptsUseCase,
)
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import CreateWorkItem
from codex_sdk_cli.application.workflows.commands import (
    ProcessToPublishCommand,
    StartProcessToPublishUseCase,
)
from codex_sdk_cli.domains.work.models import (
    JsonObject,
    WorkExecutionMode,
    WorkItem,
    WorkItemStatus,
)

from .ports import (
    AutomationScheduleStatePort,
    InlineWorkRunnerPort,
    PublishedPromptSnapshotPort,
    ScheduledChannel,
    ScheduledChannelReaderPort,
    SchedulerEvent,
    SchedulerEventRecorderPort,
    WorkflowAdmissionGuardPort,
    WorkflowCandidateReaderPort,
    WorkflowCandidateSnapshot,
)
from .quota import (
    WorkflowAllocationPlan,
    allocate_workflow_candidates,
    daily_quota_window,
)

Now = Callable[[], datetime]
VIDEO_COLLECT_TASK = "video_collect"
VIDEO_COLLECT_VERSION = "v2"


@dataclass(frozen=True, slots=True)
class PipelineSchedulerConfig:
    channel_interval_seconds: int
    transcript_limit: int
    no_transcript_recheck_interval_seconds: int
    no_transcript_limit: int
    video_collect_timeout_seconds: int = 600
    workflow_limit: int = 12
    daily_workflow_limit: int = 40
    channel_daily_minimum: int = 2
    quota_timezone: str = "Asia/Seoul"
    transcript_fallback_grace_seconds: int = 21600
    transcript_recheck_interval_seconds: int = 1800


@dataclass(frozen=True, slots=True)
class PipelineSchedulerChannelResult:
    channel_id: int
    status: str
    reason: str
    created_video_count: int = 0
    transcript_enqueued_count: int = 0
    transcript_reused_count: int = 0


@dataclass(frozen=True, slots=True)
class PipelineSchedulerTickResult:
    channel_count: int
    processed_channel_count: int
    skipped_channel_count: int
    failed_channel_count: int
    created_video_count: int
    transcript_enqueued_count: int
    transcript_reused_count: int
    no_transcript_recheck_count: int
    workflow_enqueued_count: int
    channels: tuple[PipelineSchedulerChannelResult, ...]


class RunPipelineSchedulerTickUseCase:
    def __init__(
        self,
        *,
        channels: ScheduledChannelReaderPort,
        collect_transcripts: CollectTranscriptsUseCase,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        inline_runner: InlineWorkRunnerPort,
        events: SchedulerEventRecorderPort,
        config: PipelineSchedulerConfig,
        start_workflows: StartProcessToPublishUseCase | None = None,
        workflow_candidates: WorkflowCandidateReaderPort | None = None,
        workflow_admission_guard: WorkflowAdmissionGuardPort | None = None,
        automation_state: AutomationScheduleStatePort | None = None,
        prompts: PublishedPromptSnapshotPort | None = None,
        now: Now | None = None,
    ) -> None:
        self._channels = channels
        self._collect_transcripts = collect_transcripts
        self._unit_of_work_factory = unit_of_work_factory
        self._inline_runner = inline_runner
        self._events = events
        self._config = config
        self._start_workflows = start_workflows
        self._workflow_candidates = workflow_candidates
        self._workflow_admission_guard = workflow_admission_guard
        self._automation_state = automation_state
        self._prompts = prompts
        self._now = now or (lambda: datetime.now(UTC))

    async def execute_once(self) -> PipelineSchedulerTickResult:
        now = _aware(self._now())
        if self._automation_state is not None:
            state = await self._automation_state.get_state(now=now)
            if state.runtime_state != "active":
                result = _tick_result([], 0, 0)
                await self._record(
                    "pipeline_scheduler.tick_skipped",
                    "info",
                    "Tick skipped while pipeline runtime is paused.",
                    metadata={"runtimeState": state.runtime_state},
                )
                return result
        await self._record("pipeline_scheduler.tick_started", "info", "Tick started.")
        try:
            result = await self._execute_once(now)
        except Exception as exc:
            await self._record(
                "pipeline_scheduler.tick_failed",
                "error",
                "Tick failed.",
                error=exc,
            )
            raise
        await self._record(
            "pipeline_scheduler.tick_succeeded",
            "info",
            "Tick finished.",
            metadata=_tick_metadata(result),
        )
        return result

    async def _execute_once(self, now: datetime) -> PipelineSchedulerTickResult:
        channels = await self._channels.list_scheduled_channels()
        results = [await self._process_channel(channel, now) for channel in channels]
        rechecked = (
            0
            if self._start_workflows is not None
            else await self._recheck_no_transcript(now)
        )
        workflows = await self._enqueue_workflows(now)
        return _tick_result(results, rechecked, workflows)

    async def _process_channel(
        self,
        channel: ScheduledChannel,
        now: datetime,
    ) -> PipelineSchedulerChannelResult:
        work_item, skip_reason = await self._prepare_video_collect(channel, now)
        if work_item is None:
            result = PipelineSchedulerChannelResult(
                channel_id=channel.id,
                status="skipped",
                reason=skip_reason or "not_due",
            )
            await self._record_channel("pipeline_scheduler.channel_skipped", channel, result)
            return result

        run = await self._inline_runner.run_inline(work_item.id)
        if not run.processed or run.succeeded is not True:
            result = PipelineSchedulerChannelResult(
                channel_id=channel.id,
                status="failed",
                reason="video_collect_failed",
            )
            await self._record_channel("pipeline_scheduler.channel_failed", channel, result)
            return result

        transcript_batch = (
            await self._collect_transcripts.execute(
                CollectTranscriptsCommand(
                    selection=ChannelVideos(channel.id, self._config.transcript_limit),
                    actor_type="system",
                )
            )
            if self._start_workflows is None
            else None
        )
        result = PipelineSchedulerChannelResult(
            channel_id=channel.id,
            status="processed",
            reason="processed",
            created_video_count=_created_count(run.output_json),
            transcript_enqueued_count=(transcript_batch.created_count if transcript_batch else 0),
            transcript_reused_count=(transcript_batch.reused_count if transcript_batch else 0),
        )
        await self._record_channel("pipeline_scheduler.channel_processed", channel, result)
        return result

    async def _enqueue_workflows(self, now: datetime) -> int:
        if (
            self._start_workflows is None
            or self._workflow_candidates is None
            or self._automation_state is None
            or self._prompts is None
        ):
            return 0
        admission_context = (
            self._workflow_admission_guard.hold()
            if self._workflow_admission_guard is not None
            else nullcontext()
        )
        async with admission_context:
            state = await self._automation_state.get_state(now=now)
            window = daily_quota_window(now, self._config.quota_timezone)
            snapshot = await self._workflow_candidates.read_snapshot(
                state=state,
                quota_started_at=window.started_at,
                quota_ends_at=window.ends_at,
            )
            if not _snapshot_has_candidates(snapshot) and state.mode == "backfill":
                await self._automation_state.mark_steady(now=now)
                state = await self._automation_state.get_state(now=now)
                snapshot = await self._workflow_candidates.read_snapshot(
                    state=state,
                    quota_started_at=window.started_at,
                    quota_ends_at=window.ends_at,
                )
            plan = allocate_workflow_candidates(
                snapshot,
                daily_limit=self._config.daily_workflow_limit,
                channel_minimum=self._config.channel_daily_minimum,
                tick_limit=self._config.workflow_limit,
                quota_date=window.quota_date,
            )
            if not plan.floor_feasible:
                await self._record(
                    "pipeline_scheduler.quota_floor_infeasible",
                    "warning",
                    "Daily channel minimum cannot fit within the workflow quota.",
                    metadata=_quota_metadata(
                        quota_date=window.quota_date.isoformat(),
                        daily_limit=self._config.daily_workflow_limit,
                        plan=plan,
                    ),
                )
            if not plan.candidates:
                return 0
            micro_prompt_id, timeline_prompt_id = await self._prompts.active_version_ids()
            result = await self._start_workflows.execute(
                ProcessToPublishCommand(
                    selection=SelectedVideos(tuple(item.id for item in plan.candidates)),
                    micro_prompt_version_id=micro_prompt_id,
                    timeline_prompt_version_id=timeline_prompt_id,
                    retry_failed=False,
                    transcript_fallback_mode="asr_after_grace",
                    transcript_fallback_grace_seconds=(
                        self._config.transcript_fallback_grace_seconds
                    ),
                    transcript_recheck_interval_seconds=(
                        self._config.transcript_recheck_interval_seconds
                    ),
                    asr_model="turbo",
                    asr_language="ko",
                    asr_device="cuda",
                    asr_compute_type="auto",
                    asr_chunk_minutes=15,
                    asr_overlap_seconds=3,
                    asr_beam_size=5,
                    asr_vad_filter=True,
                    asr_timeout_seconds=64800,
                    micro_timeout_seconds=14400,
                    timeline_timeout_seconds=7200,
                    actor_type="system",
                    automation_mode=state.mode,
                )
            )
            await self._record(
                "pipeline_scheduler.quota_admitted",
                "info",
                "Automatic workflows admitted under the daily quota.",
                metadata={
                    **_quota_metadata(
                        quota_date=window.quota_date.isoformat(),
                        daily_limit=self._config.daily_workflow_limit,
                        plan=plan,
                    ),
                    "createdWorkflowCount": result.created_count,
                    "reusedWorkflowCount": result.reused_count,
                },
            )
            return result.created_count

    async def _prepare_video_collect(
        self,
        channel: ScheduledChannel,
        now: datetime,
    ) -> tuple[WorkItem | None, str | None]:
        async with self._unit_of_work_factory() as unit_of_work:
            item = await unit_of_work.work_items.find_latest(
                task_type=VIDEO_COLLECT_TASK,
                subject_type="channel",
                subject_id=channel.id,
            )
            skip_reason = _video_collect_skip_reason(item, now, self._config)
            if skip_reason is not None:
                return None, skip_reason
            if item is None:
                item, _ = await unit_of_work.work_items.get_or_create(
                    _video_collect_item(channel, now, self._config)
                )
            else:
                item = await unit_of_work.work_items.reset_for_retry(
                    work_item_id=item.id,
                    now=now,
                    allow_succeeded=True,
                )
            await unit_of_work.commit()
        return item, None

    async def _recheck_no_transcript(self, now: datetime) -> int:
        cutoff = now - timedelta(
            seconds=self._config.no_transcript_recheck_interval_seconds
        )
        async with self._unit_of_work_factory() as unit_of_work:
            candidates = await unit_of_work.work_items.list_outcome_due(
                task_type=TRANSCRIPT_COLLECT_TASK,
                outcome_code="no_transcript",
                completed_before=cutoff,
                limit=self._config.no_transcript_limit,
            )
        video_ids = tuple(
            item.subject_id for item in candidates if item.subject_id is not None
        )
        if not video_ids:
            return 0
        result = await self._collect_transcripts.execute(
            CollectTranscriptsCommand(
                selection=SelectedVideos(video_ids),
                recheck_no_transcript=True,
                actor_type="system",
            )
        )
        return result.created_count

    async def _record_channel(
        self,
        event_type: str,
        channel: ScheduledChannel,
        result: PipelineSchedulerChannelResult,
    ) -> None:
        await self._events.record(
            SchedulerEvent(
                event_type=event_type,
                severity="error" if result.status == "failed" else "info",
                message=f"Scheduler channel {result.status}.",
                channel_id=channel.id,
                subject_type="channel",
                subject_id=channel.id,
                external_key=channel.youtube_channel_id,
                metadata_json=_channel_metadata(result),
            )
        )

    async def _record(
        self,
        event_type: str,
        severity: str,
        message: str,
        *,
        error: Exception | None = None,
        metadata: JsonObject | None = None,
    ) -> None:
        await self._events.record(
            SchedulerEvent(
                event_type=event_type,
                severity=severity,
                message=message,
                error_type=type(error).__name__ if error is not None else None,
                error_message=str(error) if error is not None else None,
                metadata_json=metadata,
            )
        )


def _video_collect_item(
    channel: ScheduledChannel,
    now: datetime,
    config: PipelineSchedulerConfig,
) -> CreateWorkItem:
    input_json: JsonObject = {
        "channelId": channel.id,
        "youtubeChannelId": channel.youtube_channel_id,
        "taskVersion": VIDEO_COLLECT_VERSION,
    }
    input_hash = _hash(input_json)
    return CreateWorkItem(
        task_type=VIDEO_COLLECT_TASK,
        subject_type="channel",
        subject_id=channel.id,
        external_key=channel.youtube_channel_id,
        task_version=VIDEO_COLLECT_VERSION,
        input_hash=input_hash,
        idempotency_key=f"{VIDEO_COLLECT_TASK}:channel:{channel.id}:{VIDEO_COLLECT_VERSION}",
        execution_mode=WorkExecutionMode.INLINE,
        timeout_seconds=config.video_collect_timeout_seconds,
        input_json=input_json,
        available_at=now,
    )


def _video_collect_skip_reason(
    item: WorkItem | None,
    now: datetime,
    config: PipelineSchedulerConfig,
) -> str | None:
    if item is None:
        return None
    if item.status in {WorkItemStatus.PENDING, WorkItemStatus.RUNNING}:
        return "video_collect_running"
    if item.status is not WorkItemStatus.SUCCEEDED or item.completed_at is None:
        return None
    cutoff = now - timedelta(seconds=config.channel_interval_seconds)
    return "channel_interval_not_due" if _aware(item.completed_at) > cutoff else None


def _created_count(output: JsonObject | None) -> int:
    value = output.get("createdCount") if output is not None else None
    return value if isinstance(value, int) else 0


def _tick_result(
    results: list[PipelineSchedulerChannelResult],
    rechecked: int,
    workflows: int = 0,
) -> PipelineSchedulerTickResult:
    return PipelineSchedulerTickResult(
        channel_count=len(results),
        processed_channel_count=sum(item.status == "processed" for item in results),
        skipped_channel_count=sum(item.status == "skipped" for item in results),
        failed_channel_count=sum(item.status == "failed" for item in results),
        created_video_count=sum(item.created_video_count for item in results),
        transcript_enqueued_count=sum(item.transcript_enqueued_count for item in results),
        transcript_reused_count=sum(item.transcript_reused_count for item in results),
        no_transcript_recheck_count=rechecked,
        workflow_enqueued_count=workflows,
        channels=tuple(results),
    )


def _channel_metadata(result: PipelineSchedulerChannelResult) -> JsonObject:
    return {
        "channelId": result.channel_id,
        "status": result.status,
        "reason": result.reason,
        "createdVideoCount": result.created_video_count,
        "transcriptEnqueuedCount": result.transcript_enqueued_count,
        "transcriptReusedCount": result.transcript_reused_count,
    }


def _tick_metadata(result: PipelineSchedulerTickResult) -> JsonObject:
    return {
        "channelCount": result.channel_count,
        "processedChannelCount": result.processed_channel_count,
        "skippedChannelCount": result.skipped_channel_count,
        "failedChannelCount": result.failed_channel_count,
        "createdVideoCount": result.created_video_count,
        "transcriptEnqueuedCount": result.transcript_enqueued_count,
        "transcriptReusedCount": result.transcript_reused_count,
        "noTranscriptRecheckCount": result.no_transcript_recheck_count,
        "workflowEnqueuedCount": result.workflow_enqueued_count,
    }


def _snapshot_has_candidates(snapshot: WorkflowCandidateSnapshot) -> bool:
    return any(channel.candidates for channel in snapshot.channels)


def _quota_metadata(
    *,
    quota_date: str,
    daily_limit: int,
    plan: WorkflowAllocationPlan,
) -> JsonObject:
    return {
        "quotaDate": quota_date,
        "dailyLimit": daily_limit,
        "admittedBeforeCount": plan.admitted_before_count,
        "admittedAfterCount": plan.admitted_after_count,
        "remainingAfterCount": plan.remaining_after_count,
        "floorFeasible": plan.floor_feasible,
        "channelAllocations": [
            {"channelId": channel_id, "count": count}
            for channel_id, count in plan.channel_allocations
        ],
    }


def _hash(values: JsonObject) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
