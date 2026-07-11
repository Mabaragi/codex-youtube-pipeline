from __future__ import annotations

import asyncio
import time
from typing import cast

from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainKnowledgeRepositoryPort,
)
from codex_sdk_cli.domains.llm_traces.ports import LlmTraceRecorderPort, NoopLlmTraceRecorder
from codex_sdk_cli.domains.micro_events.constants import MICRO_EVENT_EXTRACT_TASK_NAME
from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventExtractionRepositoryPort,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventRecorderPort,
)
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

from .composition import (
    _composition_create as _composition_create,
)
from .composition import (
    _composition_create_with_repairs,
)
from .constants import (
    TIMELINE_COMPOSE_BATCH_SCAN_LIMIT,
    TIMELINE_COMPOSE_DEFAULT_COPY_STYLE,
    TIMELINE_COMPOSE_DEFAULT_REASONING_EFFORT,
)
from .exceptions import (
    TimelineCompositionNotFound,
    TimelineCompositionOutputInvalid,
    TimelineCompositionPreconditionFailed,
)
from .models import (
    _ComposerInput,
    _EnqueueCounters,
    _PreparedTimelineCompose,
    _TimelineRawResponse,
)
from .ports import (
    CopyStyle,
    TimelineComposeRequest,
    TimelineComposerPort,
    TimelineCompositionRepositoryPort,
)
from .responses import (
    _attempt_output_json,
    _enqueue_item,
    _enqueue_response,
    _failed_attempt_output_json,
    _output_json,
    _timeline_response,
)
from .schemas import (
    TimelineComposeEnqueueItemResponse,
    TimelineComposeEnqueueRequest,
    TimelineComposeEnqueueResponse,
    TimelineCompositionResponse,
)
from .task_events import TimelineTaskEventRecorder
from .task_inputs import (
    _flatten_micro_events,
    _int_output,
    _micro_event_count,
    _model_output,
    _reasoning_effort_output,
    _required_int,
    _required_str,
    _source_micro_event_fingerprint,
    _str_output,
    _task_input_hash,
    _task_input_json,
    _timeline_prompt,
)
from .tracing import (
    _elapsed_ms,
    _log_timeline_failure,
    _raw_response,
    _timeline_trace_event,
)

TIMELINE_COMPOSE_WORKER_ID_PREFIX = "timeline-compose-worker:"


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
        self._task_events = TimelineTaskEventRecorder(events)
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
            if candidate.video.is_embeddable is False and not request.include_non_embeddable:
                counters.ineligible_count += 1
                continue
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
        await self._task_events.record(
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
        if video.is_embeddable is False and not request.include_non_embeddable:
            counters.ineligible_count += 1
            return _enqueue_item(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                task=None,
                status="skipped",
                reason="not_embeddable",
                source_task_id=None,
                model=request.model,
                reasoning_effort=request.reasoning_effort,
                copy_style=request.copy_style,
            )
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
            await self._task_events.record(
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
            await self._task_events.record(
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
            await self._task_events.record(
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
        await self._task_events.record(
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
