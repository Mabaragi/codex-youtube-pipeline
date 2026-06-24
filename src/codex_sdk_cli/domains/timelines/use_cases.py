from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import cast, get_args

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainKnowledgePromptEntryRecord,
    DomainKnowledgeRepositoryPort,
)
from codex_sdk_cli.domains.micro_events.constants import MICRO_EVENT_EXTRACT_TASK_NAME
from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventCandidateRecord,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionRepositoryPort,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventActorType,
    OperationEventCreate,
    OperationEventRecorderPort,
    OperationEventSeverity,
)
from codex_sdk_cli.domains.operation_events.recording import record_operation_event
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobCreate,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
)
from codex_sdk_cli.domains.streamers.ports import StreamerRepositoryPort
from codex_sdk_cli.domains.video_tasks.constants import (
    TIMELINE_COMPOSE_TASK_NAME,
    TIMELINE_COMPOSE_TASK_VERSION,
    TIMELINE_COMPOSE_WORKER_ID,
)
from codex_sdk_cli.domains.video_tasks.exceptions import VideoTaskRetryNotAllowed
from codex_sdk_cli.domains.video_tasks.ports import (
    VideoTaskCreate,
    VideoTaskRecord,
    VideoTaskRepositoryPort,
    VideoTaskWithVideoRecord,
)
from codex_sdk_cli.domains.videos.exceptions import VideoNotFound
from codex_sdk_cli.domains.videos.ports import VideoRecord, VideoRepositoryPort
from codex_sdk_cli.settings import CodexModelChoice, ReasoningEffortChoice

from .constants import (
    TIMELINE_COMPOSE_BATCH_SCAN_LIMIT,
    TIMELINE_COMPOSE_DEFAULT_COPY_STYLE,
    TIMELINE_COMPOSE_PROMPT_VERSION,
)
from .exceptions import (
    TimelineCompositionNotFound,
    TimelineCompositionOutputInvalid,
    TimelineCompositionPreconditionFailed,
)
from .ports import (
    CopyStyle,
    TimelineBlockCreate,
    TimelineBlockType,
    TimelineComposeRequest,
    TimelineComposeResult,
    TimelineComposerPort,
    TimelineCompositionCreate,
    TimelineCompositionRecord,
    TimelineCompositionRepositoryPort,
    TimelineContentKind,
    TimelineEpisodeCreate,
    TimelineReviewFlagCreate,
    TimelineReviewFlagType,
    TimelineTopicClusterCreate,
    TimelineVisibility,
)
from .schemas import (
    TimelineBlockResponse,
    TimelineComposeEnqueueItemResponse,
    TimelineComposeEnqueueRequest,
    TimelineComposeEnqueueResponse,
    TimelineCompositionResponse,
    TimelineEpisodeResponse,
    TimelineReviewFlagResponse,
    TimelineTopicClusterResponse,
)

TIMELINE_COMPOSE_WORKER_ID_PREFIX = "timeline-compose-worker:"


@dataclass(frozen=True, slots=True)
class _PreparedTimelineCompose:
    video: VideoRecord
    source_task: VideoTaskRecord
    source_detail: MicroEventExtractionDetailRecord
    input_hash: str
    input_json: JsonObject
    model: CodexModelChoice
    reasoning_effort: ReasoningEffortChoice
    copy_style: CopyStyle


@dataclass(slots=True)
class _EnqueueCounters:
    scanned_count: int = 0
    enqueued_count: int = 0
    already_pending_count: int = 0
    already_running_count: int = 0
    already_succeeded_count: int = 0
    retry_queued_count: int = 0
    regenerated_count: int = 0
    failed_skipped_count: int = 0
    ineligible_count: int = 0


@dataclass(frozen=True, slots=True)
class _ComposerInput:
    video: VideoRecord
    streamer_name: str | None
    domain_entries: list[DomainKnowledgePromptEntryRecord]
    source_task: VideoTaskRecord
    source_detail: MicroEventExtractionDetailRecord
    micro_events: list[MicroEventCandidateRecord]
    synthetic_id_by_candidate_id: dict[int, str]
    candidate_id_by_synthetic_id: dict[str, int]
    input_json: JsonObject
    input_hash: str
    model: CodexModelChoice
    reasoning_effort: ReasoningEffortChoice
    copy_style: CopyStyle


class ComposeTimelineUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        channels: ChannelRepositoryPort,
        streamers: StreamerRepositoryPort,
        domain_knowledge: DomainKnowledgeRepositoryPort,
        micro_events: MicroEventExtractionRepositoryPort,
        timelines: TimelineCompositionRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        composer: TimelineComposerPort,
        timeout_seconds: int,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
        events: OperationEventRecorderPort,
    ) -> None:
        self._videos = videos
        self._video_tasks = video_tasks
        self._channels = channels
        self._streamers = streamers
        self._domain_knowledge = domain_knowledge
        self._micro_events = micro_events
        self._timelines = timelines
        self._pipeline_jobs = pipeline_jobs
        self._composer = composer
        self._timeout_seconds = timeout_seconds
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._events = events

    async def enqueue(
        self,
        request: TimelineComposeEnqueueRequest,
    ) -> TimelineComposeEnqueueResponse:
        counters = _EnqueueCounters()
        items: list[TimelineComposeEnqueueItemResponse] = []
        if request.target == "selected_videos":
            for video_id in request.video_ids[: request.limit]:
                counters.scanned_count += 1
                items.append(await self._enqueue_video_id(video_id, request, counters))
            return _enqueue_response(request, counters, items)

        candidates = await self._video_tasks.list_latest_succeeded_tasks(
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
            channel_id=request.channel_id,
            limit=TIMELINE_COMPOSE_BATCH_SCAN_LIMIT,
        )
        for candidate in candidates:
            counters.scanned_count += 1
            action = await self._batch_candidate_action(candidate, request)
            if action == "skip":
                continue
            item = await self._enqueue_video(candidate.video, request, counters)
            if request.target == "next_eligible" and item.reason in {
                "already_pending",
                "already_running",
                "already_succeeded",
                "failed_skipped",
                "ineligible",
            }:
                continue
            items.append(item)
            if len(items) >= request.limit:
                break
        return _enqueue_response(request, counters, items)

    async def get_latest(self, video_id: int) -> TimelineCompositionResponse:
        if await self._videos.get_video(video_id) is None:
            raise VideoNotFound("Video not found.")
        record = await self._timelines.get_latest_succeeded_composition(video_id=video_id)
        if record is None:
            raise TimelineCompositionNotFound("Timeline composition not found.")
        return _timeline_response(record)

    async def get_detail(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> TimelineCompositionResponse:
        if await self._videos.get_video(video_id) is None:
            raise VideoNotFound("Video not found.")
        record = await self._timelines.get_composition(
            video_id=video_id,
            video_task_id=video_task_id,
        )
        if record is None:
            raise TimelineCompositionNotFound("Timeline composition not found.")
        return _timeline_response(record)

    async def execute_claimed_task(
        self,
        task: VideoTaskRecord,
        *,
        worker_id: str,
    ) -> TimelineCompositionResponse:
        if task.task_name != TIMELINE_COMPOSE_TASK_NAME or task.status != "running":
            raise VideoTaskRetryNotAllowed("Only claimed timeline tasks can be executed.")
        input_json = task.input_json or {}
        if not input_json:
            await self._video_tasks.mark_task_failed(
                task.id,
                error_type="TimelineComposeInputMissing",
                error_message="Queued timeline task is missing input_json.",
            )
            raise VideoTaskRetryNotAllowed("Queued timeline task is missing input_json.")
        job_input_json = {**input_json, "videoTaskId": task.id}
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step=TIMELINE_COMPOSE_TASK_NAME,
                status="running",
                subject_type="video",
                subject_id=_required_int(job_input_json, "videoId"),
                external_key=_str_output(job_input_json, "youtubeVideoId"),
                input_json=job_input_json,
                input_hash=_required_str(job_input_json, "inputHash"),
            )
        )
        attempt = await self._pipeline_jobs.create_attempt(
            job_id=job.id,
            worker_id=worker_id,
        )
        task = await self._video_tasks.attach_task_execution(
            task.id,
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        composer_input = await self._load_composer_input(input_json)
        await self._record_task_event(
            "timeline_compose.task_running",
            "info",
            "Timeline compose task started running.",
            task=task,
            video=composer_input.video,
            metadata_json={"attemptId": attempt.id, "workerId": worker_id},
        )
        return await self._execute_job_attempt(
            job,
            attempt,
            task=task,
            composer_input=composer_input,
            timeout_seconds=_int_output(input_json, "timeoutSeconds") or task.timeout_seconds,
        )

    async def execute_retry_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        task_id = _required_int(job.input_json, "videoTaskId")
        task = await self._video_tasks.get_task(task_id)
        if task is None:
            raise VideoTaskRetryNotAllowed("Video task not found.")
        if task.task_name != TIMELINE_COMPOSE_TASK_NAME:
            raise VideoTaskRetryNotAllowed("Pipeline job is not a timeline task.")
        if task.status not in {"failed", "timed_out"}:
            raise VideoTaskRetryNotAllowed("Only failed timeline tasks can be retried.")
        composer_input = await self._load_composer_input(job.input_json)
        task = await self._video_tasks.mark_task_running(
            task.id,
            worker_id=TIMELINE_COMPOSE_WORKER_ID,
            timeout_seconds=_required_int(job.input_json, "timeoutSeconds"),
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        response = await self._execute_job_attempt(
            job,
            attempt,
            task=task,
            composer_input=composer_input,
            timeout_seconds=_required_int(job.input_json, "timeoutSeconds"),
        )
        return response.output_json

    async def _enqueue_video_id(
        self,
        video_id: int,
        request: TimelineComposeEnqueueRequest,
        counters: _EnqueueCounters,
    ) -> TimelineComposeEnqueueItemResponse:
        video = await self._videos.get_video(video_id)
        if video is None:
            counters.ineligible_count += 1
            return _enqueue_item(
                video_id=video_id,
                youtube_video_id=None,
                task=None,
                status="skipped",
                reason="video_not_found",
                source_task_id=None,
                model=request.model,
                reasoning_effort=request.reasoning_effort,
                copy_style=request.copy_style,
                error_type="VideoNotFound",
                error_message="Video not found.",
            )
        return await self._enqueue_video(video, request, counters)

    async def _enqueue_video(
        self,
        video: VideoRecord,
        request: TimelineComposeEnqueueRequest,
        counters: _EnqueueCounters,
    ) -> TimelineComposeEnqueueItemResponse:
        try:
            prepared = await self._prepare(video, request)
        except TimelineCompositionPreconditionFailed as exc:
            counters.ineligible_count += 1
            return _enqueue_item(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                task=None,
                status="skipped",
                reason="ineligible",
                source_task_id=None,
                model=request.model,
                reasoning_effort=request.reasoning_effort,
                copy_style=request.copy_style,
                error_type=exc.__class__.__name__,
                error_message=exc.message,
            )

        existing = await self._video_tasks.get_task_for_input(
            video_id=video.id,
            task_name=TIMELINE_COMPOSE_TASK_NAME,
            task_version=TIMELINE_COMPOSE_TASK_VERSION,
            input_hash=prepared.input_hash,
        )
        if existing is None:
            task = await self._video_tasks.get_or_create_task(
                VideoTaskCreate(
                    video_id=video.id,
                    task_name=TIMELINE_COMPOSE_TASK_NAME,
                    task_version=TIMELINE_COMPOSE_TASK_VERSION,
                    input_hash=prepared.input_hash,
                    timeout_seconds=self._timeout_seconds,
                    input_json=prepared.input_json,
                    status="pending",
                )
            )
            counters.enqueued_count += 1
            await self._record_task_event(
                "timeline_compose.task_enqueued",
                "info",
                "Timeline compose task enqueued.",
                task=task,
                video=video,
                metadata_json=prepared.input_json,
            )
            return _enqueue_item(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                task=task,
                status="pending",
                reason="enqueued",
                source_task_id=prepared.source_task.id,
                model=prepared.model,
                reasoning_effort=prepared.reasoning_effort,
                copy_style=prepared.copy_style,
            )
        return await self._handle_existing_task(video, existing, prepared, request, counters)

    async def _handle_existing_task(
        self,
        video: VideoRecord,
        task: VideoTaskRecord,
        prepared: _PreparedTimelineCompose,
        request: TimelineComposeEnqueueRequest,
        counters: _EnqueueCounters,
    ) -> TimelineComposeEnqueueItemResponse:
        if task.status == "pending":
            counters.already_pending_count += 1
            return _enqueue_item(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                task=task,
                status="pending",
                reason="already_pending",
                source_task_id=prepared.source_task.id,
                model=prepared.model,
                reasoning_effort=prepared.reasoning_effort,
                copy_style=prepared.copy_style,
            )
        if task.status == "running":
            counters.already_running_count += 1
            return _enqueue_item(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                task=task,
                status="running",
                reason="already_running",
                source_task_id=prepared.source_task.id,
                model=prepared.model,
                reasoning_effort=prepared.reasoning_effort,
                copy_style=prepared.copy_style,
            )
        if task.status == "succeeded" and not request.regenerate_succeeded:
            counters.already_succeeded_count += 1
            return _enqueue_item(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                task=task,
                status="succeeded",
                reason="already_succeeded",
                source_task_id=prepared.source_task.id,
                model=prepared.model,
                reasoning_effort=prepared.reasoning_effort,
                copy_style=prepared.copy_style,
            )
        if task.status in {"failed", "timed_out"} and not request.retry_failed:
            counters.failed_skipped_count += 1
            return _enqueue_item(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                task=task,
                status=task.status,
                reason="failed_skipped",
                source_task_id=prepared.source_task.id,
                model=prepared.model,
                reasoning_effort=prepared.reasoning_effort,
                copy_style=prepared.copy_style,
                error_type=task.error_type,
                error_message=task.error_message,
            )
        reset = await self._video_tasks.reset_task_to_pending(
            task.id,
            timeout_seconds=self._timeout_seconds,
            input_json=prepared.input_json,
        )
        if task.status == "succeeded":
            counters.regenerated_count += 1
            reason = "regenerated"
        else:
            counters.retry_queued_count += 1
            reason = "retry_queued"
        return _enqueue_item(
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
            task=reset,
            status="pending",
            reason=reason,
            source_task_id=prepared.source_task.id,
            model=prepared.model,
            reasoning_effort=prepared.reasoning_effort,
            copy_style=prepared.copy_style,
        )

    async def _prepare(
        self,
        video: VideoRecord,
        request: TimelineComposeEnqueueRequest,
    ) -> _PreparedTimelineCompose:
        source_task = await self._video_tasks.get_latest_succeeded_task_for_video(
            video_id=video.id,
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
        )
        if source_task is None:
            raise TimelineCompositionPreconditionFailed(
                "Succeeded micro-event extraction is required."
            )
        source_detail = await self._micro_events.get_extraction(
            video_id=video.id,
            video_task_id=source_task.id,
        )
        if source_detail is None or _micro_event_count(source_detail) == 0:
            raise TimelineCompositionPreconditionFailed(
                "Micro-event extraction has no micro-events."
            )
        model = request.model or self._model
        reasoning_effort = request.reasoning_effort or self._reasoning_effort
        source_fingerprint = _source_micro_event_fingerprint(source_detail)
        input_hash = _task_input_hash(
            video=video,
            source_task=source_task,
            source_fingerprint=source_fingerprint,
            copy_style=request.copy_style,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        input_json = _task_input_json(
            video=video,
            source_task=source_task,
            source_fingerprint=source_fingerprint,
            input_hash=input_hash,
            copy_style=request.copy_style,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=self._timeout_seconds,
        )
        return _PreparedTimelineCompose(
            video=video,
            source_task=source_task,
            source_detail=source_detail,
            input_hash=input_hash,
            input_json=input_json,
            model=model,
            reasoning_effort=reasoning_effort,
            copy_style=request.copy_style,
        )

    async def _load_composer_input(self, input_json: JsonObject) -> _ComposerInput:
        video_id = _required_int(input_json, "videoId")
        source_task_id = _required_int(input_json, "sourceMicroEventTaskId")
        video = await self._videos.get_video(video_id)
        if video is None:
            raise VideoNotFound("Video not found.")
        source_task = await self._video_tasks.get_task(source_task_id)
        if source_task is None:
            raise TimelineCompositionPreconditionFailed(
                "Source micro-event task not found."
            )
        source_detail = await self._micro_events.get_extraction(
            video_id=video.id,
            video_task_id=source_task.id,
        )
        if source_detail is None:
            raise TimelineCompositionPreconditionFailed(
                "Source micro-event extraction not found."
            )
        micro_events = _flatten_micro_events(source_detail)
        if not micro_events:
            raise TimelineCompositionPreconditionFailed("Micro-events are required.")
        channel = await self._channels.get_channel(video.channel_id)
        streamer_name = None
        streamer_id = channel.streamer_id if channel is not None else None
        if streamer_id is not None:
            streamer = await self._streamers.get_streamer(streamer_id)
            streamer_name = streamer.name if streamer is not None else None
        domain_entries = await self._domain_knowledge.list_prompt_entries_for_streamer(
            streamer_id
        )
        synthetic_id_by_candidate_id = {
            candidate.id: f"me_{index:04d}"
            for index, candidate in enumerate(micro_events, start=1)
        }
        candidate_id_by_synthetic_id = {
            value: key for key, value in synthetic_id_by_candidate_id.items()
        }
        return _ComposerInput(
            video=video,
            streamer_name=streamer_name,
            domain_entries=domain_entries,
            source_task=source_task,
            source_detail=source_detail,
            micro_events=micro_events,
            synthetic_id_by_candidate_id=synthetic_id_by_candidate_id,
            candidate_id_by_synthetic_id=candidate_id_by_synthetic_id,
            input_json=input_json,
            input_hash=_required_str(input_json, "inputHash"),
            model=_model_output(input_json) or self._model,
            reasoning_effort=_reasoning_effort_output(input_json) or self._reasoning_effort,
            copy_style=cast(
                CopyStyle,
                _str_output(input_json, "copyStyle")
                or TIMELINE_COMPOSE_DEFAULT_COPY_STYLE,
            ),
        )

    async def _execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        *,
        task: VideoTaskRecord,
        composer_input: _ComposerInput,
        timeout_seconds: int,
    ) -> TimelineCompositionResponse:
        try:
            await self._timelines.delete_composition(task.id)
            prompt = _timeline_prompt(composer_input)
            result = await asyncio.wait_for(
                self._composer.compose(
                    TimelineComposeRequest(
                        prompt=prompt,
                        video_id=composer_input.video.id,
                        video_task_id=task.id,
                        job_id=job.id,
                        job_attempt_id=attempt.id,
                        source_micro_event_task_id=composer_input.source_task.id,
                        model=composer_input.model,
                        reasoning_effort=composer_input.reasoning_effort,
                    )
                ),
                timeout=timeout_seconds,
            )
            create = _composition_create(
                composer_input,
                result,
                task=task,
                job=job,
                attempt=attempt,
            )
        except TimeoutError:
            message = f"Timeline compose exceeded {timeout_seconds} seconds."
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type="TimeoutError",
                error_message=message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            updated = await self._video_tasks.mark_task_timed_out(
                task.id,
                error_message=message,
                output_json=_attempt_output_json(composer_input, job=job, attempt=attempt),
            )
            await self._record_task_event(
                "timeline_compose.task_timed_out",
                "error",
                "Timeline compose task timed out.",
                task=updated,
                video=composer_input.video,
                reason="timeout",
                error_type="TimeoutError",
                error_message=message,
            )
            raise
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=error_type,
                error_message=error_message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            updated = await self._video_tasks.mark_task_failed(
                task.id,
                error_type=error_type,
                error_message=error_message,
                output_json=_attempt_output_json(composer_input, job=job, attempt=attempt),
            )
            await self._record_task_event(
                "timeline_compose.task_failed",
                "error",
                "Timeline compose task failed.",
                task=updated,
                video=composer_input.video,
                reason="error",
                error_type=error_type,
                error_message=error_message,
            )
            raise

        record = await self._timelines.replace_composition(create)
        if record is None:
            raise TimelineCompositionOutputInvalid("Timeline composition was not stored.")
        output_json = _output_json(record, composer_input, job=job, attempt=attempt)
        await self._pipeline_jobs.mark_attempt_succeeded(
            attempt.id,
            output_json=output_json,
        )
        await self._pipeline_jobs.mark_job_succeeded(job.id)
        updated = await self._video_tasks.mark_task_succeeded(
            task.id,
            output_transcript_id=None,
            output_json=output_json,
        )
        await self._record_task_event(
            "timeline_compose.task_succeeded",
            "info",
            "Timeline compose task succeeded.",
            task=updated,
            video=composer_input.video,
            reason="composed",
            metadata_json=output_json,
        )
        return _timeline_response(record)

    async def _batch_candidate_action(
        self,
        candidate: VideoTaskWithVideoRecord,
        request: TimelineComposeEnqueueRequest,
    ) -> str:
        if request.search is not None:
            search = request.search.casefold()
            if (
                search not in candidate.video.title.casefold()
                and search not in candidate.video.youtube_video_id.casefold()
            ):
                return "skip"
        if request.task_status is not None:
            latest = await self._video_tasks.get_latest_task_for_video(candidate.video.id)
            if latest is None or latest.status != request.task_status:
                return "skip"
        return "include"

    async def _record_task_event(
        self,
        event_type: str,
        severity: OperationEventSeverity,
        message: str,
        *,
        task: VideoTaskRecord,
        video: VideoRecord,
        reason: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata_json: JsonObject | None = None,
    ) -> None:
        metadata: JsonObject = dict(metadata_json or {})
        if reason is not None:
            metadata["reason"] = reason
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity=severity,
                message=message,
                actor_type=cast(OperationEventActorType, "system"),
                source="timelines.compose",
                metadata_json=metadata,
                job_id=task.job_id,
                job_attempt_id=task.job_attempt_id,
                video_task_id=task.id,
                video_id=video.id,
                subject_type="video",
                subject_id=video.id,
                external_key=video.youtube_video_id,
                error_type=error_type,
                error_message=error_message,
            ),
        )


class _VideoSummaryOutput(BaseModel):
    title: str = ""
    summary: str = ""
    display_title: str = ""
    display_summary: str = ""
    main_topics: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class _TimelineBlockOutput(BaseModel):
    block_id: str = ""
    block_type: str = "MIXED"
    title: str = ""
    summary: str = ""
    display_title: str = ""
    display_summary: str = ""
    episode_ids: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class _TimelineEpisodeOutput(BaseModel):
    episode_id: str = ""
    parent_block_id: str = ""
    start_micro_event_id: str = ""
    end_micro_event_id: str = ""
    program_mode: str = "MIXED"
    primary_content_kind: str = "OTHER"
    title: str = ""
    summary: str = ""
    display_title: str = ""
    display_summary: str = ""
    topics: list[str] = Field(default_factory=list)
    viewer_tags: list[str] = Field(default_factory=list)
    highlight_micro_event_ids: list[str] = Field(default_factory=list)
    visibility: str = "DEFAULT"

    model_config = ConfigDict(extra="ignore")


class _TimelineTopicClusterOutput(BaseModel):
    topic_id: str = Field(
        default="",
        validation_alias=AliasChoices("topic_id", "topicId", "cluster_id", "clusterId"),
    )
    label: str = Field(default="", validation_alias=AliasChoices("label", "title"))
    summary: str = ""
    display_label: str = Field(
        default="",
        validation_alias=AliasChoices("display_label", "displayLabel", "title"),
    )
    episode_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("episode_ids", "episodeIds"),
    )

    model_config = ConfigDict(extra="ignore")


class _TimelineReviewFlagOutput(BaseModel):
    start_micro_event_id: str = ""
    end_micro_event_id: str = ""
    type: str = "BOUNDARY_AMBIGUOUS"
    reason: str = ""

    model_config = ConfigDict(extra="ignore")


class _TimelineOutput(BaseModel):
    video_summary: _VideoSummaryOutput = Field(default_factory=_VideoSummaryOutput)
    blocks: list[_TimelineBlockOutput] = Field(default_factory=list)
    episodes: list[_TimelineEpisodeOutput] = Field(default_factory=list)
    topic_clusters: list[_TimelineTopicClusterOutput] = Field(default_factory=list)
    review_flags: list[_TimelineReviewFlagOutput] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


def _timeline_prompt(composer_input: _ComposerInput) -> str:
    input_json = {
        "video_metadata": {
            "video_id": composer_input.video.id,
            "youtube_video_id": composer_input.video.youtube_video_id,
            "title": composer_input.video.title,
            "streamer_name": composer_input.streamer_name,
            "duration_sec": _duration_seconds(composer_input.video.duration),
            "copy_style": composer_input.copy_style,
            "target_episode_count_hint": _episode_count_hint(
                len(composer_input.micro_events)
            ),
        },
        "domain_entries": [
            _domain_entry_json(entry) for entry in composer_input.domain_entries[:80]
        ],
        "micro_events": [
            _micro_event_input(candidate, composer_input, seq=index)
            for index, candidate in enumerate(composer_input.micro_events, start=1)
        ],
    }
    return "\n\n".join([PROMPT_HEADER, "# 입력 데이터", json.dumps(input_json, ensure_ascii=False)])


PROMPT_HEADER = """# 역할

너는 장시간 버츄얼 스트리머 라이브 방송의 micro-event 목록을
사용자 탐색용 최종 타임라인으로 편집하는 Timeline Composer다.

입력에는 방송 전체의 micro-event가 시간순으로 제공된다.

작업:
1. 인접한 micro-event를 의미적으로 완결된 episode로 병합한다.
2. episode를 방송의 큰 흐름을 나타내는 block으로 묶는다.
3. 시간적으로 떨어져 있지만 동일한 주제를 다루는 episode를 topic_cluster로 연결한다.
4. 방송 전체 제목과 요약을 작성한다.
5. 각 episode에 담백한 title/summary와 사용자 노출용 display_title/display_summary를 작성한다.
6. 최종 결정을 내리기 어려운 오류 후보만 review_flags에 기록한다.

새로운 사건을 추출하지 말고 입력 micro-event에 없는 사실을 추가하지 않는다.
모든 micro-event는 정확히 하나의 episode 범위에 포함되어야 한다.
episode는 연속된 micro-event만 포함할 수 있고, block은 연속된 episode로 구성한다.
topic_cluster는 비연속 episode를 연결할 수 있지만 episode의 시간 범위는 바꾸지 않는다.
cue_id와 시간은 출력하지 않는다.

block_type/program_mode는 PRE_ROLL, OPENING, JUST_CHATTING, COMMUNITY_REVIEW,
MEDIA_REVIEW, GAME_SETUP, GAMEPLAY, BREAK, POST_GAME, CLOSING, MIXED 중 하나다.

primary_content_kind는 ANNOUNCEMENT, PERSONAL_STORY, OPINION, QNA, REACTION,
TECHNICAL_SETUP, GAME_PROGRESS, GAME_DISCUSSION, COMMUNITY_REVIEW, MEDIA_REVIEW,
META_CHAT, BREAK_TIME, OTHER 중 하나다.

viewer_tags는 STORY, FUNNY, REACTION, INFORMATION, FOOD, GAME_PROGRESS,
GAME_STORY, GAME_DISCUSSION, COMMUNITY, MEDIA, ANNOUNCEMENT, META 중에서 고른다.

visibility는 DEFAULT, COLLAPSED, HIDDEN 중 하나다. 의미 있는 이야기와 게임 진행은
HIDDEN으로 두지 않는다. BREAK는 보통 COLLAPSED로 둔다.

episode 작성 규칙:
- 서로 다른 탐색 가치가 있는 주제가 한 episode에 과하게 섞이면 분리한다.
- 단순한 곁가지, 짧은 농담, 짧은 채팅 답변만으로는 새 episode를 만들지 않는다.
- topics는 episode마다 검색에 유용한 구체적 명사구 2~6개만 넣는다.
- highlight_micro_event_ids는 episode 안의 핵심 후보만 0~3개 넣는다.

block 작성 규칙:
- MIXED는 지배적인 흐름을 고르기 어려울 때만 사용한다.
- 게임 중 짧은 자리 비움은 별도 최상위 BREAK block보다
  주변 흐름 안의 COLLAPSED BREAK episode로 둔다.
- 게임 후 개인 잡담은 GAMEPLAY가 아니라 POST_GAME 또는 JUST_CHATTING으로 분류한다.

review_flags 작성 규칙:
- 해결하기 어려운 과도한 episode 범위는 OVERBROAD_MICRO_EVENT 또는 BOUNDARY_AMBIGUOUS로 표시한다.
- 방송 후반에 "방송 시작/방송 예정"처럼 방종과 혼동될 수 있는 표현은 ASR_SEMANTIC_RISK로 표시한다.
- 짧은 BREAK 경계가 애매하면 BOUNDARY_AMBIGUOUS로 표시한다.

topic_clusters 작성 규칙:
- 하나의 episode만 포함하는 topic_cluster는 만들지 않는다.
- 너무 일반적인 "잡담", "게임" 같은 cluster는 만들지 않는다.
- 반드시 topic_id, label, summary, display_label, episode_ids 키를 사용한다.

출력은 지정된 JSON 구조만 반환한다.

{
  "video_summary": {
    "title": "string",
    "summary": "string",
    "display_title": "string",
    "display_summary": "string",
    "main_topics": ["string"]
  },
  "blocks": [
    {
      "block_id": "block_001",
      "block_type": "MIXED",
      "title": "string",
      "summary": "string",
      "display_title": "string",
      "display_summary": "string",
      "episode_ids": ["episode_001"]
    }
  ],
  "episodes": [
    {
      "episode_id": "episode_001",
      "parent_block_id": "block_001",
      "start_micro_event_id": "me_0001",
      "end_micro_event_id": "me_0002",
      "program_mode": "JUST_CHATTING",
      "primary_content_kind": "META_CHAT",
      "title": "string",
      "summary": "string",
      "display_title": "string",
      "display_summary": "string",
      "topics": ["string"],
      "viewer_tags": ["META"],
      "highlight_micro_event_ids": ["me_0001"],
      "visibility": "DEFAULT"
    }
  ],
  "topic_clusters": [
    {
      "topic_id": "topic_001",
      "label": "string",
      "summary": "string",
      "display_label": "string",
      "episode_ids": ["episode_001", "episode_003"]
    }
  ],
  "review_flags": []
}
"""


_TIMELINE_BLOCK_TYPES = frozenset(get_args(TimelineBlockType))
_TIMELINE_CONTENT_KINDS = frozenset(get_args(TimelineContentKind))
_TIMELINE_VISIBILITIES = frozenset(get_args(TimelineVisibility))
_TIMELINE_REVIEW_FLAG_TYPES = frozenset(get_args(TimelineReviewFlagType))
_MAX_EPISODE_TOPICS = 6
_MAX_EPISODE_HIGHLIGHTS = 3
_OVERBROAD_MICRO_EVENT_COUNT = 9
_OVERBROAD_LARGE_MICRO_EVENT_COUNT = 12
_SHORT_BREAK_EPISODE_COUNT = 2


def _composition_create(
    composer_input: _ComposerInput,
    result: TimelineComposeResult,
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> TimelineCompositionCreate:
    final_response = result.final_response
    output_json = _loads_output_json(final_response)
    try:
        parsed = _TimelineOutput.model_validate(output_json)
    except ValidationError as exc:
        raise TimelineCompositionOutputInvalid(str(exc)) from exc
    if not parsed.episodes or not parsed.blocks:
        raise TimelineCompositionOutputInvalid(
            "Timeline output must include at least one episode and one block."
        )
    warnings: list[str] = []
    blocks = _normalized_blocks(parsed.blocks, warnings)
    episodes = _normalized_episodes(parsed.episodes, composer_input, warnings)
    episode_ids = {episode.episode_id for episode in episodes}
    blocks = _sanitize_block_episode_ids(blocks, episode_ids, warnings)
    topics = _normalized_topics(parsed.topic_clusters, episode_ids, warnings)
    flags = _normalized_flags(parsed.review_flags, composer_input, warnings)
    flags = _soft_verifier_flags(
        episodes=episodes,
        blocks=blocks,
        composer_input=composer_input,
        existing_flags=flags,
        warnings=warnings,
    )
    summary = parsed.video_summary
    return TimelineCompositionCreate(
        video_task_id=task.id,
        video_id=composer_input.video.id,
        source_micro_event_task_id=composer_input.source_task.id,
        source_micro_event_fingerprint=_required_str(
            composer_input.input_json,
            "sourceMicroEventFingerprint",
        ),
        copy_style=composer_input.copy_style,
        model=composer_input.model,
        reasoning_effort=composer_input.reasoning_effort,
        title=summary.title or composer_input.video.title,
        summary=summary.summary,
        display_title=summary.display_title or summary.title or composer_input.video.title,
        display_summary=summary.display_summary or summary.summary,
        main_topics=summary.main_topics,
        output_json=output_json,
        validation_warnings=warnings,
        source_job_id=job.id,
        source_job_attempt_id=attempt.id,
        codex_thread_id=result.thread_id,
        codex_turn_id=result.turn_id,
        raw_response_text=final_response,
        blocks=blocks,
        episodes=episodes,
        topic_clusters=topics,
        review_flags=flags,
    )


def _normalized_blocks(
    blocks: list[_TimelineBlockOutput],
    warnings: list[str],
) -> list[TimelineBlockCreate]:
    seen: set[str] = set()
    normalized: list[TimelineBlockCreate] = []
    for index, block in enumerate(blocks, start=1):
        block_id = block.block_id or f"block_{index:03d}"
        if block_id in seen:
            warnings.append(f"duplicate block_id removed: {block_id}")
            continue
        seen.add(block_id)
        normalized.append(
            TimelineBlockCreate(
                block_id=block_id,
                block_index=index,
                block_type=_timeline_block_type(
                    block.block_type,
                    warnings,
                    f"block {block_id} block_type",
                ),
                title=block.title,
                summary=block.summary,
                display_title=block.display_title or block.title,
                display_summary=block.display_summary or block.summary,
                episode_ids=block.episode_ids,
            )
        )
    return normalized


def _normalized_episodes(
    episodes: list[_TimelineEpisodeOutput],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineEpisodeCreate]:
    seen: set[str] = set()
    normalized: list[TimelineEpisodeCreate] = []
    for index, episode in enumerate(episodes, start=1):
        episode_id = episode.episode_id or f"episode_{index:03d}"
        if episode_id in seen:
            warnings.append(f"duplicate episode_id removed: {episode_id}")
            continue
        seen.add(episode_id)
        start_id = composer_input.candidate_id_by_synthetic_id.get(
            episode.start_micro_event_id
        )
        end_id = composer_input.candidate_id_by_synthetic_id.get(episode.end_micro_event_id)
        if start_id is None or end_id is None:
            warnings.append(f"episode has invalid micro-event range: {episode_id}")
        if len(episode.highlight_micro_event_ids) > _MAX_EPISODE_HIGHLIGHTS:
            warnings.append(
                f"episode {episode_id} highlight_micro_event_ids truncated "
                f"to {_MAX_EPISODE_HIGHLIGHTS}"
            )
        if len(episode.topics) > _MAX_EPISODE_TOPICS:
            warnings.append(
                f"episode {episode_id} topics truncated to {_MAX_EPISODE_TOPICS}"
            )
        highlights = [
            candidate_id
            for value in episode.highlight_micro_event_ids[:_MAX_EPISODE_HIGHLIGHTS]
            if (candidate_id := composer_input.candidate_id_by_synthetic_id.get(value))
            is not None
        ]
        normalized.append(
            TimelineEpisodeCreate(
                episode_id=episode_id,
                episode_index=len(normalized) + 1,
                parent_block_id=episode.parent_block_id or "block_001",
                start_micro_event_candidate_id=start_id,
                end_micro_event_candidate_id=end_id,
                program_mode=_timeline_block_type(
                    episode.program_mode,
                    warnings,
                    f"episode {episode_id} program_mode",
                ),
                primary_content_kind=_timeline_content_kind(
                    episode.primary_content_kind,
                    warnings,
                    f"episode {episode_id} primary_content_kind",
                ),
                title=episode.title,
                summary=episode.summary,
                display_title=episode.display_title or episode.title,
                display_summary=episode.display_summary or episode.summary,
                topics=episode.topics[:_MAX_EPISODE_TOPICS],
                viewer_tags=episode.viewer_tags,
                highlight_micro_event_candidate_ids=highlights,
                visibility=_timeline_visibility(
                    episode.visibility,
                    warnings,
                    f"episode {episode_id} visibility",
                ),
            )
        )
    _coverage_warnings(normalized, composer_input, warnings)
    return normalized


def _sanitize_block_episode_ids(
    blocks: list[TimelineBlockCreate],
    episode_ids: set[str],
    warnings: list[str],
) -> list[TimelineBlockCreate]:
    sanitized: list[TimelineBlockCreate] = []
    for block in blocks:
        ids = [episode_id for episode_id in block.episode_ids if episode_id in episode_ids]
        if len(ids) != len(block.episode_ids):
            warnings.append(f"block has invalid episode refs: {block.block_id}")
        sanitized.append(
            TimelineBlockCreate(
                block_id=block.block_id,
                block_index=block.block_index,
                block_type=block.block_type,
                title=block.title,
                summary=block.summary,
                display_title=block.display_title,
                display_summary=block.display_summary,
                episode_ids=ids,
            )
        )
    return sanitized


def _normalized_topics(
    clusters: list[_TimelineTopicClusterOutput],
    episode_ids: set[str],
    warnings: list[str],
) -> list[TimelineTopicClusterCreate]:
    normalized: list[TimelineTopicClusterCreate] = []
    for index, cluster in enumerate(clusters, start=1):
        ids = [episode_id for episode_id in cluster.episode_ids if episode_id in episode_ids]
        if len(ids) < 2:
            warnings.append(f"topic cluster removed because it has fewer than two refs: {index}")
            continue
        topic_id = cluster.topic_id or f"topic_{index:03d}"
        label = cluster.label or cluster.display_label or topic_id
        display_label = cluster.display_label or label
        if not cluster.label:
            warnings.append(f"topic cluster label filled from fallback: {topic_id}")
        normalized.append(
            TimelineTopicClusterCreate(
                topic_id=topic_id,
                topic_index=len(normalized) + 1,
                label=label,
                summary=cluster.summary,
                display_label=display_label,
                episode_ids=ids,
            )
        )
    return normalized


def _normalized_flags(
    flags: list[_TimelineReviewFlagOutput],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineReviewFlagCreate]:
    normalized: list[TimelineReviewFlagCreate] = []
    for flag in flags:
        start_id = composer_input.candidate_id_by_synthetic_id.get(flag.start_micro_event_id)
        end_id = composer_input.candidate_id_by_synthetic_id.get(flag.end_micro_event_id)
        if start_id is None or end_id is None:
            warnings.append("review flag removed because micro-event refs are invalid")
            continue
        normalized.append(
            TimelineReviewFlagCreate(
                flag_index=len(normalized) + 1,
                start_micro_event_candidate_id=start_id,
                end_micro_event_candidate_id=end_id,
                type=_timeline_review_flag_type(
                    flag.type,
                    warnings,
                    "review flag type",
                ),
                reason=flag.reason,
            )
        )
    return normalized


def _soft_verifier_flags(
    *,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
    existing_flags: list[TimelineReviewFlagCreate],
    warnings: list[str],
) -> list[TimelineReviewFlagCreate]:
    normalized = list(existing_flags)
    existing_keys = {
        (flag.start_micro_event_candidate_id, flag.end_micro_event_candidate_id, flag.type)
        for flag in normalized
    }
    episode_by_id = {episode.episode_id: episode for episode in episodes}
    candidate_by_id = {candidate.id: candidate for candidate in composer_input.micro_events}
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }

    def append_flag(
        *,
        start_id: int | None,
        end_id: int | None,
        flag_type: TimelineReviewFlagType,
        reason: str,
    ) -> None:
        if start_id is None or end_id is None:
            return
        key = (start_id, end_id, flag_type)
        if key in existing_keys:
            return
        existing_keys.add(key)
        normalized.append(
            TimelineReviewFlagCreate(
                flag_index=len(normalized) + 1,
                start_micro_event_candidate_id=start_id,
                end_micro_event_candidate_id=end_id,
                type=flag_type,
                reason=reason,
            )
        )

    mixed_count = sum(1 for block in blocks if block.block_type == "MIXED")
    if len(blocks) >= 4 and mixed_count / len(blocks) >= 0.3:
        warnings.append(f"timeline has many MIXED blocks: {mixed_count}/{len(blocks)}")

    for episode in episodes:
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            continue
        candidates, start_index, _end_index = range_info
        program_modes = {
            candidate.program_mode for candidate in candidates if candidate.program_mode
        }
        content_kinds = {
            candidate.content_kind for candidate in candidates if candidate.content_kind
        }
        is_overbroad = (
            len(candidates) >= _OVERBROAD_MICRO_EVENT_COUNT
            and (
                len(episode.topics) >= _MAX_EPISODE_TOPICS
                or len(program_modes) >= 3
                or len(content_kinds) >= 3
            )
        ) or (
            len(candidates) >= _OVERBROAD_LARGE_MICRO_EVENT_COUNT
            and len(content_kinds) >= 2
        )
        if is_overbroad:
            append_flag(
                start_id=episode.start_micro_event_candidate_id,
                end_id=episode.end_micro_event_candidate_id,
                flag_type="OVERBROAD_MICRO_EVENT",
                reason=(
                    "Episode spans many micro-events with mixed subjects; "
                    "consider splitting if separate user-searchable topics are present."
                ),
            )
        if _is_late_broadcast_start_risk(
            episode,
            candidates,
            start_index=start_index,
            total_count=len(candidate_ids),
        ):
            append_flag(
                start_id=episode.start_micro_event_candidate_id,
                end_id=episode.end_micro_event_candidate_id,
                flag_type="ASR_SEMANTIC_RISK",
                reason=(
                    "Late-stream wording mentions starting or scheduling a broadcast; "
                    "verify whether this is an ASR confusion with ending the broadcast."
                ),
            )

    for index, block in enumerate(blocks):
        if (
            block.block_type != "BREAK"
            or len(block.episode_ids) > _SHORT_BREAK_EPISODE_COUNT
            or index == 0
            or index == len(blocks) - 1
        ):
            continue
        block_episodes = [
            episode
            for episode_id in block.episode_ids
            if (episode := episode_by_id.get(episode_id)) is not None
        ]
        if not block_episodes:
            continue
        append_flag(
            start_id=block_episodes[0].start_micro_event_candidate_id,
            end_id=block_episodes[-1].end_micro_event_candidate_id,
            flag_type="BOUNDARY_AMBIGUOUS",
            reason=(
                "Short BREAK appears as a separate top-level block; "
                "consider keeping it as a collapsed episode inside the neighboring flow."
            ),
        )
    return normalized


def _episode_candidate_range(
    episode: TimelineEpisodeCreate,
    candidate_ids: list[int],
    candidate_index_by_id: dict[int, int],
    candidate_by_id: dict[int, MicroEventCandidateRecord],
) -> tuple[list[MicroEventCandidateRecord], int, int] | None:
    if (
        episode.start_micro_event_candidate_id is None
        or episode.end_micro_event_candidate_id is None
    ):
        return None
    start_index = candidate_index_by_id.get(episode.start_micro_event_candidate_id)
    end_index = candidate_index_by_id.get(episode.end_micro_event_candidate_id)
    if start_index is None or end_index is None or end_index < start_index:
        return None
    candidate_range = [
        candidate_by_id[candidate_id]
        for candidate_id in candidate_ids[start_index : end_index + 1]
        if candidate_id in candidate_by_id
    ]
    return candidate_range, start_index, end_index


def _is_late_broadcast_start_risk(
    episode: TimelineEpisodeCreate,
    candidates: list[MicroEventCandidateRecord],
    *,
    start_index: int,
    total_count: int,
) -> bool:
    if total_count <= 0 or start_index < int(total_count * 0.65):
        return False
    text = " ".join(
        [
            episode.title,
            episode.summary,
            episode.display_title,
            episode.display_summary,
            *(candidate.event for candidate in candidates),
        ]
    )
    if "방종" in text:
        return False
    return any(
        phrase in text
        for phrase in (
            "방송할 예정",
            "방송 예정",
            "방송 시작",
            "방송을 시작",
            "방송하면",
            "방송한다",
        )
    )


def _timeline_block_type(
    value: str,
    warnings: list[str],
    context: str,
) -> TimelineBlockType:
    normalized = value.strip().upper()
    if normalized in _TIMELINE_BLOCK_TYPES:
        return cast(TimelineBlockType, normalized)
    warnings.append(f"{context} had unknown value '{value}', replaced with MIXED")
    return "MIXED"


def _timeline_content_kind(
    value: str,
    warnings: list[str],
    context: str,
) -> TimelineContentKind:
    normalized = value.strip().upper()
    if normalized in _TIMELINE_CONTENT_KINDS:
        return cast(TimelineContentKind, normalized)
    warnings.append(f"{context} had unknown value '{value}', replaced with OTHER")
    return "OTHER"


def _timeline_visibility(
    value: str,
    warnings: list[str],
    context: str,
) -> TimelineVisibility:
    normalized = value.strip().upper()
    if normalized in _TIMELINE_VISIBILITIES:
        return cast(TimelineVisibility, normalized)
    warnings.append(f"{context} had unknown value '{value}', replaced with DEFAULT")
    return "DEFAULT"


def _timeline_review_flag_type(
    value: str,
    warnings: list[str],
    context: str,
) -> TimelineReviewFlagType:
    normalized = value.strip().upper()
    if normalized in _TIMELINE_REVIEW_FLAG_TYPES:
        return cast(TimelineReviewFlagType, normalized)
    warnings.append(
        f"{context} had unknown value '{value}', replaced with BOUNDARY_AMBIGUOUS"
    )
    return "BOUNDARY_AMBIGUOUS"


def _coverage_warnings(
    episodes: list[TimelineEpisodeCreate],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> None:
    ids = [candidate.id for candidate in composer_input.micro_events]
    covered: list[int] = []
    for episode in episodes:
        if (
            episode.start_micro_event_candidate_id is None
            or episode.end_micro_event_candidate_id is None
        ):
            continue
        try:
            start = ids.index(episode.start_micro_event_candidate_id)
            end = ids.index(episode.end_micro_event_candidate_id)
        except ValueError:
            continue
        if end < start:
            warnings.append(f"episode range is reversed: {episode.episode_id}")
            continue
        covered.extend(ids[start : end + 1])
    missing = sorted(set(ids) - set(covered))
    if missing:
        warnings.append(f"micro-events missing from episodes: {len(missing)}")
    if len(covered) != len(set(covered)):
        warnings.append("micro-events duplicated across episodes")


def _loads_output_json(text: str) -> JsonObject:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise TimelineCompositionOutputInvalid("Composer returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise TimelineCompositionOutputInvalid("Composer output must be a JSON object.")
    return cast(JsonObject, payload)


def _micro_event_input(
    candidate: MicroEventCandidateRecord,
    composer_input: _ComposerInput,
    *,
    seq: int,
) -> JsonObject:
    return {
        "micro_event_id": composer_input.synthetic_id_by_candidate_id[candidate.id],
        "seq": seq,
        "start_cue_id": candidate.start_cue_id,
        "end_cue_id": candidate.end_cue_id,
        "event": candidate.event,
        "program_mode": candidate.program_mode,
        "content_kind": candidate.content_kind,
        "topics": candidate.topics or [],
    }


def _domain_entry_json(entry: DomainKnowledgePromptEntryRecord) -> JsonObject:
    return {
        "type": entry.type_key,
        "canonicalName": entry.canonical_name,
        "displayName": entry.display_name,
        "detail": entry.detail,
        "aliases": [
            {
                "surfaceForm": alias.surface_form,
                "aliasKind": alias.alias_kind,
                "certainty": alias.certainty,
            }
            for alias in entry.aliases
        ],
    }


def _flatten_micro_events(
    detail: MicroEventExtractionDetailRecord,
) -> list[MicroEventCandidateRecord]:
    return [
        candidate
        for window in sorted(detail.windows, key=lambda item: item.window_index)
        for candidate in sorted(window.micro_events, key=lambda item: item.candidate_index)
    ]


def _micro_event_count(detail: MicroEventExtractionDetailRecord) -> int:
    return sum(len(window.micro_events) for window in detail.windows)


def _source_micro_event_fingerprint(detail: MicroEventExtractionDetailRecord) -> str:
    payload = [
        {
            "id": candidate.id,
            "event": candidate.event,
            "startCueId": candidate.start_cue_id,
            "endCueId": candidate.end_cue_id,
            "programMode": candidate.program_mode,
            "contentKind": candidate.content_kind,
            "topics": candidate.topics,
        }
        for candidate in _flatten_micro_events(detail)
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _task_input_hash(
    *,
    video: VideoRecord,
    source_task: VideoTaskRecord,
    source_fingerprint: str,
    copy_style: CopyStyle,
    model: CodexModelChoice,
    reasoning_effort: ReasoningEffortChoice,
) -> str:
    payload = {
        "copyStyle": copy_style,
        "model": model,
        "promptVersion": TIMELINE_COMPOSE_PROMPT_VERSION,
        "reasoningEffort": reasoning_effort,
        "sourceMicroEventFingerprint": source_fingerprint,
        "sourceMicroEventTaskId": source_task.id,
        "taskVersion": TIMELINE_COMPOSE_TASK_VERSION,
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _task_input_json(
    *,
    video: VideoRecord,
    source_task: VideoTaskRecord,
    source_fingerprint: str,
    input_hash: str,
    copy_style: CopyStyle,
    model: CodexModelChoice,
    reasoning_effort: ReasoningEffortChoice,
    timeout_seconds: int,
) -> JsonObject:
    return {
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
        "sourceMicroEventTaskId": source_task.id,
        "sourceMicroEventFingerprint": source_fingerprint,
        "taskVersion": TIMELINE_COMPOSE_TASK_VERSION,
        "promptVersion": TIMELINE_COMPOSE_PROMPT_VERSION,
        "inputHash": input_hash,
        "copyStyle": copy_style,
        "model": model,
        "reasoningEffort": reasoning_effort,
        "timeoutSeconds": timeout_seconds,
    }


def _enqueue_response(
    request: TimelineComposeEnqueueRequest,
    counters: _EnqueueCounters,
    items: list[TimelineComposeEnqueueItemResponse],
) -> TimelineComposeEnqueueResponse:
    requested_count = (
        min(len(request.video_ids), request.limit)
        if request.target == "selected_videos"
        else request.limit
    )
    return TimelineComposeEnqueueResponse(
        requestedCount=requested_count,
        scannedCount=counters.scanned_count,
        enqueuedCount=counters.enqueued_count,
        alreadyPendingCount=counters.already_pending_count,
        alreadyRunningCount=counters.already_running_count,
        alreadySucceededCount=counters.already_succeeded_count,
        retryQueuedCount=counters.retry_queued_count,
        regeneratedCount=counters.regenerated_count,
        failedSkippedCount=counters.failed_skipped_count,
        ineligibleCount=counters.ineligible_count,
        items=items,
    )


def _enqueue_item(
    *,
    video_id: int,
    youtube_video_id: str | None,
    task: VideoTaskRecord | None,
    status: str,
    reason: str,
    source_task_id: int | None,
    model: str | None,
    reasoning_effort: str | None,
    copy_style: str | None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> TimelineComposeEnqueueItemResponse:
    return TimelineComposeEnqueueItemResponse(
        videoId=video_id,
        youtubeVideoId=youtube_video_id,
        videoTaskId=task.id if task is not None else None,
        status=status,
        reason=reason,
        sourceMicroEventTaskId=source_task_id,
        model=model,
        reasoningEffort=reasoning_effort,
        copyStyle=copy_style,
        errorType=error_type,
        errorMessage=error_message,
    )


def _timeline_response(record: TimelineCompositionRecord) -> TimelineCompositionResponse:
    return TimelineCompositionResponse(
        videoTaskId=record.video_task_id,
        videoId=record.video_id,
        youtubeVideoId=record.youtube_video_id,
        sourceMicroEventTaskId=record.source_micro_event_task_id,
        sourceMicroEventFingerprint=record.source_micro_event_fingerprint,
        copyStyle=record.copy_style,
        status=record.status,
        model=record.model,
        reasoningEffort=record.reasoning_effort,
        title=record.title,
        summary=record.summary,
        displayTitle=record.display_title,
        displaySummary=record.display_summary,
        mainTopics=record.main_topics,
        validationWarnings=record.validation_warnings,
        outputJson=record.output_json,
        blocks=[
            TimelineBlockResponse(
                blockId=item.block_id,
                blockIndex=item.block_index,
                blockType=item.block_type,
                title=item.title,
                summary=item.summary,
                displayTitle=item.display_title,
                displaySummary=item.display_summary,
                episodeIds=item.episode_ids,
            )
            for item in record.blocks
        ],
        episodes=[
            TimelineEpisodeResponse(
                episodeId=item.episode_id,
                episodeIndex=item.episode_index,
                parentBlockId=item.parent_block_id,
                startMicroEventCandidateId=item.start_micro_event_candidate_id,
                endMicroEventCandidateId=item.end_micro_event_candidate_id,
                programMode=item.program_mode,
                primaryContentKind=item.primary_content_kind,
                title=item.title,
                summary=item.summary,
                displayTitle=item.display_title,
                displaySummary=item.display_summary,
                topics=item.topics,
                viewerTags=item.viewer_tags,
                highlightMicroEventCandidateIds=item.highlight_micro_event_candidate_ids,
                visibility=item.visibility,
            )
            for item in record.episodes
        ],
        topicClusters=[
            TimelineTopicClusterResponse(
                topicId=item.topic_id,
                topicIndex=item.topic_index,
                label=item.label,
                summary=item.summary,
                displayLabel=item.display_label,
                episodeIds=item.episode_ids,
            )
            for item in record.topic_clusters
        ],
        reviewFlags=[
            TimelineReviewFlagResponse(
                flagIndex=item.flag_index,
                startMicroEventCandidateId=item.start_micro_event_candidate_id,
                endMicroEventCandidateId=item.end_micro_event_candidate_id,
                type=item.type,
                reason=item.reason,
            )
            for item in record.review_flags
        ],
    )


def _output_json(
    record: TimelineCompositionRecord,
    composer_input: _ComposerInput,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> JsonObject:
    return {
        "videoTaskId": record.video_task_id,
        "videoId": record.video_id,
        "youtubeVideoId": record.youtube_video_id,
        "sourceMicroEventTaskId": composer_input.source_task.id,
        "sourceMicroEventFingerprint": record.source_micro_event_fingerprint,
        "copyStyle": record.copy_style,
        "model": record.model,
        "reasoningEffort": record.reasoning_effort,
        "timelineTitle": record.title,
        "blockCount": len(record.blocks),
        "episodeCount": len(record.episodes),
        "topicClusterCount": len(record.topic_clusters),
        "reviewFlagCount": len(record.review_flags),
        "validationWarnings": record.validation_warnings,
        "jobId": job.id,
        "jobAttemptId": attempt.id,
    }


def _attempt_output_json(
    composer_input: _ComposerInput,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> JsonObject:
    return {
        "videoId": composer_input.video.id,
        "youtubeVideoId": composer_input.video.youtube_video_id,
        "sourceMicroEventTaskId": composer_input.source_task.id,
        "copyStyle": composer_input.copy_style,
        "model": composer_input.model,
        "reasoningEffort": composer_input.reasoning_effort,
        "jobId": job.id,
        "jobAttemptId": attempt.id,
    }


def _duration_seconds(duration: str | None) -> int | None:
    if not duration or not duration.startswith("PT"):
        return None
    total = 0
    number = ""
    for char in duration[2:]:
        if char.isdigit():
            number += char
            continue
        if not number:
            continue
        value = int(number)
        number = ""
        if char == "H":
            total += value * 3600
        elif char == "M":
            total += value * 60
        elif char == "S":
            total += value
    return total or None


def _episode_count_hint(micro_event_count: int) -> JsonObject:
    if micro_event_count <= 20:
        return {"min": 3, "max": max(5, micro_event_count)}
    if micro_event_count <= 80:
        return {"min": 10, "max": 30}
    return {"min": 30, "max": 60}


def _model_output(input_json: JsonObject) -> CodexModelChoice | None:
    value = input_json.get("model")
    if value in {"gpt-5.5", "gpt-5.4", "gpt-5.4-mini"}:
        return cast(CodexModelChoice, value)
    return None


def _reasoning_effort_output(input_json: JsonObject) -> ReasoningEffortChoice | None:
    value = input_json.get("reasoningEffort")
    if value in {"low", "medium", "high", "xhigh"}:
        return cast(ReasoningEffortChoice, value)
    return None


def _str_output(input_json: JsonObject, key: str) -> str | None:
    value = input_json.get(key)
    return value if isinstance(value, str) else None


def _int_output(input_json: JsonObject, key: str) -> int | None:
    value = input_json.get(key)
    return value if isinstance(value, int) else None


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise VideoTaskRetryNotAllowed(f"Task input is missing integer '{key}'.")
    return value


def _required_str(input_json: JsonObject, key: str) -> str:
    value = input_json.get(key)
    if not isinstance(value, str) or not value:
        raise VideoTaskRetryNotAllowed(f"Task input is missing string '{key}'.")
    return value
