from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import cast, get_args

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainKnowledgePromptEntryRecord,
    DomainKnowledgeRepositoryPort,
)
from codex_sdk_cli.domains.llm_traces.ports import (
    LlmTraceEvent,
    LlmTraceRecorderPort,
    NoopLlmTraceRecorder,
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
from codex_sdk_cli.domains.prompts.constants import (
    TIMELINE_COMPOSE_PROMPT_KEY,
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY,
)
from codex_sdk_cli.domains.prompts.ports import PromptResolverPort, ResolvedPrompt
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

from .constants import (
    TIMELINE_COMPOSE_BATCH_SCAN_LIMIT,
    TIMELINE_COMPOSE_DEFAULT_COPY_STYLE,
    TIMELINE_COMPOSE_DEFAULT_REASONING_EFFORT,
    TIMELINE_COMPOSE_MAX_COVERAGE_REPAIRS,
    TIMELINE_COMPOSE_MAX_EPISODE_REPAIRS,
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
    TimelineEpisodeRepairRequest,
    TimelineEpisodeRepairResult,
    TimelineReviewFlagCreate,
    TimelineReviewFlagType,
    TimelineTopicClusterCreate,
    TimelineViewerTag,
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
from .style import normalize_timeline_style_text

TIMELINE_COMPOSE_WORKER_ID_PREFIX = "timeline-compose-worker:"
TIMELINE_DOMAIN_KNOWLEDGE_PROMPT_ENTRY_LIMIT = 80
_TIMELINE_RAW_RESPONSE_STORED_IN = "pipelineJobAttempt.outputJson.rawResponses"
logger = logging.getLogger(__name__)


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
    prompt: ResolvedPrompt


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
    compose_prompt: ResolvedPrompt
    repair_prompt: ResolvedPrompt


@dataclass(frozen=True, slots=True)
class _TimelineRawResponse:
    operation: str
    thread_id: str | None
    turn_id: str | None
    status: str
    raw_response_text: str
    target_episode_id: str | None = None


@dataclass(frozen=True, slots=True)
class _CoverageRepairPlan:
    target_episode: TimelineEpisodeCreate
    target_candidates: list[MicroEventCandidateRecord]
    replace_start_index: int
    replace_end_index: int
    insert_before_episode_id: str | None


@dataclass(frozen=True, slots=True)
class _BlockSegment:
    block_type: TimelineBlockType
    title: str
    summary: str
    display_title: str
    display_summary: str
    episodes: list[TimelineEpisodeCreate]


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
        prompt_resolver: PromptResolverPort,
        timeout_seconds: int,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
        events: OperationEventRecorderPort,
        llm_traces: LlmTraceRecorderPort | None = None,
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
        self._prompt_resolver = prompt_resolver
        self._timeout_seconds = timeout_seconds
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._events = events
        self._llm_traces = llm_traces or NoopLlmTraceRecorder()

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
        reasoning_effort = request.reasoning_effort or TIMELINE_COMPOSE_DEFAULT_REASONING_EFFORT
        source_fingerprint = _source_micro_event_fingerprint(source_detail)
        prompt = await self._prompt_resolver.resolve_prompt_for_request(
            TIMELINE_COMPOSE_PROMPT_KEY,
            request.prompt_version_id,
        )
        input_hash = _task_input_hash(
            video=video,
            source_task=source_task,
            source_fingerprint=source_fingerprint,
            copy_style=request.copy_style,
            model=model,
            reasoning_effort=reasoning_effort,
            prompt=prompt,
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
            prompt=prompt,
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
            prompt=prompt,
        )

    async def _load_composer_input(self, input_json: JsonObject) -> _ComposerInput:
        video_id = _required_int(input_json, "videoId")
        source_task_id = _required_int(input_json, "sourceMicroEventTaskId")
        video = await self._videos.get_video(video_id)
        if video is None:
            raise VideoNotFound("Video not found.")
        source_task = await self._video_tasks.get_task(source_task_id)
        if source_task is None:
            raise TimelineCompositionPreconditionFailed("Source micro-event task not found.")
        source_detail = await self._micro_events.get_extraction(
            video_id=video.id,
            video_task_id=source_task.id,
        )
        if source_detail is None:
            raise TimelineCompositionPreconditionFailed("Source micro-event extraction not found.")
        micro_events = _flatten_micro_events(source_detail)
        if not micro_events:
            raise TimelineCompositionPreconditionFailed("Micro-events are required.")
        channel = await self._channels.get_channel(video.channel_id)
        streamer_name = None
        streamer_id = channel.streamer_id if channel is not None else None
        if streamer_id is not None:
            streamer = await self._streamers.get_streamer(streamer_id)
            streamer_name = streamer.name if streamer is not None else None
        domain_entries = await self._domain_knowledge.list_prompt_entries_for_streamer(streamer_id)
        synthetic_id_by_candidate_id = {
            candidate.id: f"me_{index:04d}" for index, candidate in enumerate(micro_events, start=1)
        }
        candidate_id_by_synthetic_id = {
            value: key for key, value in synthetic_id_by_candidate_id.items()
        }
        compose_prompt = await self._resolve_compose_prompt_from_input(input_json)
        repair_prompt = await self._prompt_resolver.resolve_prompt(
            TIMELINE_EPISODE_REPAIR_PROMPT_KEY
        )
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
                _str_output(input_json, "copyStyle") or TIMELINE_COMPOSE_DEFAULT_COPY_STYLE,
            ),
            compose_prompt=compose_prompt,
            repair_prompt=repair_prompt,
        )

    async def _resolve_compose_prompt_from_input(
        self,
        input_json: JsonObject,
    ) -> ResolvedPrompt:
        if "promptVersionId" in input_json:
            return await self._prompt_resolver.resolve_prompt_version(
                TIMELINE_COMPOSE_PROMPT_KEY,
                _int_output(input_json, "promptVersionId"),
            )
        return await self._prompt_resolver.resolve_prompt(TIMELINE_COMPOSE_PROMPT_KEY)

    async def _execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        *,
        task: VideoTaskRecord,
        composer_input: _ComposerInput,
        timeout_seconds: int,
    ) -> TimelineCompositionResponse:
        raw_responses: list[_TimelineRawResponse] = []
        failure_stage = "compose"
        try:
            await self._timelines.delete_composition(task.id)
            prompt = _timeline_prompt(composer_input)
            await self._llm_traces.record_event(
                _timeline_trace_event(
                    operation="compose_video",
                    phase="compose_started",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    prompt_text=prompt,
                )
            )
            started_at = time.monotonic()
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
            raw_responses.append(_raw_response("compose_video", result))
            await self._llm_traces.record_event(
                _timeline_trace_event(
                    operation="compose_video",
                    phase="compose_response_received",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    raw_response_text=result.final_response,
                )
            )
            failure_stage = "compose_output_validation"
            create = await _composition_create_with_repairs(
                composer_input,
                result,
                task=task,
                job=job,
                attempt=attempt,
                composer=self._composer,
                timeout_seconds=timeout_seconds,
                raw_responses=raw_responses,
                llm_traces=self._llm_traces,
            )
        except TimeoutError:
            message = f"Timeline compose exceeded {timeout_seconds} seconds."
            await self._llm_traces.record_event(
                _timeline_trace_event(
                    operation="compose_video",
                    phase="compose_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    error_type="TimeoutError",
                    error_message=message,
                    metadata={"stage": failure_stage},
                )
            )
            attempt_output_json = _failed_attempt_output_json(
                composer_input,
                job=job,
                attempt=attempt,
                error_type="TimeoutError",
                error_message=message,
                stage=failure_stage,
                raw_responses=raw_responses,
            )
            task_output_json = _attempt_output_json(
                composer_input,
                job=job,
                attempt=attempt,
                raw_responses=raw_responses,
            )
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type="TimeoutError",
                error_message=message,
                output_json=attempt_output_json,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            updated = await self._video_tasks.mark_task_timed_out(
                task.id,
                error_message=message,
                output_json=task_output_json,
            )
            _log_timeline_failure(
                task=updated,
                job=job,
                attempt=attempt,
                raw_responses=raw_responses,
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
                metadata_json=task_output_json,
            )
            raise
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            if failure_stage == "compose_output_validation":
                await self._llm_traces.record_event(
                    _timeline_trace_event(
                        operation="compose_video",
                        phase="compose_validation_failed",
                        task=task,
                        job=job,
                        attempt=attempt,
                        composer_input=composer_input,
                        raw_response_text=raw_responses[0].raw_response_text
                        if raw_responses
                        else None,
                        error_type=error_type,
                        error_message=error_message,
                        metadata={"stage": failure_stage},
                    )
                )
            await self._llm_traces.record_event(
                _timeline_trace_event(
                    operation="compose_video",
                    phase="compose_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    error_type=error_type,
                    error_message=error_message,
                    metadata={"stage": failure_stage},
                )
            )
            attempt_output_json = _failed_attempt_output_json(
                composer_input,
                job=job,
                attempt=attempt,
                error_type=error_type,
                error_message=error_message,
                stage=failure_stage,
                raw_responses=raw_responses,
            )
            task_output_json = _attempt_output_json(
                composer_input,
                job=job,
                attempt=attempt,
                raw_responses=raw_responses,
            )
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=error_type,
                error_message=error_message,
                output_json=attempt_output_json,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            updated = await self._video_tasks.mark_task_failed(
                task.id,
                error_type=error_type,
                error_message=error_message,
                output_json=task_output_json,
            )
            _log_timeline_failure(
                task=updated,
                job=job,
                attempt=attempt,
                raw_responses=raw_responses,
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
                metadata_json=task_output_json,
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
        await self._llm_traces.record_event(
            _timeline_trace_event(
                operation="compose_video",
                phase="compose_succeeded",
                task=updated,
                job=job,
                attempt=attempt,
                composer_input=composer_input,
                metadata={"compositionId": record.id},
            )
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


def _timeline_trace_event(
    *,
    operation: str,
    phase: str,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    composer_input: _ComposerInput,
    repair_index: int | None = None,
    target_episode_id: str | None = None,
    repair_reason: str | None = None,
    result: TimelineComposeResult | TimelineEpisodeRepairResult | None = None,
    elapsed_ms: int | None = None,
    prompt_text: str | None = None,
    raw_response_text: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata: JsonObject | None = None,
) -> LlmTraceEvent:
    return LlmTraceEvent(
        source="timeline_compose",
        operation=operation,
        phase=phase,
        video_task_id=task.id,
        video_id=composer_input.video.id,
        job_id=job.id,
        job_attempt_id=attempt.id,
        repair_index=repair_index,
        target_episode_id=target_episode_id,
        repair_reason=repair_reason,
        model=str(composer_input.model),
        reasoning_effort=str(composer_input.reasoning_effort),
        thread_id=result.thread_id if result is not None else None,
        turn_id=result.turn_id if result is not None else None,
        status=result.status if result is not None else None,
        elapsed_ms=elapsed_ms,
        prompt_text=prompt_text,
        raw_response_text=raw_response_text,
        error_type=error_type,
        error_message=error_message,
        metadata=metadata or {},
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.monotonic() - started_at) * 1000))


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


class _TimelineRepairEpisodeOutput(BaseModel):
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


class _TimelineEpisodeRepairOutput(BaseModel):
    target_episode_id: str = ""
    action: str = "KEEP"
    replacement_episodes: list[_TimelineRepairEpisodeOutput] = Field(default_factory=list)
    reason: str = ""

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
            "target_episode_count_hint": _episode_count_hint(len(composer_input.micro_events)),
        },
        "domain_entries": [
            _domain_entry_json(entry) for entry in _timeline_domain_entries(composer_input)
        ],
        "micro_events": [
            _micro_event_input(candidate, composer_input, seq=index)
            for index, candidate in enumerate(composer_input.micro_events, start=1)
        ],
    }
    return "\n\n".join(
        [
            composer_input.compose_prompt.body,
            "# INPUT_DATA",
            json.dumps(input_json, ensure_ascii=False),
        ]
    )


_TIMELINE_BLOCK_TYPES = frozenset(get_args(TimelineBlockType))
_TIMELINE_CONTENT_KINDS = frozenset(get_args(TimelineContentKind))
_TIMELINE_VISIBILITIES = frozenset(get_args(TimelineVisibility))
_TIMELINE_VIEWER_TAGS = frozenset(get_args(TimelineViewerTag))
_TIMELINE_REVIEW_FLAG_TYPES = frozenset(get_args(TimelineReviewFlagType))
_VIEWER_TAG_CONTENT_KIND_ALIASES: dict[str, TimelineViewerTag | None] = {
    "OPINION": "INFORMATION",
    "TECHNICAL_SETUP": "INFORMATION",
    "OTHER": "INFORMATION",
    "PERSONAL_STORY": "STORY",
    "META_CHAT": "META",
    "COMMUNITY_REVIEW": "COMMUNITY",
    "MEDIA_REVIEW": "MEDIA",
    "BREAK_TIME": None,
}
_MAX_EPISODE_TOPICS = 6
_MAX_EPISODE_HIGHLIGHTS = 3
_OVERBROAD_MICRO_EVENT_COUNT = 9
_OVERBROAD_LARGE_MICRO_EVENT_COUNT = 12
_SHORT_BREAK_EPISODE_COUNT = 2
_POST_GAME_DAILY_CONTENT_KINDS = frozenset({"PERSONAL_STORY", "OPINION", "QNA", "META_CHAT"})
_GAME_RELATED_CONTENT_KINDS = frozenset({"GAME_PROGRESS", "GAME_DISCUSSION"})
_GAME_RELATED_MODES = frozenset({"GAMEPLAY", "GAME_SETUP", "POST_GAME"})
_CLOSING_TERMS = (
    "방종",
    "마무리",
    "종료",
    "안내",
    "인사",
    "고마워",
    "감사",
    "수고",
    "다음",
    "오늘",
    "closing",
    "goodbye",
)


def _composition_create(
    composer_input: _ComposerInput,
    result: TimelineComposeResult,
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> TimelineCompositionCreate:
    output_json, summary, blocks, episodes, topics, flags, warnings = _normalized_timeline_parts(
        composer_input, result
    )
    blocks, episodes = _repair_block_semantics(episodes, blocks, composer_input, warnings)
    flags = _soft_verifier_flags(
        episodes=episodes,
        blocks=blocks,
        composer_input=composer_input,
        existing_flags=flags,
        warnings=warnings,
    )
    summary, blocks, episodes, topics, flags = _normalize_timeline_style(
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        warnings=warnings,
    )
    _validate_timeline_invariants(episodes, blocks, composer_input)
    output_json = _timeline_output_json(
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
    )
    return _composition_create_from_parts(
        composer_input,
        result,
        output_json=output_json,
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        warnings=warnings,
        task=task,
        job=job,
        attempt=attempt,
    )


async def _composition_create_with_repairs(
    composer_input: _ComposerInput,
    result: TimelineComposeResult,
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    composer: TimelineComposerPort,
    timeout_seconds: int,
    raw_responses: list[_TimelineRawResponse] | None = None,
    llm_traces: LlmTraceRecorderPort | None = None,
) -> TimelineCompositionCreate:
    trace_recorder = llm_traces or NoopLlmTraceRecorder()
    output_json, summary, blocks, episodes, topics, flags, warnings = _normalized_timeline_parts(
        composer_input, result
    )
    episodes, blocks, topics, flags = await _repair_overbroad_episodes(
        episodes=episodes,
        blocks=blocks,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
        task=task,
        job=job,
        attempt=attempt,
        composer=composer,
        timeout_seconds=timeout_seconds,
        warnings=warnings,
        raw_responses=raw_responses,
        llm_traces=trace_recorder,
    )
    episodes, blocks, topics, flags = await _repair_episode_coverage(
        episodes=episodes,
        blocks=blocks,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
        task=task,
        job=job,
        attempt=attempt,
        composer=composer,
        timeout_seconds=timeout_seconds,
        warnings=warnings,
        raw_responses=raw_responses,
        llm_traces=trace_recorder,
    )
    blocks, episodes = _repair_block_semantics(episodes, blocks, composer_input, warnings)
    episodes, blocks, topics, flags = await _repair_episode_coverage(
        episodes=episodes,
        blocks=blocks,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
        task=task,
        job=job,
        attempt=attempt,
        composer=composer,
        timeout_seconds=timeout_seconds,
        warnings=warnings,
        raw_responses=raw_responses,
        llm_traces=trace_recorder,
    )
    blocks, episodes = _repair_block_semantics(episodes, blocks, composer_input, warnings)
    flags = _soft_verifier_flags(
        episodes=episodes,
        blocks=blocks,
        composer_input=composer_input,
        existing_flags=flags,
        warnings=warnings,
    )
    summary, blocks, episodes, topics, flags = _normalize_timeline_style(
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        warnings=warnings,
    )
    _validate_timeline_invariants(episodes, blocks, composer_input)
    output_json = _timeline_output_json(
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
    )
    return _composition_create_from_parts(
        composer_input,
        result,
        output_json=output_json,
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        warnings=warnings,
        task=task,
        job=job,
        attempt=attempt,
    )


def _normalized_timeline_parts(
    composer_input: _ComposerInput,
    result: TimelineComposeResult,
) -> tuple[
    JsonObject,
    _VideoSummaryOutput,
    list[TimelineBlockCreate],
    list[TimelineEpisodeCreate],
    list[TimelineTopicClusterCreate],
    list[TimelineReviewFlagCreate],
    list[str],
]:
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
    episodes = _sort_episodes_by_range(episodes, composer_input, warnings)
    episode_ids = {episode.episode_id for episode in episodes}
    blocks = _sanitize_block_episode_ids(blocks, episode_ids, warnings)
    topics = _normalized_topics(parsed.topic_clusters, episode_ids, warnings)
    flags = _normalized_flags(parsed.review_flags, composer_input, warnings)
    return output_json, parsed.video_summary, blocks, episodes, topics, flags, warnings


def _normalize_timeline_style(
    *,
    summary: _VideoSummaryOutput,
    blocks: list[TimelineBlockCreate],
    episodes: list[TimelineEpisodeCreate],
    topics: list[TimelineTopicClusterCreate],
    flags: list[TimelineReviewFlagCreate],
    warnings: list[str],
) -> tuple[
    _VideoSummaryOutput,
    list[TimelineBlockCreate],
    list[TimelineEpisodeCreate],
    list[TimelineTopicClusterCreate],
    list[TimelineReviewFlagCreate],
]:
    unresolved: list[str] = []

    def normalize(value: str, path: str) -> str:
        normalized = normalize_timeline_style_text(value)
        if normalized.unresolved_endings:
            unresolved.append(f"{path}: {', '.join(normalized.unresolved_endings)}")
        return normalized.text

    normalized_summary = summary.model_copy(
        update={
            "title": normalize(summary.title, "video_summary.title"),
            "summary": normalize(summary.summary, "video_summary.summary"),
            "display_title": summary.display_title,
            "display_summary": summary.display_summary,
        }
    )
    normalized_blocks = [
        TimelineBlockCreate(
            block_id=block.block_id,
            block_index=block.block_index,
            block_type=block.block_type,
            title=normalize(block.title, f"block {block.block_id} title"),
            summary=normalize(block.summary, f"block {block.block_id} summary"),
            display_title=block.display_title,
            display_summary=block.display_summary,
            episode_ids=block.episode_ids,
        )
        for block in blocks
    ]
    normalized_episodes = [
        TimelineEpisodeCreate(
            episode_id=episode.episode_id,
            episode_index=episode.episode_index,
            parent_block_id=episode.parent_block_id,
            start_micro_event_candidate_id=episode.start_micro_event_candidate_id,
            end_micro_event_candidate_id=episode.end_micro_event_candidate_id,
            program_mode=episode.program_mode,
            primary_content_kind=episode.primary_content_kind,
            title=normalize(episode.title, f"episode {episode.episode_id} title"),
            summary=normalize(episode.summary, f"episode {episode.episode_id} summary"),
            display_title=episode.display_title,
            display_summary=episode.display_summary,
            topics=episode.topics,
            viewer_tags=episode.viewer_tags,
            highlight_micro_event_candidate_ids=episode.highlight_micro_event_candidate_ids,
            visibility=episode.visibility,
        )
        for episode in episodes
    ]
    normalized_topics = [
        TimelineTopicClusterCreate(
            topic_id=topic.topic_id,
            topic_index=topic.topic_index,
            label=normalize(topic.label, f"topic {topic.topic_id} label"),
            summary=normalize(topic.summary, f"topic {topic.topic_id} summary"),
            display_label=normalize(
                topic.display_label,
                f"topic {topic.topic_id} display_label",
            ),
            episode_ids=topic.episode_ids,
        )
        for topic in topics
    ]
    normalized_flags = [
        TimelineReviewFlagCreate(
            flag_index=flag.flag_index,
            start_micro_event_candidate_id=flag.start_micro_event_candidate_id,
            end_micro_event_candidate_id=flag.end_micro_event_candidate_id,
            type=flag.type,
            reason=normalize(flag.reason, f"review_flag {flag.flag_index} reason"),
        )
        for flag in flags
    ]
    warnings.extend(f"timeline style unresolved polite ending: {item}" for item in unresolved)
    return (
        normalized_summary,
        normalized_blocks,
        normalized_episodes,
        normalized_topics,
        normalized_flags,
    )


def _composition_create_from_parts(
    composer_input: _ComposerInput,
    result: TimelineComposeResult,
    *,
    output_json: JsonObject,
    summary: _VideoSummaryOutput,
    blocks: list[TimelineBlockCreate],
    episodes: list[TimelineEpisodeCreate],
    topics: list[TimelineTopicClusterCreate],
    flags: list[TimelineReviewFlagCreate],
    warnings: list[str],
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> TimelineCompositionCreate:
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
        raw_response_text=result.final_response,
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
        start_id = composer_input.candidate_id_by_synthetic_id.get(episode.start_micro_event_id)
        end_id = composer_input.candidate_id_by_synthetic_id.get(episode.end_micro_event_id)
        if start_id is None or end_id is None:
            warnings.append(f"episode has invalid micro-event range: {episode_id}")
        if len(episode.highlight_micro_event_ids) > _MAX_EPISODE_HIGHLIGHTS:
            warnings.append(
                f"episode {episode_id} highlight_micro_event_ids truncated "
                f"to {_MAX_EPISODE_HIGHLIGHTS}"
            )
        if len(episode.topics) > _MAX_EPISODE_TOPICS:
            warnings.append(f"episode {episode_id} topics truncated to {_MAX_EPISODE_TOPICS}")
        highlights = [
            candidate_id
            for value in episode.highlight_micro_event_ids[:_MAX_EPISODE_HIGHLIGHTS]
            if (candidate_id := composer_input.candidate_id_by_synthetic_id.get(value)) is not None
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
                viewer_tags=_timeline_viewer_tags(
                    episode.viewer_tags,
                    warnings,
                    f"episode {episode_id} viewer_tags",
                ),
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


def _sort_episodes_by_range(
    episodes: list[TimelineEpisodeCreate],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineEpisodeCreate]:
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }

    def key(episode: TimelineEpisodeCreate) -> int:
        if episode.start_micro_event_candidate_id is None:
            return len(candidate_ids)
        return candidate_index_by_id.get(
            episode.start_micro_event_candidate_id,
            len(candidate_ids),
        )

    sorted_episodes = sorted(episodes, key=key)
    if [episode.episode_id for episode in sorted_episodes] != [
        episode.episode_id for episode in episodes
    ]:
        warnings.append("episodes sorted by micro-event range")
    return [
        _episode_with(episode, episode_index=index)
        for index, episode in enumerate(sorted_episodes, start=1)
    ]


async def _repair_overbroad_episodes(
    *,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    topics: list[TimelineTopicClusterCreate],
    flags: list[TimelineReviewFlagCreate],
    composer_input: _ComposerInput,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    composer: TimelineComposerPort,
    timeout_seconds: int,
    warnings: list[str],
    raw_responses: list[_TimelineRawResponse] | None = None,
    llm_traces: LlmTraceRecorderPort | None = None,
) -> tuple[
    list[TimelineEpisodeCreate],
    list[TimelineBlockCreate],
    list[TimelineTopicClusterCreate],
    list[TimelineReviewFlagCreate],
]:
    candidate_by_id = {candidate.id: candidate for candidate in composer_input.micro_events}
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }
    repaired_episodes = list(episodes)
    repaired_blocks = list(blocks)
    repaired_topics = list(topics)
    repaired_flags = list(flags)
    repairs_attempted = 0
    for episode in episodes:
        if repairs_attempted >= TIMELINE_COMPOSE_MAX_EPISODE_REPAIRS:
            break
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            continue
        candidates, _start_index, _end_index = range_info
        if not _is_overbroad_episode(episode, candidates):
            continue
        repairs_attempted += 1
        repair_prompt = _episode_repair_prompt(
            episode=episode,
            episodes=repaired_episodes,
            blocks=repaired_blocks,
            candidates=candidates,
            composer_input=composer_input,
        )
        trace_recorder = llm_traces or NoopLlmTraceRecorder()
        await trace_recorder.record_event(
            _timeline_trace_event(
                operation="repair_episode",
                phase="repair_requested",
                task=task,
                job=job,
                attempt=attempt,
                composer_input=composer_input,
                repair_index=repairs_attempted,
                target_episode_id=episode.episode_id,
                repair_reason="overbroad_episode",
                prompt_text=repair_prompt,
            )
        )
        started_at = time.monotonic()
        try:
            result = await asyncio.wait_for(
                composer.repair_episode(
                    TimelineEpisodeRepairRequest(
                        prompt=repair_prompt,
                        video_id=composer_input.video.id,
                        video_task_id=task.id,
                        job_id=job.id,
                        job_attempt_id=attempt.id,
                        source_micro_event_task_id=composer_input.source_task.id,
                        target_episode_id=episode.episode_id,
                        model=composer_input.model,
                        reasoning_effort=composer_input.reasoning_effort,
                    )
                ),
                timeout=timeout_seconds,
            )
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_response_received",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repairs_attempted,
                    target_episode_id=episode.episode_id,
                    repair_reason="overbroad_episode",
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    raw_response_text=result.final_response,
                )
            )
            if raw_responses is not None:
                raw_responses.append(
                    _raw_response(
                        "repair_episode",
                        result,
                        target_episode_id=episode.episode_id,
                    )
                )
            repair = _parse_episode_repair(result.final_response)
            replacement = _validated_repair_replacement(
                repair,
                target=episode,
                target_candidates=candidates,
                composer_input=composer_input,
                warnings=warnings,
            )
        except Exception as exc:
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repairs_attempted,
                    target_episode_id=episode.episode_id,
                    repair_reason="overbroad_episode",
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type=exc.__class__.__name__,
                    error_message=str(exc) or exc.__class__.__name__,
                )
            )
            warnings.append(f"episode {episode.episode_id} repair failed: {exc.__class__.__name__}")
            repaired_flags = _append_review_flag(
                repaired_flags,
                start_id=episode.start_micro_event_candidate_id,
                end_id=episode.end_micro_event_candidate_id,
                flag_type="OVERBROAD_EPISODE",
                reason="Overbroad episode repair failed; original episode was kept.",
            )
            continue
        if replacement is None:
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repairs_attempted,
                    target_episode_id=episode.episode_id,
                    repair_reason="overbroad_episode",
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type="TimelineEpisodeRepairKeptOriginal",
                    error_message="Episode repair kept original episode.",
                )
            )
            warnings.append(f"episode {episode.episode_id} repair kept original episode")
            repaired_flags = _append_review_flag(
                repaired_flags,
                start_id=episode.start_micro_event_candidate_id,
                end_id=episode.end_micro_event_candidate_id,
                flag_type="OVERBROAD_EPISODE",
                reason="Episode still appears broad after repair KEEP decision.",
            )
            continue
        replacement_ids = [item.episode_id for item in replacement]
        repaired_episodes = _replace_episode(repaired_episodes, episode.episode_id, replacement)
        repaired_blocks = _replace_block_episode_refs(
            repaired_blocks,
            old_episode_id=episode.episode_id,
            new_episode_ids=replacement_ids,
        )
        repaired_topics = _replace_topic_episode_refs(
            repaired_topics,
            old_episode_id=episode.episode_id,
            new_episode_ids=replacement_ids,
        )
        await trace_recorder.record_event(
            _timeline_trace_event(
                operation="repair_episode",
                phase="repair_succeeded",
                task=task,
                job=job,
                attempt=attempt,
                composer_input=composer_input,
                repair_index=repairs_attempted,
                target_episode_id=episode.episode_id,
                repair_reason="overbroad_episode",
                result=result,
                elapsed_ms=_elapsed_ms(started_at),
                metadata={"replacementCount": len(replacement)},
            )
        )
        warnings.append(f"episode {episode.episode_id} repaired into {len(replacement)} episode(s)")
    return repaired_episodes, repaired_blocks, repaired_topics, repaired_flags


async def _repair_episode_coverage(
    *,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    topics: list[TimelineTopicClusterCreate],
    flags: list[TimelineReviewFlagCreate],
    composer_input: _ComposerInput,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    composer: TimelineComposerPort,
    timeout_seconds: int,
    warnings: list[str],
    raw_responses: list[_TimelineRawResponse] | None = None,
    llm_traces: LlmTraceRecorderPort | None = None,
) -> tuple[
    list[TimelineEpisodeCreate],
    list[TimelineBlockCreate],
    list[TimelineTopicClusterCreate],
    list[TimelineReviewFlagCreate],
]:
    repaired_episodes = list(episodes)
    repaired_blocks = list(blocks)
    repaired_topics = list(topics)
    repaired_flags = list(flags)
    for repair_index in range(1, TIMELINE_COMPOSE_MAX_COVERAGE_REPAIRS + 1):
        plan = _coverage_repair_plan(
            repaired_episodes,
            repaired_blocks,
            composer_input,
            repair_index=repair_index,
        )
        if plan is None:
            break
        repair_prompt = _coverage_repair_prompt(
            plan=plan,
            episodes=repaired_episodes,
            blocks=repaired_blocks,
            composer_input=composer_input,
        )
        trace_recorder = llm_traces or NoopLlmTraceRecorder()
        await trace_recorder.record_event(
            _timeline_trace_event(
                operation="repair_episode",
                phase="repair_requested",
                task=task,
                job=job,
                attempt=attempt,
                composer_input=composer_input,
                repair_index=repair_index,
                target_episode_id=plan.target_episode.episode_id,
                repair_reason="coverage_repair",
                prompt_text=repair_prompt,
            )
        )
        started_at = time.monotonic()
        try:
            result = await asyncio.wait_for(
                composer.repair_episode(
                    TimelineEpisodeRepairRequest(
                        prompt=repair_prompt,
                        video_id=composer_input.video.id,
                        video_task_id=task.id,
                        job_id=job.id,
                        job_attempt_id=attempt.id,
                        source_micro_event_task_id=composer_input.source_task.id,
                        target_episode_id=plan.target_episode.episode_id,
                        model=composer_input.model,
                        reasoning_effort=composer_input.reasoning_effort,
                    )
                ),
                timeout=timeout_seconds,
            )
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_response_received",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repair_index,
                    target_episode_id=plan.target_episode.episode_id,
                    repair_reason="coverage_repair",
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    raw_response_text=result.final_response,
                )
            )
            if raw_responses is not None:
                raw_responses.append(
                    _raw_response(
                        "repair_episode",
                        result,
                        target_episode_id=plan.target_episode.episode_id,
                    )
                )
            repair = _parse_episode_repair(result.final_response)
            replacement = _validated_coverage_repair_replacement(
                repair,
                target=plan.target_episode,
                target_candidates=plan.target_candidates,
                composer_input=composer_input,
                warnings=warnings,
            )
        except Exception as exc:
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repair_index,
                    target_episode_id=plan.target_episode.episode_id,
                    repair_reason="coverage_repair",
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type=exc.__class__.__name__,
                    error_message=str(exc) or exc.__class__.__name__,
                )
            )
            warnings.append(
                f"coverage repair {plan.target_episode.episode_id} failed: {exc.__class__.__name__}"
            )
            break
        if replacement is None:
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repair_index,
                    target_episode_id=plan.target_episode.episode_id,
                    repair_reason="coverage_repair",
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type="TimelineEpisodeRepairKeptInvalidCoverage",
                    error_message="Coverage repair kept invalid coverage.",
                )
            )
            warnings.append(
                f"coverage repair {plan.target_episode.episode_id} kept invalid coverage"
            )
            break
        repaired_episodes, repaired_blocks, repaired_topics = _apply_coverage_repair(
            episodes=repaired_episodes,
            blocks=repaired_blocks,
            topics=repaired_topics,
            plan=plan,
            replacement=replacement,
        )
        warnings.append(
            f"coverage repair {plan.target_episode.episode_id} inserted "
            f"{len(replacement)} episode(s)"
        )
        await trace_recorder.record_event(
            _timeline_trace_event(
                operation="repair_episode",
                phase="repair_succeeded",
                task=task,
                job=job,
                attempt=attempt,
                composer_input=composer_input,
                repair_index=repair_index,
                target_episode_id=plan.target_episode.episode_id,
                repair_reason="coverage_repair",
                result=result,
                elapsed_ms=_elapsed_ms(started_at),
                metadata={"replacementCount": len(replacement)},
            )
        )
    return repaired_episodes, repaired_blocks, repaired_topics, repaired_flags


def _coverage_repair_plan(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
    *,
    repair_index: int,
) -> _CoverageRepairPlan | None:
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    if not candidate_ids:
        return None
    candidate_by_id = {candidate.id: candidate for candidate in composer_input.micro_events}
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }
    valid_ranges: list[tuple[int, int, int]] = []
    next_candidate_index = 0
    for episode_index, episode in enumerate(episodes):
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            next_start = _next_valid_episode_start_index(
                episodes,
                episode_index + 1,
                candidate_ids,
                candidate_index_by_id,
                candidate_by_id,
            )
            target_start_index = min(next_candidate_index, len(candidate_ids) - 1)
            target_end_index = (
                len(candidate_ids) - 1
                if next_start is None
                else max(target_start_index, next_start - 1)
            )
            return _coverage_repair_plan_for_range(
                candidate_ids=candidate_ids,
                candidate_by_id=candidate_by_id,
                episodes=episodes,
                blocks=blocks,
                composer_input=composer_input,
                target_start_index=target_start_index,
                target_end_index=target_end_index,
                replace_start_index=episode_index,
                replace_end_index=episode_index + 1,
                repair_index=repair_index,
            )
        _candidates, start_index, end_index = range_info
        if start_index > next_candidate_index:
            return _coverage_repair_plan_for_range(
                candidate_ids=candidate_ids,
                candidate_by_id=candidate_by_id,
                episodes=episodes,
                blocks=blocks,
                composer_input=composer_input,
                target_start_index=next_candidate_index,
                target_end_index=start_index - 1,
                replace_start_index=episode_index,
                replace_end_index=episode_index,
                repair_index=repair_index,
            )
        if start_index < next_candidate_index:
            overlapping_ranges = [item for item in valid_ranges if item[2] >= start_index]
            if overlapping_ranges:
                replace_start_index, target_start_index, previous_end_index = overlapping_ranges[0]
            else:
                replace_start_index = episode_index
                target_start_index = start_index
                previous_end_index = next_candidate_index - 1
            return _coverage_repair_plan_for_range(
                candidate_ids=candidate_ids,
                candidate_by_id=candidate_by_id,
                episodes=episodes,
                blocks=blocks,
                composer_input=composer_input,
                target_start_index=target_start_index,
                target_end_index=max(end_index, previous_end_index),
                replace_start_index=replace_start_index,
                replace_end_index=episode_index + 1,
                repair_index=repair_index,
            )
        next_candidate_index = end_index + 1
        valid_ranges.append((episode_index, start_index, end_index))
    if next_candidate_index < len(candidate_ids):
        return _coverage_repair_plan_for_range(
            candidate_ids=candidate_ids,
            candidate_by_id=candidate_by_id,
            episodes=episodes,
            blocks=blocks,
            composer_input=composer_input,
            target_start_index=next_candidate_index,
            target_end_index=len(candidate_ids) - 1,
            replace_start_index=len(episodes),
            replace_end_index=len(episodes),
            repair_index=repair_index,
        )
    return None


def _coverage_repair_plan_for_range(
    *,
    candidate_ids: list[int],
    candidate_by_id: dict[int, MicroEventCandidateRecord],
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
    target_start_index: int,
    target_end_index: int,
    replace_start_index: int,
    replace_end_index: int,
    repair_index: int,
) -> _CoverageRepairPlan:
    target_candidates = [
        candidate_by_id[candidate_id]
        for candidate_id in candidate_ids[target_start_index : target_end_index + 1]
    ]
    parent_block_id = _coverage_repair_parent_block_id(
        episodes,
        blocks,
        replace_start_index=replace_start_index,
    )
    target_episode_id = (
        episodes[replace_start_index].episode_id
        if replace_start_index < replace_end_index
        else _coverage_repair_episode_id(episodes, repair_index)
    )
    first_candidate = target_candidates[0]
    program_modes = {candidate.program_mode for candidate in target_candidates}
    content_kinds = {candidate.content_kind for candidate in target_candidates}
    program_mode = (
        cast(TimelineBlockType, first_candidate.program_mode)
        if len(program_modes) == 1 and first_candidate.program_mode in _TIMELINE_BLOCK_TYPES
        else "MIXED"
    )
    primary_content_kind = (
        cast(TimelineContentKind, first_candidate.content_kind)
        if len(content_kinds) == 1 and first_candidate.content_kind in _TIMELINE_CONTENT_KINDS
        else "OTHER"
    )
    topics = list(
        dict.fromkeys(
            topic for candidate in target_candidates for topic in (candidate.topics or [])
        )
    )[:_MAX_EPISODE_TOPICS]
    return _CoverageRepairPlan(
        target_episode=TimelineEpisodeCreate(
            episode_id=target_episode_id,
            episode_index=replace_start_index + 1,
            parent_block_id=parent_block_id,
            start_micro_event_candidate_id=target_candidates[0].id,
            end_micro_event_candidate_id=target_candidates[-1].id,
            program_mode=program_mode,
            primary_content_kind=primary_content_kind,
            title="Coverage recovery segment",
            summary="Repair this segment so timeline episodes cover each micro-event once.",
            display_title="Coverage recovery segment",
            display_summary=(
                "Repair this segment so timeline episodes cover each micro-event once."
            ),
            topics=topics,
            viewer_tags=[],
            highlight_micro_event_candidate_ids=[target_candidates[0].id],
            visibility="DEFAULT",
        ),
        target_candidates=target_candidates,
        replace_start_index=replace_start_index,
        replace_end_index=replace_end_index,
        insert_before_episode_id=(
            episodes[replace_start_index].episode_id
            if replace_start_index == replace_end_index and replace_start_index < len(episodes)
            else None
        ),
    )


def _next_valid_episode_start_index(
    episodes: list[TimelineEpisodeCreate],
    start_episode_index: int,
    candidate_ids: list[int],
    candidate_index_by_id: dict[int, int],
    candidate_by_id: dict[int, MicroEventCandidateRecord],
) -> int | None:
    for episode in episodes[start_episode_index:]:
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            continue
        _candidates, start_index, _end_index = range_info
        return start_index
    return None


def _coverage_repair_parent_block_id(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    *,
    replace_start_index: int,
) -> str:
    if replace_start_index < len(episodes):
        return episodes[replace_start_index].parent_block_id
    if episodes:
        return episodes[-1].parent_block_id
    if blocks:
        return blocks[-1].block_id
    return "block_001"


def _coverage_repair_episode_id(
    episodes: list[TimelineEpisodeCreate],
    repair_index: int,
) -> str:
    existing = {episode.episode_id for episode in episodes}
    candidate = f"episode_recovery_{repair_index:03d}"
    while candidate in existing:
        repair_index += 1
        candidate = f"episode_recovery_{repair_index:03d}"
    return candidate


def _coverage_repair_prompt(
    *,
    plan: _CoverageRepairPlan,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
) -> str:
    before = episodes[max(0, plan.replace_start_index - 2) : plan.replace_start_index]
    after = episodes[plan.replace_end_index : min(len(episodes), plan.replace_end_index + 2)]
    input_json = {
        "video_metadata": {
            "video_id": composer_input.video.id,
            "youtube_video_id": composer_input.video.youtube_video_id,
            "title": composer_input.video.title,
            "streamer_name": composer_input.streamer_name,
            "copy_style": composer_input.copy_style,
        },
        "repair_reason": (
            "The current timeline has a micro-event coverage gap, duplicate, "
            "overlap, or invalid episode range. Rewrite only target_micro_events."
        ),
        "target_episode": _episode_prompt_json(plan.target_episode, composer_input),
        "target_micro_events": [
            _micro_event_input(candidate, composer_input, seq=index)
            for index, candidate in enumerate(plan.target_candidates, start=1)
        ],
        "current_episodes_before_target": [
            _episode_prompt_json(episode, composer_input) for episode in before
        ],
        "current_episodes_replaced_by_target": [
            _episode_prompt_json(episode, composer_input)
            for episode in episodes[plan.replace_start_index : plan.replace_end_index]
        ],
        "current_episodes_after_target": [
            _episode_prompt_json(episode, composer_input) for episode in after
        ],
        "blocks": [
            {
                "block_id": block.block_id,
                "block_type": block.block_type,
                "episode_ids": block.episode_ids,
            }
            for block in blocks
        ],
        "output_rules": {
            "target_episode_id": plan.target_episode.episode_id,
            "action": "SPLIT",
            "coverage": (
                "replacement_episodes must cover every target_micro_events item "
                "exactly once, in input order, using only provided micro_event_id values."
            ),
            "single_episode_allowed": True,
        },
    }
    recovery_instructions = """
# COVERAGE_RECOVERY_TASK

Repair only the target_micro_events segment. Return the same JSON shape as the
episode repair task.

- Set action to "SPLIT".
- replacement_episodes may contain one or more episodes.
- The first replacement must start at the first target_micro_events item.
- The final replacement must end at the final target_micro_events item.
- Adjacent replacements must be contiguous with no gap, overlap, duplicate, or reorder.
- Do not invent micro_event_id values.
- Do not include markdown fences or explanatory text.
""".strip()
    return "\n\n".join(
        [
            composer_input.repair_prompt.body,
            recovery_instructions,
            "# INPUT_DATA",
            json.dumps(input_json, ensure_ascii=False),
        ]
    )


def _validated_coverage_repair_replacement(
    repair: _TimelineEpisodeRepairOutput,
    *,
    target: TimelineEpisodeCreate,
    target_candidates: list[MicroEventCandidateRecord],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineEpisodeCreate] | None:
    if repair.target_episode_id and repair.target_episode_id != target.episode_id:
        raise TimelineCompositionOutputInvalid("Coverage repair target_episode_id does not match.")
    action = repair.action.strip().upper()
    if action == "KEEP":
        return None
    if action not in {"SPLIT", "REPLACE"}:
        raise TimelineCompositionOutputInvalid(f"Unknown coverage repair action: {repair.action}")
    if not repair.replacement_episodes:
        return None
    target_ids = [candidate.id for candidate in target_candidates]
    candidate_index_by_id = {candidate_id: index for index, candidate_id in enumerate(target_ids)}
    covered: list[int] = []
    replacement: list[TimelineEpisodeCreate] = []
    for index, episode in enumerate(repair.replacement_episodes, start=1):
        start_id = composer_input.candidate_id_by_synthetic_id.get(episode.start_micro_event_id)
        end_id = composer_input.candidate_id_by_synthetic_id.get(episode.end_micro_event_id)
        if start_id is None or end_id is None:
            raise TimelineCompositionOutputInvalid("Coverage repair episode has invalid range.")
        start_index = candidate_index_by_id.get(start_id)
        end_index = candidate_index_by_id.get(end_id)
        if start_index is None or end_index is None or end_index < start_index:
            raise TimelineCompositionOutputInvalid(
                "Coverage repair episode range is outside target."
            )
        covered.extend(target_ids[start_index : end_index + 1])
        episode_id = target.episode_id if index == 1 else f"{target.episode_id}_split_{index:03d}"
        replacement.append(
            TimelineEpisodeCreate(
                episode_id=episode_id,
                episode_index=target.episode_index + index - 1,
                parent_block_id=target.parent_block_id,
                start_micro_event_candidate_id=start_id,
                end_micro_event_candidate_id=end_id,
                program_mode=_timeline_block_type(
                    episode.program_mode,
                    warnings,
                    f"coverage repair episode {episode_id} program_mode",
                ),
                primary_content_kind=_timeline_content_kind(
                    episode.primary_content_kind,
                    warnings,
                    f"coverage repair episode {episode_id} primary_content_kind",
                ),
                title=episode.title,
                summary=episode.summary,
                display_title=episode.display_title or episode.title,
                display_summary=episode.display_summary or episode.summary,
                topics=episode.topics[:_MAX_EPISODE_TOPICS],
                viewer_tags=_timeline_viewer_tags(
                    episode.viewer_tags,
                    warnings,
                    f"coverage repair episode {episode_id} viewer_tags",
                ),
                highlight_micro_event_candidate_ids=[
                    candidate_id
                    for value in episode.highlight_micro_event_ids[:_MAX_EPISODE_HIGHLIGHTS]
                    if (candidate_id := composer_input.candidate_id_by_synthetic_id.get(value))
                    is not None
                ],
                visibility=_timeline_visibility(
                    episode.visibility,
                    warnings,
                    f"coverage repair episode {episode_id} visibility",
                ),
            )
        )
    if covered != target_ids:
        raise TimelineCompositionOutputInvalid(
            "Coverage repair replacement does not exactly cover target micro-events."
        )
    return replacement


def _apply_coverage_repair(
    *,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    topics: list[TimelineTopicClusterCreate],
    plan: _CoverageRepairPlan,
    replacement: list[TimelineEpisodeCreate],
) -> tuple[
    list[TimelineEpisodeCreate],
    list[TimelineBlockCreate],
    list[TimelineTopicClusterCreate],
]:
    removed_episode_ids = [
        episode.episode_id
        for episode in episodes[plan.replace_start_index : plan.replace_end_index]
    ]
    replacement_episode_ids = [episode.episode_id for episode in replacement]
    updated_episodes = [
        *episodes[: plan.replace_start_index],
        *replacement,
        *episodes[plan.replace_end_index :],
    ]
    updated_blocks = _apply_coverage_repair_to_blocks(
        blocks=blocks,
        plan=plan,
        removed_episode_ids=removed_episode_ids,
        replacement_episode_ids=replacement_episode_ids,
    )
    updated_topics = _apply_coverage_repair_to_topics(
        topics,
        removed_episode_ids=removed_episode_ids,
        replacement_episode_ids=replacement_episode_ids,
    )
    return (
        [
            _episode_with(episode, episode_index=index)
            for index, episode in enumerate(updated_episodes, start=1)
        ],
        updated_blocks,
        updated_topics,
    )


def _apply_coverage_repair_to_blocks(
    *,
    blocks: list[TimelineBlockCreate],
    plan: _CoverageRepairPlan,
    removed_episode_ids: list[str],
    replacement_episode_ids: list[str],
) -> list[TimelineBlockCreate]:
    if not blocks:
        return [
            TimelineBlockCreate(
                block_id=plan.target_episode.parent_block_id,
                block_index=1,
                block_type=plan.target_episode.program_mode,
                title=plan.target_episode.title,
                summary=plan.target_episode.summary,
                display_title=plan.target_episode.display_title,
                display_summary=plan.target_episode.display_summary,
                episode_ids=replacement_episode_ids,
            )
        ]
    removed = set(removed_episode_ids)
    first_removed_id = removed_episode_ids[0] if removed_episode_ids else None
    inserted = False
    updated: list[TimelineBlockCreate] = []
    for block in blocks:
        episode_ids: list[str] = []
        for episode_id in block.episode_ids:
            if first_removed_id is not None and episode_id == first_removed_id:
                episode_ids.extend(replacement_episode_ids)
                inserted = True
                continue
            if episode_id in removed:
                continue
            if (
                first_removed_id is None
                and plan.insert_before_episode_id is not None
                and episode_id == plan.insert_before_episode_id
            ):
                episode_ids.extend(replacement_episode_ids)
                inserted = True
            episode_ids.append(episode_id)
        if (
            not inserted
            and first_removed_id is None
            and plan.insert_before_episode_id is None
            and block.block_id == plan.target_episode.parent_block_id
        ):
            episode_ids.extend(replacement_episode_ids)
            inserted = True
        updated.append(_block_with(block, episode_ids=episode_ids))
    if not inserted:
        updated[-1] = _block_with(
            updated[-1],
            episode_ids=[*updated[-1].episode_ids, *replacement_episode_ids],
        )
    return updated


def _apply_coverage_repair_to_topics(
    topics: list[TimelineTopicClusterCreate],
    *,
    removed_episode_ids: list[str],
    replacement_episode_ids: list[str],
) -> list[TimelineTopicClusterCreate]:
    if not removed_episode_ids:
        return topics
    removed = set(removed_episode_ids)
    first_removed_id = removed_episode_ids[0]
    updated: list[TimelineTopicClusterCreate] = []
    for topic in topics:
        episode_ids: list[str] = []
        for episode_id in topic.episode_ids:
            if episode_id == first_removed_id:
                episode_ids.extend(replacement_episode_ids)
                continue
            if episode_id in removed:
                continue
            episode_ids.append(episode_id)
        deduped = list(dict.fromkeys(episode_ids))
        if len(deduped) < 2:
            continue
        updated.append(
            TimelineTopicClusterCreate(
                topic_id=topic.topic_id,
                topic_index=len(updated) + 1,
                label=topic.label,
                summary=topic.summary,
                display_label=topic.display_label,
                episode_ids=deduped,
            )
        )
    return updated


def _repair_block_semantics(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> tuple[list[TimelineBlockCreate], list[TimelineEpisodeCreate]]:
    segments = _block_semantic_segments(episodes, blocks, warnings)
    segments = _merge_short_break_segments(segments, warnings)
    segments = _split_post_game_segments(segments, warnings)
    segments = _split_closing_segments(segments, warnings)
    segments = _merge_adjacent_same_type_segments(segments)
    repaired_blocks: list[TimelineBlockCreate] = []
    repaired_episodes: list[TimelineEpisodeCreate] = []
    for block_index, segment in enumerate(segments, start=1):
        block_id = f"block_{block_index:03d}"
        segment_episodes = [
            _episode_with(
                episode,
                episode_index=len(repaired_episodes) + offset,
                parent_block_id=block_id,
            )
            for offset, episode in enumerate(segment.episodes, start=1)
        ]
        repaired_episodes.extend(segment_episodes)
        repaired_blocks.append(
            TimelineBlockCreate(
                block_id=block_id,
                block_index=block_index,
                block_type=segment.block_type,
                title=segment.title,
                summary=segment.summary,
                display_title=segment.display_title,
                display_summary=segment.display_summary,
                episode_ids=[episode.episode_id for episode in segment_episodes],
            )
        )
    return repaired_blocks, repaired_episodes


def _block_semantic_segments(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    warnings: list[str],
) -> list[_BlockSegment]:
    block_by_id = {block.block_id: block for block in blocks}
    episode_ids = {episode.episode_id for episode in episodes}
    block_episode_ids = [
        episode_id
        for block in blocks
        for episode_id in block.episode_ids
        if episode_id in episode_ids
    ]
    if block_episode_ids != [episode.episode_id for episode in episodes]:
        warnings.append("block semantic repair rebuilt block refs from episode order")

    block_id_by_episode_id: dict[str, str] = {}
    for block in blocks:
        for episode_id in block.episode_ids:
            if episode_id in episode_ids and episode_id not in block_id_by_episode_id:
                block_id_by_episode_id[episode_id] = block.block_id

    keyed_segments: list[tuple[str, _BlockSegment]] = []
    for episode in episodes:
        block = block_by_id.get(block_id_by_episode_id.get(episode.episode_id, ""))
        if block is None:
            block = block_by_id.get(episode.parent_block_id)
        segment_key = block.block_id if block is not None else episode.episode_id
        segment = (
            _BlockSegment(
                block_type=block.block_type,
                title=block.title,
                summary=block.summary,
                display_title=block.display_title,
                display_summary=block.display_summary,
                episodes=[episode],
            )
            if block is not None
            else _BlockSegment(
                block_type=episode.program_mode,
                title=episode.title,
                summary=episode.summary,
                display_title=episode.display_title,
                display_summary=episode.display_summary,
                episodes=[episode],
            )
        )
        if keyed_segments and keyed_segments[-1][0] == segment_key:
            previous_key, previous_segment = keyed_segments[-1]
            keyed_segments[-1] = (
                previous_key,
                _segment_with(
                    previous_segment,
                    episodes=[*previous_segment.episodes, episode],
                ),
            )
            continue
        keyed_segments.append((segment_key, segment))
    return [segment for _key, segment in keyed_segments]


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
        if _is_overbroad_episode(episode, candidates):
            append_flag(
                start_id=episode.start_micro_event_candidate_id,
                end_id=episode.end_micro_event_candidate_id,
                flag_type="OVERBROAD_EPISODE",
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


def _is_overbroad_episode(
    episode: TimelineEpisodeCreate,
    candidates: list[MicroEventCandidateRecord],
) -> bool:
    program_modes = {candidate.program_mode for candidate in candidates if candidate.program_mode}
    content_kinds = {candidate.content_kind for candidate in candidates if candidate.content_kind}
    return (
        len(candidates) >= _OVERBROAD_MICRO_EVENT_COUNT
        and (
            len(episode.topics) >= _MAX_EPISODE_TOPICS
            or len(program_modes) >= 3
            or len(content_kinds) >= 3
        )
    ) or (len(candidates) >= _OVERBROAD_LARGE_MICRO_EVENT_COUNT and len(content_kinds) >= 2)


def _append_review_flag(
    flags: list[TimelineReviewFlagCreate],
    *,
    start_id: int | None,
    end_id: int | None,
    flag_type: TimelineReviewFlagType,
    reason: str,
) -> list[TimelineReviewFlagCreate]:
    if start_id is None or end_id is None:
        return flags
    key = (start_id, end_id, flag_type)
    existing = {
        (
            flag.start_micro_event_candidate_id,
            flag.end_micro_event_candidate_id,
            flag.type,
        )
        for flag in flags
    }
    if key in existing:
        return flags
    return [
        *flags,
        TimelineReviewFlagCreate(
            flag_index=len(flags) + 1,
            start_micro_event_candidate_id=start_id,
            end_micro_event_candidate_id=end_id,
            type=flag_type,
            reason=reason,
        ),
    ]


def _episode_repair_prompt(
    *,
    episode: TimelineEpisodeCreate,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    candidates: list[MicroEventCandidateRecord],
    composer_input: _ComposerInput,
) -> str:
    episode_index = next(
        (index for index, item in enumerate(episodes) if item.episode_id == episode.episode_id),
        -1,
    )
    previous_episode = episodes[episode_index - 1] if episode_index > 0 else None
    next_episode = episodes[episode_index + 1] if 0 <= episode_index < len(episodes) - 1 else None
    parent_block = next(
        (block for block in blocks if episode.episode_id in block.episode_ids),
        None,
    )
    input_json = {
        "video_metadata": {
            "video_id": composer_input.video.id,
            "youtube_video_id": composer_input.video.youtube_video_id,
            "title": composer_input.video.title,
            "streamer_name": composer_input.streamer_name,
            "copy_style": composer_input.copy_style,
        },
        "target_episode": _episode_prompt_json(episode, composer_input),
        "target_micro_events": [
            _micro_event_input(candidate, composer_input, seq=index)
            for index, candidate in enumerate(candidates, start=1)
        ],
        "previous_episode": (
            _episode_prompt_json(previous_episode, composer_input)
            if previous_episode is not None
            else None
        ),
        "next_episode": (
            _episode_prompt_json(next_episode, composer_input) if next_episode is not None else None
        ),
        "parent_block": (
            {
                "block_id": parent_block.block_id,
                "block_type": parent_block.block_type,
                "title": parent_block.title,
                "summary": parent_block.summary,
            }
            if parent_block is not None
            else None
        ),
    }
    return "\n\n".join(
        [
            composer_input.repair_prompt.body,
            "# INPUT_DATA",
            json.dumps(input_json, ensure_ascii=False),
        ]
    )


def _parse_episode_repair(text: str) -> _TimelineEpisodeRepairOutput:
    payload = _loads_output_json(text)
    try:
        return _TimelineEpisodeRepairOutput.model_validate(payload)
    except ValidationError as exc:
        raise TimelineCompositionOutputInvalid(str(exc)) from exc


def _validated_repair_replacement(
    repair: _TimelineEpisodeRepairOutput,
    *,
    target: TimelineEpisodeCreate,
    target_candidates: list[MicroEventCandidateRecord],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineEpisodeCreate] | None:
    if repair.target_episode_id and repair.target_episode_id != target.episode_id:
        raise TimelineCompositionOutputInvalid("Repair target_episode_id does not match.")
    action = repair.action.strip().upper()
    if action == "KEEP":
        return None
    if action != "SPLIT":
        raise TimelineCompositionOutputInvalid(f"Unknown repair action: {repair.action}")
    if len(repair.replacement_episodes) < 2:
        return None
    target_ids = [candidate.id for candidate in target_candidates]
    candidate_index_by_id = {candidate_id: index for index, candidate_id in enumerate(target_ids)}
    covered: list[int] = []
    replacement: list[TimelineEpisodeCreate] = []
    for index, episode in enumerate(repair.replacement_episodes, start=1):
        start_id = composer_input.candidate_id_by_synthetic_id.get(episode.start_micro_event_id)
        end_id = composer_input.candidate_id_by_synthetic_id.get(episode.end_micro_event_id)
        if start_id is None or end_id is None:
            raise TimelineCompositionOutputInvalid("Repair episode has invalid range.")
        start_index = candidate_index_by_id.get(start_id)
        end_index = candidate_index_by_id.get(end_id)
        if start_index is None or end_index is None or end_index < start_index:
            raise TimelineCompositionOutputInvalid("Repair episode range is outside target.")
        covered.extend(target_ids[start_index : end_index + 1])
        episode_id = target.episode_id if index == 1 else f"{target.episode_id}_split_{index:03d}"
        replacement.append(
            TimelineEpisodeCreate(
                episode_id=episode_id,
                episode_index=target.episode_index + index - 1,
                parent_block_id=target.parent_block_id,
                start_micro_event_candidate_id=start_id,
                end_micro_event_candidate_id=end_id,
                program_mode=_timeline_block_type(
                    episode.program_mode,
                    warnings,
                    f"repair episode {episode_id} program_mode",
                ),
                primary_content_kind=_timeline_content_kind(
                    episode.primary_content_kind,
                    warnings,
                    f"repair episode {episode_id} primary_content_kind",
                ),
                title=episode.title,
                summary=episode.summary,
                display_title=episode.display_title or episode.title,
                display_summary=episode.display_summary or episode.summary,
                topics=episode.topics[:_MAX_EPISODE_TOPICS],
                viewer_tags=_timeline_viewer_tags(
                    episode.viewer_tags,
                    warnings,
                    f"repair episode {episode_id} viewer_tags",
                ),
                highlight_micro_event_candidate_ids=[
                    candidate_id
                    for value in episode.highlight_micro_event_ids[:_MAX_EPISODE_HIGHLIGHTS]
                    if (candidate_id := composer_input.candidate_id_by_synthetic_id.get(value))
                    is not None
                ],
                visibility=_timeline_visibility(
                    episode.visibility,
                    warnings,
                    f"repair episode {episode_id} visibility",
                ),
            )
        )
    if covered != target_ids:
        raise TimelineCompositionOutputInvalid(
            "Repair replacement does not exactly cover target micro-events."
        )
    return replacement


def _replace_episode(
    episodes: list[TimelineEpisodeCreate],
    old_episode_id: str,
    replacement: list[TimelineEpisodeCreate],
) -> list[TimelineEpisodeCreate]:
    updated: list[TimelineEpisodeCreate] = []
    for episode in episodes:
        if episode.episode_id == old_episode_id:
            updated.extend(replacement)
        else:
            updated.append(episode)
    return [
        _episode_with(episode, episode_index=index)
        for index, episode in enumerate(updated, start=1)
    ]


def _replace_block_episode_refs(
    blocks: list[TimelineBlockCreate],
    *,
    old_episode_id: str,
    new_episode_ids: list[str],
) -> list[TimelineBlockCreate]:
    updated: list[TimelineBlockCreate] = []
    for block in blocks:
        episode_ids: list[str] = []
        for episode_id in block.episode_ids:
            if episode_id == old_episode_id:
                episode_ids.extend(new_episode_ids)
            else:
                episode_ids.append(episode_id)
        updated.append(_block_with(block, episode_ids=episode_ids))
    return updated


def _replace_topic_episode_refs(
    topics: list[TimelineTopicClusterCreate],
    *,
    old_episode_id: str,
    new_episode_ids: list[str],
) -> list[TimelineTopicClusterCreate]:
    updated: list[TimelineTopicClusterCreate] = []
    for topic in topics:
        episode_ids: list[str] = []
        for episode_id in topic.episode_ids:
            if episode_id == old_episode_id:
                episode_ids.extend(new_episode_ids)
            else:
                episode_ids.append(episode_id)
        updated.append(
            TimelineTopicClusterCreate(
                topic_id=topic.topic_id,
                topic_index=topic.topic_index,
                label=topic.label,
                summary=topic.summary,
                display_label=topic.display_label,
                episode_ids=list(dict.fromkeys(episode_ids)),
            )
        )
    return updated


def _merge_short_break_segments(
    segments: list[_BlockSegment],
    warnings: list[str],
) -> list[_BlockSegment]:
    result: list[_BlockSegment] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        if (
            segment.block_type == "BREAK"
            and len(segment.episodes) <= _SHORT_BREAK_EPISODE_COUNT
            and index > 0
            and index < len(segments) - 1
        ):
            break_episodes = [
                _episode_with(
                    episode,
                    program_mode="BREAK",
                    primary_content_kind="BREAK_TIME",
                    visibility="COLLAPSED",
                )
                for episode in segment.episodes
            ]
            if result:
                previous = result[-1]
                result[-1] = _segment_with(
                    previous,
                    episodes=[*previous.episodes, *break_episodes],
                )
            else:
                next_segment = segments[index + 1]
                segments[index + 1] = _segment_with(
                    next_segment,
                    episodes=[*break_episodes, *next_segment.episodes],
                )
            warnings.append("short BREAK block merged into neighboring block")
            index += 1
            continue
        result.append(segment)
        index += 1
    return result


def _split_post_game_segments(
    segments: list[_BlockSegment],
    warnings: list[str],
) -> list[_BlockSegment]:
    result: list[_BlockSegment] = []
    for segment in segments:
        if segment.block_type != "POST_GAME":
            result.append(segment)
            continue
        split_index = _first_daily_post_game_run(segment.episodes)
        if split_index is None:
            result.append(segment)
            continue
        before = segment.episodes[:split_index]
        after = [
            _episode_with(episode, program_mode="JUST_CHATTING")
            for episode in segment.episodes[split_index:]
        ]
        if before:
            result.append(_segment_with(segment, episodes=before))
        result.append(_segment_with(segment, block_type="JUST_CHATTING", episodes=after))
        warnings.append("POST_GAME block split when unrelated daily chat started")
    return result


def _split_closing_segments(
    segments: list[_BlockSegment],
    warnings: list[str],
) -> list[_BlockSegment]:
    result: list[_BlockSegment] = []
    for segment in segments:
        if segment.block_type != "CLOSING":
            result.append(segment)
            continue
        first_closing = next(
            (
                index
                for index, episode in enumerate(segment.episodes)
                if _is_explicit_closing_episode(episode)
            ),
            None,
        )
        if first_closing is None:
            result.append(
                _segment_with(
                    segment,
                    block_type="JUST_CHATTING",
                    episodes=[
                        _episode_with(episode, program_mode="JUST_CHATTING")
                        for episode in segment.episodes
                    ],
                )
            )
            warnings.append("CLOSING block changed to JUST_CHATTING without closing terms")
            continue
        if first_closing == 0:
            result.append(segment)
            continue
        result.append(
            _segment_with(
                segment,
                block_type="JUST_CHATTING",
                episodes=[
                    _episode_with(episode, program_mode="JUST_CHATTING")
                    for episode in segment.episodes[:first_closing]
                ],
            )
        )
        result.append(_segment_with(segment, episodes=segment.episodes[first_closing:]))
        warnings.append("CLOSING block split after non-closing daily chat prefix")
    return result


def _merge_adjacent_same_type_segments(
    segments: list[_BlockSegment],
) -> list[_BlockSegment]:
    merged: list[_BlockSegment] = []
    for segment in segments:
        if merged and merged[-1].block_type == segment.block_type:
            previous = merged[-1]
            merged[-1] = _segment_with(
                previous,
                episodes=[*previous.episodes, *segment.episodes],
            )
            continue
        merged.append(segment)
    return merged


def _first_daily_post_game_run(
    episodes: list[TimelineEpisodeCreate],
) -> int | None:
    for index in range(len(episodes) - 1):
        if _is_daily_chat_after_game(episodes[index]) and _is_daily_chat_after_game(
            episodes[index + 1]
        ):
            return index
    return None


def _is_daily_chat_after_game(episode: TimelineEpisodeCreate) -> bool:
    if episode.primary_content_kind not in _POST_GAME_DAILY_CONTENT_KINDS:
        return False
    if episode.primary_content_kind in _GAME_RELATED_CONTENT_KINDS:
        return False
    if episode.program_mode in {"GAMEPLAY", "GAME_SETUP"}:
        return False
    text = _episode_text(episode).casefold()
    return not any(token in text for token in ("게임", "엔딩", "스토리", "플레이", "game"))


def _is_explicit_closing_episode(episode: TimelineEpisodeCreate) -> bool:
    text = _episode_text(episode).casefold()
    return any(term in text for term in _CLOSING_TERMS)


def _episode_text(episode: TimelineEpisodeCreate) -> str:
    return " ".join(
        [
            episode.title,
            episode.summary,
            episode.display_title,
            episode.display_summary,
            *episode.topics,
        ]
    )


def _episode_prompt_json(
    episode: TimelineEpisodeCreate,
    composer_input: _ComposerInput,
) -> JsonObject:
    return {
        "episode_id": episode.episode_id,
        "start_micro_event_id": _synthetic_candidate_id(
            composer_input,
            episode.start_micro_event_candidate_id,
        ),
        "end_micro_event_id": _synthetic_candidate_id(
            composer_input,
            episode.end_micro_event_candidate_id,
        ),
        "program_mode": episode.program_mode,
        "primary_content_kind": episode.primary_content_kind,
        "title": episode.title,
        "summary": episode.summary,
        "display_title": episode.display_title,
        "display_summary": episode.display_summary,
        "topics": episode.topics,
        "viewer_tags": episode.viewer_tags,
        "visibility": episode.visibility,
    }


def _synthetic_candidate_id(
    composer_input: _ComposerInput,
    candidate_id: int | None,
) -> str | None:
    if candidate_id is None:
        return None
    return composer_input.synthetic_id_by_candidate_id.get(candidate_id)


def _segment_with(
    segment: _BlockSegment,
    *,
    block_type: TimelineBlockType | None = None,
    episodes: list[TimelineEpisodeCreate] | None = None,
) -> _BlockSegment:
    return _BlockSegment(
        block_type=block_type or segment.block_type,
        title=segment.title,
        summary=segment.summary,
        display_title=segment.display_title,
        display_summary=segment.display_summary,
        episodes=episodes if episodes is not None else segment.episodes,
    )


def _block_with(
    block: TimelineBlockCreate,
    *,
    episode_ids: list[str],
) -> TimelineBlockCreate:
    return TimelineBlockCreate(
        block_id=block.block_id,
        block_index=block.block_index,
        block_type=block.block_type,
        title=block.title,
        summary=block.summary,
        display_title=block.display_title,
        display_summary=block.display_summary,
        episode_ids=episode_ids,
    )


def _episode_with(
    episode: TimelineEpisodeCreate,
    *,
    episode_index: int | None = None,
    parent_block_id: str | None = None,
    program_mode: TimelineBlockType | None = None,
    primary_content_kind: TimelineContentKind | None = None,
    visibility: TimelineVisibility | None = None,
) -> TimelineEpisodeCreate:
    return TimelineEpisodeCreate(
        episode_id=episode.episode_id,
        episode_index=episode_index if episode_index is not None else episode.episode_index,
        parent_block_id=parent_block_id or episode.parent_block_id,
        start_micro_event_candidate_id=episode.start_micro_event_candidate_id,
        end_micro_event_candidate_id=episode.end_micro_event_candidate_id,
        program_mode=program_mode or episode.program_mode,
        primary_content_kind=primary_content_kind or episode.primary_content_kind,
        title=episode.title,
        summary=episode.summary,
        display_title=episode.display_title,
        display_summary=episode.display_summary,
        topics=episode.topics,
        viewer_tags=episode.viewer_tags,
        highlight_micro_event_candidate_ids=episode.highlight_micro_event_candidate_ids,
        visibility=visibility or episode.visibility,
    )


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


def _validate_timeline_invariants(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
) -> None:
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    candidate_by_id = {candidate.id: candidate for candidate in composer_input.micro_events}
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }
    next_candidate_index = 0
    for episode in episodes:
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            raise TimelineCompositionOutputInvalid(
                f"Episode has invalid micro-event range: {episode.episode_id}"
            )
        _candidates, start_index, end_index = range_info
        if start_index != next_candidate_index:
            raise TimelineCompositionOutputInvalid(
                "Timeline episodes must cover every micro-event exactly once in order."
            )
        next_candidate_index = end_index + 1
    if next_candidate_index != len(candidate_ids):
        raise TimelineCompositionOutputInvalid("Timeline episodes do not cover all micro-events.")

    episode_ids = [episode.episode_id for episode in episodes]
    block_episode_ids = [episode_id for block in blocks for episode_id in block.episode_ids]
    if block_episode_ids != episode_ids:
        raise TimelineCompositionOutputInvalid(
            "Timeline blocks must contain every episode exactly once in order."
        )
    episode_index_by_id = {episode_id: index for index, episode_id in enumerate(episode_ids)}
    for block in blocks:
        indexes = [episode_index_by_id[episode_id] for episode_id in block.episode_ids]
        if not indexes:
            raise TimelineCompositionOutputInvalid("Timeline block cannot be empty.")
        expected = list(range(indexes[0], indexes[-1] + 1))
        if indexes != expected:
            raise TimelineCompositionOutputInvalid(
                f"Timeline block has non-contiguous episodes: {block.block_id}"
            )
        for episode_id in block.episode_ids:
            episode = episodes[episode_index_by_id[episode_id]]
            if episode.parent_block_id != block.block_id:
                raise TimelineCompositionOutputInvalid(
                    f"Episode parent block mismatch: {episode.episode_id}"
                )


def _timeline_output_json(
    *,
    summary: _VideoSummaryOutput,
    blocks: list[TimelineBlockCreate],
    episodes: list[TimelineEpisodeCreate],
    topics: list[TimelineTopicClusterCreate],
    flags: list[TimelineReviewFlagCreate],
    composer_input: _ComposerInput,
) -> JsonObject:
    return {
        "video_summary": {
            "title": summary.title or composer_input.video.title,
            "summary": summary.summary,
            "display_title": summary.display_title or summary.title or composer_input.video.title,
            "display_summary": summary.display_summary or summary.summary,
            "main_topics": summary.main_topics,
        },
        "blocks": [
            {
                "block_id": block.block_id,
                "block_type": block.block_type,
                "title": block.title,
                "summary": block.summary,
                "display_title": block.display_title,
                "display_summary": block.display_summary,
                "episode_ids": block.episode_ids,
            }
            for block in blocks
        ],
        "episodes": [
            {
                "episode_id": episode.episode_id,
                "parent_block_id": episode.parent_block_id,
                "start_micro_event_id": _synthetic_candidate_id(
                    composer_input,
                    episode.start_micro_event_candidate_id,
                ),
                "end_micro_event_id": _synthetic_candidate_id(
                    composer_input,
                    episode.end_micro_event_candidate_id,
                ),
                "program_mode": episode.program_mode,
                "primary_content_kind": episode.primary_content_kind,
                "title": episode.title,
                "summary": episode.summary,
                "display_title": episode.display_title,
                "display_summary": episode.display_summary,
                "topics": episode.topics,
                "viewer_tags": episode.viewer_tags,
                "highlight_micro_event_ids": [
                    synthetic_id
                    for candidate_id in episode.highlight_micro_event_candidate_ids
                    if (
                        synthetic_id := _synthetic_candidate_id(
                            composer_input,
                            candidate_id,
                        )
                    )
                    is not None
                ],
                "visibility": episode.visibility,
            }
            for episode in episodes
        ],
        "topic_clusters": [
            {
                "topic_id": topic.topic_id,
                "label": topic.label,
                "summary": topic.summary,
                "display_label": topic.display_label,
                "episode_ids": topic.episode_ids,
            }
            for topic in topics
        ],
        "review_flags": [
            {
                "start_micro_event_id": _synthetic_candidate_id(
                    composer_input,
                    flag.start_micro_event_candidate_id,
                ),
                "end_micro_event_id": _synthetic_candidate_id(
                    composer_input,
                    flag.end_micro_event_candidate_id,
                ),
                "type": flag.type,
                "reason": flag.reason,
            }
            for flag in flags
        ],
    }


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


def _timeline_viewer_tags(
    values: list[str],
    warnings: list[str],
    context: str,
) -> list[TimelineViewerTag]:
    normalized: list[TimelineViewerTag] = []
    seen: set[str] = set()
    for value in values:
        tag = value.strip().upper()
        if tag not in _TIMELINE_VIEWER_TAGS:
            replacement = _VIEWER_TAG_CONTENT_KIND_ALIASES.get(tag)
            if replacement is None:
                if tag in _VIEWER_TAG_CONTENT_KIND_ALIASES:
                    warnings.append(
                        f"{context} removed content kind value from viewer_tags: {value}"
                    )
                else:
                    warnings.append(f"{context} removed unknown viewer tag: {value}")
                continue
            warnings.append(
                f"{context} mapped content kind value in viewer_tags: {value} -> {replacement}"
            )
            tag = replacement
        if tag in seen:
            warnings.append(f"{context} duplicate viewer tag removed: {tag}")
            continue
        seen.add(tag)
        normalized.append(cast(TimelineViewerTag, tag))
    return normalized


def _timeline_review_flag_type(
    value: str,
    warnings: list[str],
    context: str,
) -> TimelineReviewFlagType:
    normalized = value.strip().upper()
    if normalized == "OVERBROAD_MICRO_EVENT":
        warnings.append(f"{context} migrated OVERBROAD_MICRO_EVENT to OVERBROAD_EPISODE")
        return "OVERBROAD_EPISODE"
    if normalized in _TIMELINE_REVIEW_FLAG_TYPES:
        return cast(TimelineReviewFlagType, normalized)
    warnings.append(f"{context} had unknown value '{value}', replaced with BOUNDARY_AMBIGUOUS")
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


def _timeline_domain_entries(
    composer_input: _ComposerInput,
) -> list[DomainKnowledgePromptEntryRecord]:
    text = _timeline_domain_match_text(composer_input)
    selected: list[DomainKnowledgePromptEntryRecord] = []
    for entry in composer_input.domain_entries:
        if entry.prompt_policy == "ALWAYS_FOR_SCOPED_STREAMER":
            selected.append(entry)
            continue
        if entry.prompt_policy == "AUTO_ON_MATCH" and _domain_entry_matches_text(
            entry,
            text,
        ):
            selected.append(entry)
    selected.sort(key=lambda entry: (-entry.priority, entry.entry_id))
    return selected[:TIMELINE_DOMAIN_KNOWLEDGE_PROMPT_ENTRY_LIMIT]


def _timeline_domain_match_text(composer_input: _ComposerInput) -> str:
    values = [composer_input.video.title, composer_input.streamer_name or ""]
    for candidate in composer_input.micro_events:
        values.append(candidate.event)
        values.extend(candidate.topics or [])
    return " ".join(value for value in values if value).casefold()


def _domain_entry_matches_text(
    entry: DomainKnowledgePromptEntryRecord,
    text: str,
) -> bool:
    values = [entry.canonical_name, entry.display_name]
    values.extend(alias.surface_form for alias in entry.aliases)
    return any(value.strip().casefold() in text for value in values if value)


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


def _prompt_metadata_json(prompt: ResolvedPrompt) -> JsonObject:
    return {
        "promptVersionId": prompt.version_id,
        "promptVersion": prompt.version_label,
        "promptSha256": prompt.body_sha256,
        "promptSource": prompt.source,
    }


def _task_input_hash(
    *,
    video: VideoRecord,
    source_task: VideoTaskRecord,
    source_fingerprint: str,
    copy_style: CopyStyle,
    model: CodexModelChoice,
    reasoning_effort: ReasoningEffortChoice,
    prompt: ResolvedPrompt,
) -> str:
    payload = {
        "copyStyle": copy_style,
        "model": model,
        **_prompt_metadata_json(prompt),
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
    prompt: ResolvedPrompt,
) -> JsonObject:
    return {
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
        "sourceMicroEventTaskId": source_task.id,
        "sourceMicroEventFingerprint": source_fingerprint,
        "taskVersion": TIMELINE_COMPOSE_TASK_VERSION,
        **_prompt_metadata_json(prompt),
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
    raw_responses: list[_TimelineRawResponse] | None = None,
) -> JsonObject:
    output: JsonObject = {
        "videoId": composer_input.video.id,
        "youtubeVideoId": composer_input.video.youtube_video_id,
        "sourceMicroEventTaskId": composer_input.source_task.id,
        "copyStyle": composer_input.copy_style,
        "model": composer_input.model,
        "reasoningEffort": composer_input.reasoning_effort,
        "jobId": job.id,
        "jobAttemptId": attempt.id,
    }
    if raw_responses is not None:
        output.update(_raw_response_summary(raw_responses))
    return output


def _failed_attempt_output_json(
    composer_input: _ComposerInput,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    error_type: str,
    error_message: str,
    stage: str,
    raw_responses: list[_TimelineRawResponse],
) -> JsonObject:
    output = _attempt_output_json(
        composer_input,
        job=job,
        attempt=attempt,
        raw_responses=raw_responses,
    )
    output["failure"] = {
        "errorType": error_type,
        "errorMessage": error_message,
        "stage": stage,
    }
    output["rawResponses"] = [_raw_response_json(item) for item in raw_responses]
    return output


def _raw_response(
    operation: str,
    result: TimelineComposeResult | TimelineEpisodeRepairResult,
    *,
    target_episode_id: str | None = None,
) -> _TimelineRawResponse:
    return _TimelineRawResponse(
        operation=operation,
        thread_id=result.thread_id,
        turn_id=result.turn_id,
        status=result.status,
        raw_response_text=result.final_response,
        target_episode_id=target_episode_id,
    )


def _raw_response_json(response: _TimelineRawResponse) -> JsonObject:
    payload: JsonObject = {
        "operation": response.operation,
        "threadId": response.thread_id,
        "turnId": response.turn_id,
        "status": response.status,
        "rawResponseText": response.raw_response_text,
        "rawResponseLength": len(response.raw_response_text),
        "rawResponseSha256": _raw_response_sha256(response.raw_response_text),
    }
    if response.target_episode_id is not None:
        payload["targetEpisodeId"] = response.target_episode_id
    return payload


def _raw_response_summary(
    raw_responses: list[_TimelineRawResponse],
) -> JsonObject:
    return {
        "rawResponseCount": len(raw_responses),
        "rawResponseSha256s": [
            _raw_response_sha256(response.raw_response_text) for response in raw_responses
        ],
        "rawResponseLengths": [len(response.raw_response_text) for response in raw_responses],
        "rawResponseStoredIn": _TIMELINE_RAW_RESPONSE_STORED_IN,
    }


def _raw_response_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _log_timeline_failure(
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    raw_responses: list[_TimelineRawResponse],
) -> None:
    summary = _raw_response_summary(raw_responses)
    logger.error(
        "Timeline compose failed task_id=%s video_id=%s job_id=%s "
        "job_attempt_id=%s raw_response_count=%s raw_response_sha256s=%s",
        task.id,
        task.video_id,
        job.id,
        attempt.id,
        summary["rawResponseCount"],
        summary["rawResponseSha256s"],
    )


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
