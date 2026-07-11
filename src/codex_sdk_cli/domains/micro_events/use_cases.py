from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
from codex_sdk_cli.domains.codex.choices import (
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainKnowledgePromptEntryRecord,
    DomainKnowledgeRepositoryPort,
)
from codex_sdk_cli.domains.llm_traces.ports import (
    LlmTraceRecorderPort,
    NoopLlmTraceRecorder,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventActorType,
    OperationEventRecorderPort,
    OperationEventSeverity,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobCreate,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
)
from codex_sdk_cli.domains.prompts.constants import MICRO_EVENT_EXTRACT_PROMPT_KEY
from codex_sdk_cli.domains.prompts.ports import PromptResolverPort, ResolvedPrompt
from codex_sdk_cli.domains.streamers.ports import StreamerRepositoryPort
from codex_sdk_cli.domains.transcript_cues.ports import (
    TranscriptCueRecord,
    TranscriptCueRepositoryPort,
)
from codex_sdk_cli.domains.video_tasks.constants import (
    TRANSCRIPT_CUE_GENERATE_TASK_NAME,
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
from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    YouTubeTranscriptMetadataNotFound,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataFilters,
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptRepositoryPort,
)

from .constants import (
    MICRO_EVENT_EXTRACT_TASK_NAME,
    MICRO_EVENT_EXTRACT_TASK_VERSION,
    MICRO_EVENT_EXTRACT_WORKER_ID,
)
from .exceptions import (
    MicroEventExtractionNotFound,
    MicroEventExtractionOutputInvalid,
    MicroEventExtractionPreconditionFailed,
)
from .ports import (
    MicroEventExtractionDetailRecord,
    MicroEventExtractionRepositoryPort,
    MicroEventExtractionRequest,
    MicroEventExtractionWindowCreate,
    MicroEventExtractorPort,
)
from .repair import MicroEventWindowRepairService
from .responses import (
    _asr_count,
    _detail_response,
    _enqueue_item,
    _enqueue_item_from_task,
    _enqueue_response,
    _EnqueueCounters,
    _excluded_range_count,
    _extract_response,
    _first_cue_id,
    _int_output,
    _last_cue_id,
    _micro_event_count,
    _model_output,
    _reasoning_effort_output,
    _required_int,
    _skipped_extract_response,
    _str_output,
    _window_count,
)
from .schemas import (
    MicroEventBatchExtractRequest,
    MicroEventBatchExtractResponse,
    MicroEventEnqueueItemResponse,
    MicroEventEnqueueRequest,
    MicroEventEnqueueResponse,
    MicroEventExtractionDetailResponse,
    MicroEventExtractRequest,
    MicroEventExtractResponse,
)
from .task_events import MicroEventTaskEventRecorder
from .task_inputs import (
    _domain_knowledge_fingerprint,
    _prompt_metadata_json,
    _single_extract_request,
    _task_input_hash,
    _task_input_json,
)
from .tracing import (
    _elapsed_ms,
    _micro_event_validation_failure_phase,
    _micro_trace_event,
    _window_retry_metadata,
)
from .window_results import (
    _failed_window,
    _MicroEventWindowValidationFailure,
    _partial_resume_metadata,
    _partial_resume_plan,
    _runtime_failed_window,
    _sorted_windows,
    _validated_window,
)
from .windowing import (
    _cue_windows,
    _CueWindow,
    _ExtractionExecutionInput,
    _window_prompt,
)

MICRO_EVENT_EXTRACT_VIDEO_TASK_CONCURRENCY_LIMIT = 1
MICRO_EVENT_EXTRACT_BATCH_SCAN_LIMIT = 500


@dataclass(frozen=True, slots=True)
class _PreparedExtraction:
    execution_input: _ExtractionExecutionInput
    input_hash: str
    input_json: JsonObject


_MICRO_EVENT_WINDOW_MAX_RETRY_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class _MicroEventWindowRuntimeFailure:
    cue_window: _CueWindow
    error: Exception
    failed_window: MicroEventExtractionWindowCreate


@dataclass(frozen=True, slots=True)
class _MicroEventWindowBatchResult:
    windows: dict[int, MicroEventExtractionWindowCreate]
    validation_failures: dict[int, _MicroEventWindowValidationFailure]
    runtime_failures: dict[int, _MicroEventWindowRuntimeFailure]


@dataclass(frozen=True, slots=True)
class _MicroEventWindowFinalFailures:
    validation_failures: dict[int, _MicroEventWindowValidationFailure]
    runtime_failures: dict[int, _MicroEventWindowRuntimeFailure]


@dataclass(slots=True)
class _MicroEventWindowRunStats:
    resumed_window_indices: set[int] = field(default_factory=set)
    executed_window_indices: set[int] = field(default_factory=set)
    failed_window_indices: set[int] = field(default_factory=set)


class ExtractVideoMicroEventsUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        transcripts: YouTubeTranscriptRepositoryPort,
        transcript_cues: TranscriptCueRepositoryPort,
        channels: ChannelRepositoryPort,
        streamers: StreamerRepositoryPort,
        domain_knowledge: DomainKnowledgeRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        micro_events: MicroEventExtractionRepositoryPort,
        extractor: MicroEventExtractorPort,
        prompt_resolver: PromptResolverPort,
        timeout_seconds: int,
        concurrency_limit: int,
        model: CodexModelChoice,
        reasoning_effort: ReasoningEffortChoice,
        events: OperationEventRecorderPort,
        llm_traces: LlmTraceRecorderPort | None = None,
    ) -> None:
        self._videos = videos
        self._video_tasks = video_tasks
        self._transcripts = transcripts
        self._transcript_cues = transcript_cues
        self._channels = channels
        self._streamers = streamers
        self._domain_knowledge = domain_knowledge
        self._pipeline_jobs = pipeline_jobs
        self._micro_events = micro_events
        self._extractor = extractor
        self._prompt_resolver = prompt_resolver
        self._timeout_seconds = timeout_seconds
        self._concurrency_limit = concurrency_limit
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._task_events = MicroEventTaskEventRecorder(events)
        self._llm_traces = llm_traces or NoopLlmTraceRecorder()
        self._window_repair = MicroEventWindowRepairService(
            extractor=self._extractor,
            llm_traces=self._llm_traces,
            task_events=self._task_events,
        )

    async def execute(
        self,
        video_id: int,
        request: MicroEventExtractRequest,
    ) -> MicroEventExtractResponse:
        video = await self._videos.get_video(video_id)
        if video is None:
            raise VideoNotFound("Video not found.")
        if video.is_embeddable is False and not request.include_non_embeddable:
            return _skipped_extract_response(
                video,
                reason="not_embeddable",
                model=request.model or self._model,
                reasoning_effort=request.reasoning_effort or self._reasoning_effort,
            )
        prepared = await self._prepare_extraction(
            video_id,
            request,
            actor_type="manual_api",
        )
        task = await self._video_tasks.get_or_create_task(
            VideoTaskCreate(
                video_id=prepared.execution_input.video.id,
                task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
                task_version=MICRO_EVENT_EXTRACT_TASK_VERSION,
                input_hash=prepared.input_hash,
                timeout_seconds=self._timeout_seconds,
                input_json=prepared.input_json,
            )
        )
        await self._task_events.record(
            "micro_event_extract.task_selected",
            "info",
            "Micro-event extraction task was selected.",
            task=task,
            execution_input=prepared.execution_input,
            metadata_json={
                "taskStatus": task.status,
                "retryFailed": request.retry_failed,
                "regenerateSucceeded": request.regenerate_succeeded,
                "model": prepared.execution_input.model,
                "reasoningEffort": prepared.execution_input.reasoning_effort,
                "domainKnowledgeEntryCount": len(prepared.execution_input.domain_knowledge_entries),
                "domainKnowledgeFingerprint": (
                    prepared.execution_input.domain_knowledge_fingerprint
                ),
            },
        )
        return await self._process_task(
            task,
            prepared.execution_input,
            prepared.input_hash,
            retry_failed=request.retry_failed,
            regenerate_succeeded=request.regenerate_succeeded,
        )

    async def execute_all(
        self,
        request: MicroEventBatchExtractRequest,
    ) -> MicroEventBatchExtractResponse:
        candidates = await self._video_tasks.list_latest_succeeded_tasks(
            task_name=TRANSCRIPT_CUE_GENERATE_TASK_NAME,
            channel_id=None,
            limit=MICRO_EVENT_EXTRACT_BATCH_SCAN_LIMIT,
        )
        items: list[MicroEventExtractResponse] = []
        scanned_count = 0
        already_satisfied_count = 0
        ineligible_count = 0
        domain_fingerprint_cache: dict[int, str] = {}
        single_request = _single_extract_request(request)

        for candidate in candidates:
            if len(items) >= request.limit:
                break
            scanned_count += 1
            if candidate.video.is_embeddable is False and not request.include_non_embeddable:
                ineligible_count += 1
                continue
            action = await self._batch_candidate_action(
                candidate,
                request,
                domain_fingerprint_cache,
            )
            if action == "already_satisfied":
                already_satisfied_count += 1
                continue
            if action == "ineligible":
                ineligible_count += 1
                continue
            running_count = await self._video_tasks.count_running(
                task_name=MICRO_EVENT_EXTRACT_TASK_NAME
            )
            if running_count >= MICRO_EVENT_EXTRACT_VIDEO_TASK_CONCURRENCY_LIMIT:
                ineligible_count += 1
                break
            items.append(await self.execute(candidate.video.id, single_request))

        return MicroEventBatchExtractResponse(
            requestedCount=request.limit,
            processedCount=len(items),
            succeededCount=sum(item.status == "succeeded" for item in items),
            failedCount=sum(item.status == "failed" for item in items),
            skippedCount=sum(item.status == "skipped" for item in items),
            timedOutCount=sum(item.status == "timed_out" for item in items),
            scannedCount=scanned_count,
            alreadySatisfiedCount=already_satisfied_count,
            ineligibleCount=ineligible_count,
            items=items,
        )

    async def enqueue(
        self,
        request: MicroEventEnqueueRequest,
    ) -> MicroEventEnqueueResponse:
        counters = _EnqueueCounters()
        items: list[MicroEventEnqueueItemResponse] = []
        if request.target == "selected_videos":
            for video_id in request.video_ids[: request.limit]:
                counters.scanned_count += 1
                items.append(await self._enqueue_video_id(video_id, request, counters))
            return _enqueue_response(request, counters, items)

        candidates = await self._video_tasks.list_latest_succeeded_tasks(
            task_name=TRANSCRIPT_CUE_GENERATE_TASK_NAME,
            channel_id=request.channel_id,
            limit=MICRO_EVENT_EXTRACT_BATCH_SCAN_LIMIT,
        )
        for candidate in candidates:
            counters.scanned_count += 1
            if request.target == "current_filters" and not await self._matches_enqueue_filters(
                candidate.video,
                request,
            ):
                continue
            item = await self._enqueue_video(candidate.video, request, counters)
            items.append(item)
            if counters.enqueued_count >= request.limit:
                break
        return _enqueue_response(request, counters, items)

    async def get_latest(self, video_id: int) -> MicroEventExtractionDetailResponse:
        if await self._videos.get_video(video_id) is None:
            raise VideoNotFound("Video not found.")
        detail = await self._micro_events.get_latest_succeeded_extraction(video_id=video_id)
        if detail is None:
            raise MicroEventExtractionNotFound("Micro-event extraction not found.")
        return _detail_response(detail)

    async def get_detail(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> MicroEventExtractionDetailResponse:
        if await self._videos.get_video(video_id) is None:
            raise VideoNotFound("Video not found.")
        detail = await self._micro_events.get_extraction(
            video_id=video_id,
            video_task_id=video_task_id,
        )
        if detail is None:
            raise MicroEventExtractionNotFound("Micro-event extraction not found.")
        return _detail_response(detail)

    async def execute_retry_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        task_id = _required_int(job.input_json, "videoTaskId")
        task = await self._video_tasks.get_task(task_id)
        if task is None:
            raise VideoTaskRetryNotAllowed("Video task not found.")
        if task.status not in {"failed", "timed_out"}:
            raise VideoTaskRetryNotAllowed(
                "Only failed or timed out micro-event extraction tasks can be retried."
            )
        if (
            await self._video_tasks.count_running(task_name=MICRO_EVENT_EXTRACT_TASK_NAME)
            >= MICRO_EVENT_EXTRACT_VIDEO_TASK_CONCURRENCY_LIMIT
        ):
            raise VideoTaskRetryNotAllowed("Micro-event extraction is already running.")

        video, metadata, cues = await self._load_inputs(_required_int(job.input_json, "videoId"))
        domain_knowledge_entries, streamer_name = await self._load_prompt_context(video)
        domain_knowledge_fingerprint = _str_output(
            job.input_json,
            "domainKnowledgeFingerprint",
        ) or _domain_knowledge_fingerprint(domain_knowledge_entries)
        prompt = await self._resolve_prompt_from_input(job.input_json)
        timeout_seconds = _required_int(job.input_json, "timeoutSeconds")
        task = await self._video_tasks.mark_task_running(
            task.id,
            worker_id=MICRO_EVENT_EXTRACT_WORKER_ID,
            timeout_seconds=timeout_seconds,
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        execution_input = _ExtractionExecutionInput(
            video=video,
            metadata=metadata,
            cues=cues,
            window_minutes=_required_int(job.input_json, "windowMinutes"),
            overlap_minutes=_required_int(job.input_json, "overlapMinutes"),
            model=_model_output(job.input_json) or self._model,
            reasoning_effort=(_reasoning_effort_output(job.input_json) or self._reasoning_effort),
            actor_type="retry_executor",
            domain_knowledge_entries=domain_knowledge_entries,
            domain_knowledge_fingerprint=domain_knowledge_fingerprint,
            streamer_name=streamer_name,
            prompt=prompt,
        )
        await self._task_events.record(
            "micro_event_extract.task_running",
            "info",
            "Micro-event extraction task started running.",
            task=task,
            execution_input=execution_input,
            metadata_json={"attemptId": attempt.id},
        )
        response = await self._execute_job_attempt(
            job,
            attempt,
            task=task,
            execution_input=execution_input,
            timeout_seconds=timeout_seconds,
            resume_partial=True,
        )
        return response.model_dump(by_alias=True)

    async def execute_claimed_task(
        self,
        task: VideoTaskRecord,
        *,
        worker_id: str,
    ) -> MicroEventExtractResponse:
        if task.task_name != MICRO_EVENT_EXTRACT_TASK_NAME or task.status != "running":
            raise VideoTaskRetryNotAllowed("Only claimed micro-event tasks can be executed.")
        input_json = task.input_json or {}
        if not input_json:
            await self._video_tasks.mark_task_failed(
                task.id,
                error_type="InvalidTaskInput",
                error_message="Queued micro-event task is missing input_json.",
            )
            raise VideoTaskRetryNotAllowed("Queued micro-event task is missing input_json.")
        timeout_seconds = _int_output(input_json, "timeoutSeconds") or task.timeout_seconds
        job_input_json = {**input_json, "videoTaskId": task.id}
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step=MICRO_EVENT_EXTRACT_TASK_NAME,
                status="running",
                subject_type="video",
                subject_id=_required_int(job_input_json, "videoId"),
                external_key=_str_output(job_input_json, "youtubeVideoId"),
                input_json=job_input_json,
                input_hash=task.input_hash,
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
        try:
            execution_input = await self._execution_input_from_task_input(
                task,
                job_input_json,
                actor_type="system",
            )
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=error_type,
                error_message=error_message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            await self._video_tasks.mark_task_failed(
                task.id,
                error_type=error_type,
                error_message=error_message,
                output_json={"jobId": job.id, "jobAttemptId": attempt.id},
            )
            raise
        await self._task_events.record(
            "micro_event_extract.task_running",
            "info",
            "Micro-event extraction task started running.",
            task=task,
            execution_input=execution_input,
            metadata_json={"attemptId": attempt.id, "workerId": worker_id},
        )
        existing_detail = await self._micro_events.get_extraction(
            video_id=execution_input.video.id,
            video_task_id=task.id,
        )
        return await self._execute_job_attempt(
            job,
            attempt,
            task=task,
            execution_input=execution_input,
            timeout_seconds=timeout_seconds,
            resume_partial=bool(existing_detail and existing_detail.windows),
        )

    async def _enqueue_video_id(
        self,
        video_id: int,
        request: MicroEventEnqueueRequest,
        counters: _EnqueueCounters,
    ) -> MicroEventEnqueueItemResponse:
        video = await self._videos.get_video(video_id)
        if video is None:
            counters.ineligible_count += 1
            return _enqueue_item(
                video_id=video_id,
                youtube_video_id=None,
                task=None,
                status="skipped",
                reason="video_not_found",
                request=request,
                transcript_id=None,
                error_type="VideoNotFound",
                error_message="Video not found.",
            )
        return await self._enqueue_video(video, request, counters)

    async def _enqueue_video(
        self,
        video: VideoRecord,
        request: MicroEventEnqueueRequest,
        counters: _EnqueueCounters,
    ) -> MicroEventEnqueueItemResponse:
        if video.is_embeddable is False and not request.include_non_embeddable:
            counters.ineligible_count += 1
            return _enqueue_item(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                task=None,
                status="skipped",
                reason="not_embeddable",
                request=request,
                transcript_id=None,
                error_type=None,
                error_message=None,
            )
        try:
            prepared = await self._prepare_extraction(
                video.id,
                request,
                actor_type="manual_api",
            )
        except (
            MicroEventExtractionPreconditionFailed,
            YouTubeTranscriptMetadataNotFound,
        ) as exc:
            counters.ineligible_count += 1
            return _enqueue_item(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                task=None,
                status="skipped",
                reason="ineligible",
                request=request,
                transcript_id=None,
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
            )
        existing = await self._video_tasks.get_task_for_input(
            video_id=video.id,
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
            task_version=MICRO_EVENT_EXTRACT_TASK_VERSION,
            input_hash=prepared.input_hash,
        )
        if existing is None:
            task = await self._video_tasks.get_or_create_task(
                VideoTaskCreate(
                    video_id=video.id,
                    task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
                    task_version=MICRO_EVENT_EXTRACT_TASK_VERSION,
                    input_hash=prepared.input_hash,
                    timeout_seconds=self._timeout_seconds,
                    input_json=prepared.input_json,
                    status="pending",
                )
            )
            counters.enqueued_count += 1
            await self._task_events.record(
                "micro_event_extract.task_enqueued",
                "info",
                "Micro-event extraction task was queued.",
                task=task,
                execution_input=prepared.execution_input,
                reason="enqueued",
                metadata_json=prepared.input_json,
            )
            return _enqueue_item_from_task(
                task,
                request=request,
                video=video,
                status="pending",
                reason="enqueued",
                transcript_id=prepared.execution_input.metadata.id,
            )
        return await self._enqueue_existing_task(
            existing,
            prepared,
            request,
            counters,
        )

    async def _enqueue_existing_task(
        self,
        task: VideoTaskRecord,
        prepared: _PreparedExtraction,
        request: MicroEventEnqueueRequest,
        counters: _EnqueueCounters,
    ) -> MicroEventEnqueueItemResponse:
        if task.status == "pending":
            if task.input_json is None:
                reset = await self._video_tasks.reset_task_to_pending(
                    task.id,
                    timeout_seconds=self._timeout_seconds,
                    input_json=prepared.input_json,
                )
                counters.enqueued_count += 1
                return _enqueue_item_from_task(
                    reset,
                    request=request,
                    video=prepared.execution_input.video,
                    status="pending",
                    reason="enqueued",
                    transcript_id=prepared.execution_input.metadata.id,
                )
            counters.already_pending_count += 1
            return _enqueue_item_from_task(
                task,
                request=request,
                video=prepared.execution_input.video,
                status="pending",
                reason="already_pending",
                transcript_id=prepared.execution_input.metadata.id,
            )
        if task.status == "running":
            counters.already_running_count += 1
            return _enqueue_item_from_task(
                task,
                request=request,
                video=prepared.execution_input.video,
                status="skipped",
                reason="already_running",
                transcript_id=prepared.execution_input.metadata.id,
            )
        if task.status == "succeeded" and not request.regenerate_succeeded:
            counters.already_succeeded_count += 1
            return _enqueue_item_from_task(
                task,
                request=request,
                video=prepared.execution_input.video,
                status="skipped",
                reason="already_succeeded",
                transcript_id=prepared.execution_input.metadata.id,
            )
        if task.status in {"failed", "timed_out"} and not request.retry_failed:
            counters.skipped_failed_count += 1
            return _enqueue_item_from_task(
                task,
                request=request,
                video=prepared.execution_input.video,
                status="skipped",
                reason=f"previously_{task.status}",
                transcript_id=prepared.execution_input.metadata.id,
            )
        if task.status == "canceled" and not request.retry_failed:
            counters.ineligible_count += 1
            return _enqueue_item_from_task(
                task,
                request=request,
                video=prepared.execution_input.video,
                status="skipped",
                reason="not_retryable",
                transcript_id=prepared.execution_input.metadata.id,
            )
        if task.status in {"skipped", "no_transcript"}:
            counters.ineligible_count += 1
            return _enqueue_item_from_task(
                task,
                request=request,
                video=prepared.execution_input.video,
                status="skipped",
                reason="not_retryable",
                transcript_id=prepared.execution_input.metadata.id,
            )
        reset = await self._video_tasks.reset_task_to_pending(
            task.id,
            timeout_seconds=self._timeout_seconds,
            input_json=prepared.input_json,
        )
        counters.enqueued_count += 1
        await self._task_events.record(
            "micro_event_extract.task_enqueued",
            "info",
            "Micro-event extraction task was queued.",
            task=reset,
            execution_input=prepared.execution_input,
            reason="requeued",
            metadata_json=prepared.input_json,
        )
        return _enqueue_item_from_task(
            reset,
            request=request,
            video=prepared.execution_input.video,
            status="pending",
            reason="requeued",
            transcript_id=prepared.execution_input.metadata.id,
        )

    async def _matches_enqueue_filters(
        self,
        video: VideoRecord,
        request: MicroEventEnqueueRequest,
    ) -> bool:
        if request.search is not None:
            search = request.search.casefold()
            if (
                search not in video.title.casefold()
                and search not in video.youtube_video_id.casefold()
            ):
                return False
        if request.task_status is not None:
            latest_task = await self._video_tasks.get_latest_task_for_video(video.id)
            if latest_task is None or latest_task.status != request.task_status:
                return False
        return True

    async def _prepare_extraction(
        self,
        video_id: int,
        request: MicroEventExtractRequest,
        *,
        actor_type: OperationEventActorType,
    ) -> _PreparedExtraction:
        video, metadata, cues = await self._load_inputs(video_id)
        domain_knowledge_entries, streamer_name = await self._load_prompt_context(video)
        domain_knowledge_fingerprint = _domain_knowledge_fingerprint(domain_knowledge_entries)
        model = request.model or self._model
        reasoning_effort = request.reasoning_effort or self._reasoning_effort
        prompt = await self._prompt_resolver.resolve_prompt_for_request(
            MICRO_EVENT_EXTRACT_PROMPT_KEY,
            request.prompt_version_id,
        )
        input_hash = _task_input_hash(
            video=video,
            metadata=metadata,
            window_minutes=request.window_minutes,
            overlap_minutes=request.overlap_minutes,
            model=model,
            reasoning_effort=reasoning_effort,
            domain_knowledge_fingerprint=domain_knowledge_fingerprint,
            prompt=prompt,
        )
        execution_input = _ExtractionExecutionInput(
            video=video,
            metadata=metadata,
            cues=cues,
            window_minutes=request.window_minutes,
            overlap_minutes=request.overlap_minutes,
            model=model,
            reasoning_effort=reasoning_effort,
            actor_type=actor_type,
            domain_knowledge_entries=domain_knowledge_entries,
            domain_knowledge_fingerprint=domain_knowledge_fingerprint,
            streamer_name=streamer_name,
            prompt=prompt,
        )
        return _PreparedExtraction(
            execution_input=execution_input,
            input_hash=input_hash,
            input_json=_task_input_json(
                execution_input,
                input_hash=input_hash,
                timeout_seconds=self._timeout_seconds,
            ),
        )

    async def _execution_input_from_task_input(
        self,
        task: VideoTaskRecord,
        input_json: JsonObject,
        *,
        actor_type: OperationEventActorType,
    ) -> _ExtractionExecutionInput:
        video_id = _required_int(input_json, "videoId")
        transcript_id = _required_int(input_json, "transcriptId")
        video = await self._videos.get_video(video_id)
        if video is None:
            raise VideoNotFound("Video not found.")
        metadata = await self._transcripts.get_transcript_metadata(transcript_id)
        if metadata is None:
            raise YouTubeTranscriptMetadataNotFound("Transcript metadata not found.")
        cues = await self._transcript_cues.list_cues(metadata.id)
        if not cues:
            raise MicroEventExtractionPreconditionFailed("Transcript cues are required.")
        domain_knowledge_entries, streamer_name = await self._load_prompt_context(video)
        domain_knowledge_fingerprint = _str_output(
            input_json, "domainKnowledgeFingerprint"
        ) or _domain_knowledge_fingerprint(domain_knowledge_entries)
        prompt = await self._resolve_prompt_from_input(input_json)
        return _ExtractionExecutionInput(
            video=video,
            metadata=metadata,
            cues=cues,
            window_minutes=_required_int(input_json, "windowMinutes"),
            overlap_minutes=_required_int(input_json, "overlapMinutes"),
            model=_model_output(input_json) or self._model,
            reasoning_effort=_reasoning_effort_output(input_json) or self._reasoning_effort,
            actor_type=actor_type,
            domain_knowledge_entries=domain_knowledge_entries,
            domain_knowledge_fingerprint=domain_knowledge_fingerprint,
            streamer_name=streamer_name,
            prompt=prompt,
        )

    async def _batch_candidate_action(
        self,
        candidate: VideoTaskWithVideoRecord,
        request: MicroEventBatchExtractRequest,
        domain_fingerprint_cache: dict[int, str],
    ) -> str:
        transcript_id = candidate.task.output_transcript_id
        if transcript_id is None:
            return "ineligible"
        metadata = await self._transcripts.get_transcript_metadata(transcript_id)
        if metadata is None:
            return "ineligible"
        model = request.model or self._model
        reasoning_effort = request.reasoning_effort or self._reasoning_effort
        prompt = await self._prompt_resolver.resolve_prompt_for_request(
            MICRO_EVENT_EXTRACT_PROMPT_KEY,
            request.prompt_version_id,
        )
        input_hash = _task_input_hash(
            video=candidate.video,
            metadata=metadata,
            window_minutes=request.window_minutes,
            overlap_minutes=request.overlap_minutes,
            model=model,
            reasoning_effort=reasoning_effort,
            domain_knowledge_fingerprint=(
                await self._batch_domain_knowledge_fingerprint(
                    candidate.video,
                    domain_fingerprint_cache,
                )
            ),
            prompt=prompt,
        )
        task = await self._video_tasks.get_task_for_input(
            video_id=candidate.video.id,
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
            task_version=MICRO_EVENT_EXTRACT_TASK_VERSION,
            input_hash=input_hash,
        )
        if task is None or task.status == "pending":
            return "execute"
        if task.status == "succeeded":
            return "execute" if request.regenerate_succeeded else "already_satisfied"
        if task.status in {"failed", "timed_out"}:
            return "execute" if request.retry_failed else "ineligible"
        return "ineligible"

    async def _batch_domain_knowledge_fingerprint(
        self,
        video: VideoRecord,
        cache: dict[int, str],
    ) -> str:
        cached = cache.get(video.channel_id)
        if cached is not None:
            return cached
        entries = await self._load_domain_knowledge_entries(video)
        fingerprint = _domain_knowledge_fingerprint(entries)
        cache[video.channel_id] = fingerprint
        return fingerprint

    async def _load_inputs(
        self,
        video_id: int,
    ) -> tuple[VideoRecord, YouTubeTranscriptMetadataRecord, list[TranscriptCueRecord]]:
        video = await self._videos.get_video(video_id)
        if video is None:
            raise VideoNotFound("Video not found.")
        cue_task = await self._video_tasks.get_latest_succeeded_task_for_video(
            video_id=video.id,
            task_name=TRANSCRIPT_CUE_GENERATE_TASK_NAME,
        )
        if cue_task is None or cue_task.output_transcript_id is None:
            loaded = await self._load_latest_transcript_with_cues(video)
            if loaded is not None:
                return video, loaded[0], loaded[1]
            raise MicroEventExtractionPreconditionFailed("Transcript cues are required.")
        metadata = await self._transcripts.get_transcript_metadata(cue_task.output_transcript_id)
        if metadata is None:
            raise YouTubeTranscriptMetadataNotFound("Transcript metadata not found.")
        cues = await self._transcript_cues.list_cues(metadata.id)
        if not cues:
            raise MicroEventExtractionPreconditionFailed("Transcript cues are required.")
        return video, metadata, cues

    async def _load_latest_transcript_with_cues(
        self,
        video: VideoRecord,
    ) -> tuple[YouTubeTranscriptMetadataRecord, list[TranscriptCueRecord]] | None:
        metadata_records = await self._transcripts.list_transcript_metadata(
            YouTubeTranscriptMetadataFilters(
                video_id=video.youtube_video_id,
                limit=10,
                offset=0,
            )
        )
        for metadata in metadata_records:
            cues = await self._transcript_cues.list_cues(metadata.id)
            if cues:
                return metadata, cues
        return None

    async def _load_domain_knowledge_entries(
        self,
        video: VideoRecord,
    ) -> list[DomainKnowledgePromptEntryRecord]:
        channel = await self._channels.get_channel(video.channel_id)
        streamer_id = channel.streamer_id if channel is not None else None
        return await self._domain_knowledge.list_prompt_entries_for_streamer(streamer_id)

    async def _load_prompt_context(
        self,
        video: VideoRecord,
    ) -> tuple[list[DomainKnowledgePromptEntryRecord], str | None]:
        channel = await self._channels.get_channel(video.channel_id)
        streamer_id = channel.streamer_id if channel is not None else None
        streamer_name = None
        if streamer_id is not None:
            streamer = await self._streamers.get_streamer(streamer_id)
            streamer_name = streamer.name if streamer is not None else None
        entries = await self._domain_knowledge.list_prompt_entries_for_streamer(streamer_id)
        return entries, streamer_name

    async def _resolve_prompt_from_input(self, input_json: JsonObject) -> ResolvedPrompt:
        if "promptVersionId" in input_json:
            return await self._prompt_resolver.resolve_prompt_version(
                MICRO_EVENT_EXTRACT_PROMPT_KEY,
                _int_output(input_json, "promptVersionId"),
            )
        return await self._prompt_resolver.resolve_prompt(MICRO_EVENT_EXTRACT_PROMPT_KEY)

    async def _process_task(
        self,
        task: VideoTaskRecord,
        execution_input: _ExtractionExecutionInput,
        input_hash: str,
        *,
        retry_failed: bool,
        regenerate_succeeded: bool,
    ) -> MicroEventExtractResponse:
        if task.status == "succeeded" and not regenerate_succeeded:
            detail = await self._micro_events.get_extraction(
                video_id=execution_input.video.id,
                video_task_id=task.id,
            )
            return _extract_response(
                execution_input.video,
                task,
                detail=detail,
                status="succeeded",
                reason="already_succeeded",
                model=execution_input.model,
                reasoning_effort=execution_input.reasoning_effort,
            )
        if task.status == "running":
            return _extract_response(
                execution_input.video,
                task,
                detail=None,
                status="skipped",
                reason="already_running",
                model=execution_input.model,
                reasoning_effort=execution_input.reasoning_effort,
            )
        if task.status in {"failed", "timed_out"} and not retry_failed:
            return _extract_response(
                execution_input.video,
                task,
                detail=None,
                status="skipped",
                reason=f"previously_{task.status}",
                model=execution_input.model,
                reasoning_effort=execution_input.reasoning_effort,
            )
        if task.status in {"skipped", "canceled", "no_transcript"}:
            return _extract_response(
                execution_input.video,
                task,
                detail=None,
                status="skipped",
                reason="not_retryable",
                model=execution_input.model,
                reasoning_effort=execution_input.reasoning_effort,
            )
        running_count = await self._video_tasks.count_running(
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME
        )
        if running_count >= MICRO_EVENT_EXTRACT_VIDEO_TASK_CONCURRENCY_LIMIT:
            return _extract_response(
                execution_input.video,
                task,
                detail=None,
                status="skipped",
                reason="concurrency_limit",
                model=execution_input.model,
                reasoning_effort=execution_input.reasoning_effort,
            )
        return await self._execute_task(
            task,
            execution_input,
            input_hash,
            resume_partial=task.status in {"failed", "timed_out"} and retry_failed,
        )

    async def _execute_task(
        self,
        task: VideoTaskRecord,
        execution_input: _ExtractionExecutionInput,
        input_hash: str,
        *,
        resume_partial: bool = False,
    ) -> MicroEventExtractResponse:
        input_json: JsonObject = {
            "videoTaskId": task.id,
            "videoId": execution_input.video.id,
            "youtubeVideoId": execution_input.video.youtube_video_id,
            "transcriptId": execution_input.metadata.id,
            "responseSha256": execution_input.metadata.response_sha256,
            "taskVersion": MICRO_EVENT_EXTRACT_TASK_VERSION,
            **_prompt_metadata_json(execution_input.prompt),
            "inputHash": input_hash,
            "windowMinutes": execution_input.window_minutes,
            "overlapMinutes": execution_input.overlap_minutes,
            "model": execution_input.model,
            "reasoningEffort": execution_input.reasoning_effort,
            "domainKnowledgeEntryCount": len(execution_input.domain_knowledge_entries),
            "domainKnowledgeFingerprint": execution_input.domain_knowledge_fingerprint,
            "timeoutSeconds": self._timeout_seconds,
        }
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step=MICRO_EVENT_EXTRACT_TASK_NAME,
                status="running",
                subject_type="video",
                subject_id=execution_input.video.id,
                external_key=execution_input.video.youtube_video_id,
                input_json=input_json,
                input_hash=input_hash,
            )
        )
        attempt = await self._pipeline_jobs.create_attempt(
            job_id=job.id,
            worker_id=MICRO_EVENT_EXTRACT_WORKER_ID,
        )
        task = await self._video_tasks.mark_task_running(
            task.id,
            worker_id=MICRO_EVENT_EXTRACT_WORKER_ID,
            timeout_seconds=self._timeout_seconds,
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        await self._task_events.record(
            "micro_event_extract.task_running",
            "info",
            "Micro-event extraction task started running.",
            task=task,
            execution_input=execution_input,
            metadata_json={"attemptId": attempt.id},
        )
        return await self._execute_job_attempt(
            job,
            attempt,
            task=task,
            execution_input=execution_input,
            timeout_seconds=self._timeout_seconds,
            resume_partial=resume_partial,
        )

    async def _execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        *,
        task: VideoTaskRecord,
        execution_input: _ExtractionExecutionInput,
        timeout_seconds: int,
        resume_partial: bool,
    ) -> MicroEventExtractResponse:
        run_stats = _MicroEventWindowRunStats()
        try:
            windows = await asyncio.wait_for(
                self._extract_windows(
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    resume_partial=resume_partial,
                    run_stats=run_stats,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            message = f"Micro-event extraction exceeded {timeout_seconds} seconds."
            await self._llm_traces.record_event(
                _micro_trace_event(
                    operation="extract_video",
                    phase="task_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    error_type="TimeoutError",
                    error_message=message,
                )
            )
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type="TimeoutError",
                error_message=message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            updated = await self._video_tasks.mark_task_timed_out(
                task.id,
                error_message=message,
                output_json=_attempt_output_json(
                    execution_input,
                    job=job,
                    attempt=attempt,
                    run_stats=run_stats,
                ),
            )
            await self._task_events.record(
                "micro_event_extract.task_timed_out",
                "error",
                "Micro-event extraction task timed out.",
                task=updated,
                execution_input=execution_input,
                reason="timeout",
                error_type="TimeoutError",
                error_message=message,
            )
            return _extract_response(
                execution_input.video,
                updated,
                detail=None,
                status="timed_out",
                reason="timeout",
                model=execution_input.model,
                reasoning_effort=execution_input.reasoning_effort,
            )
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            await self._llm_traces.record_event(
                _micro_trace_event(
                    operation="extract_video",
                    phase="task_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    error_type=error_type,
                    error_message=error_message,
                )
            )
            updated = await self._video_tasks.mark_task_failed(
                task.id,
                error_type=error_type,
                error_message=error_message,
                output_json=_attempt_output_json(
                    execution_input,
                    job=job,
                    attempt=attempt,
                    run_stats=run_stats,
                ),
            )
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=error_type,
                error_message=error_message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            await self._task_events.record(
                "micro_event_extract.task_failed",
                "error",
                "Micro-event extraction task failed.",
                task=updated,
                execution_input=execution_input,
                reason="error",
                error_type=error_type,
                error_message=error_message,
            )
            detail = await self._micro_events.get_extraction(
                video_id=execution_input.video.id,
                video_task_id=task.id,
            )
            return _extract_response(
                execution_input.video,
                updated,
                detail=detail,
                status="failed",
                reason="error",
                model=execution_input.model,
                reasoning_effort=execution_input.reasoning_effort,
            )

        detail = await self._micro_events.replace_extraction(task.id, windows)
        output_json = _output_json(
            execution_input,
            detail,
            job=job,
            attempt=attempt,
            run_stats=run_stats,
        )
        await self._pipeline_jobs.mark_attempt_succeeded(
            attempt.id,
            output_json=output_json,
        )
        await self._pipeline_jobs.mark_job_succeeded(job.id)
        updated = await self._video_tasks.mark_task_succeeded(
            task.id,
            output_transcript_id=execution_input.metadata.id,
            output_json=output_json,
        )
        await self._task_events.record(
            "micro_event_extract.task_succeeded",
            "info",
            "Micro-event extraction task succeeded.",
            task=updated,
            execution_input=execution_input,
            reason="extracted",
            metadata_json=output_json,
        )
        return _extract_response(
            execution_input.video,
            updated,
            detail=detail,
            status="succeeded",
            reason="extracted",
            model=execution_input.model,
            reasoning_effort=execution_input.reasoning_effort,
        )

    async def _extract_windows(
        self,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        execution_input: _ExtractionExecutionInput,
        resume_partial: bool,
        run_stats: _MicroEventWindowRunStats,
    ) -> list[MicroEventExtractionWindowCreate]:
        cue_windows = _cue_windows(
            execution_input.cues,
            window_minutes=execution_input.window_minutes,
            overlap_minutes=execution_input.overlap_minutes,
        )
        if not cue_windows:
            return []
        window_count = len(cue_windows)
        results: dict[int, MicroEventExtractionWindowCreate] = {}
        final_failures = _MicroEventWindowFinalFailures(
            validation_failures={},
            runtime_failures={},
        )
        pending_windows = list(cue_windows)
        if resume_partial:
            existing_detail = await self._micro_events.get_extraction(
                video_id=execution_input.video.id,
                video_task_id=task.id,
            )
            resume_plan = _partial_resume_plan(
                existing_detail,
                cue_windows,
                execution_input=execution_input,
                job=job,
                attempt=attempt,
            )
            results.update(resume_plan.resumed_windows)
            run_stats.resumed_window_indices.update(resume_plan.resumed_windows)
            pending_windows = resume_plan.pending_windows
            if resume_plan.skip_reason is None:
                await self._task_events.record(
                    "micro_event_extract.partial_resume_used",
                    "info",
                    "Micro-event extraction reused partial window results.",
                    task=task,
                    execution_input=execution_input,
                    reason="partial_resume_used",
                    metadata_json=_partial_resume_metadata(
                        resumed_window_indices=resume_plan.resumed_windows,
                        scheduled_windows=pending_windows,
                        window_count=window_count,
                    ),
                )
            else:
                await self._micro_events.delete_extraction(task.id)
                await self._task_events.record(
                    "micro_event_extract.partial_resume_skipped",
                    "info",
                    "Micro-event extraction partial resume was skipped.",
                    task=task,
                    execution_input=execution_input,
                    reason="partial_resume_skipped",
                    metadata_json=_partial_resume_metadata(
                        resumed_window_indices={},
                        scheduled_windows=pending_windows,
                        window_count=window_count,
                        skip_reason=resume_plan.skip_reason,
                    ),
                )
        else:
            await self._micro_events.delete_extraction(task.id)
        retry_attempt = 0
        persist_lock = asyncio.Lock()

        while pending_windows:
            batch = await self._extract_window_batch(
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_windows=pending_windows,
                window_count=window_count,
                retry_attempt=retry_attempt,
                persist_lock=persist_lock,
                run_stats=run_stats,
            )
            results.update(batch.windows)
            final_failures.validation_failures.update(batch.validation_failures)

            retry_windows: list[_CueWindow] = []
            for failure in batch.runtime_failures.values():
                if retry_attempt < _MICRO_EVENT_WINDOW_MAX_RETRY_ATTEMPTS:
                    next_retry_attempt = retry_attempt + 1
                    retry_windows.append(failure.cue_window)
                    await self._record_window_retry_event(
                        "micro_event_extract.window_retry_requested",
                        "warning",
                        "Micro-event extraction window retry requested.",
                        task=task,
                        job=job,
                        attempt=attempt,
                        execution_input=execution_input,
                        failure=failure,
                        window_count=window_count,
                        retry_attempt=next_retry_attempt,
                        phase="window_retry_scheduled",
                        reason="window_retry_scheduled",
                    )
                else:
                    final_failures.runtime_failures[failure.cue_window.window_index] = failure
                    await self._record_window_retry_event(
                        "micro_event_extract.window_retry_failed",
                        "error",
                        "Micro-event extraction window retries were exhausted.",
                        task=task,
                        job=job,
                        attempt=attempt,
                        execution_input=execution_input,
                        failure=failure,
                        window_count=window_count,
                        retry_attempt=retry_attempt,
                        phase="window_retries_exhausted",
                        reason="window_retries_exhausted",
                    )

            pending_windows = retry_windows
            if pending_windows:
                retry_attempt += 1

        if final_failures.validation_failures or final_failures.runtime_failures:
            failed_windows = [
                failure.failed_window for failure in final_failures.validation_failures.values()
            ] + [failure.failed_window for failure in final_failures.runtime_failures.values()]
            run_stats.failed_window_indices.update(window.window_index for window in failed_windows)
            await self._micro_events.replace_extraction(
                task.id,
                _sorted_windows([*results.values(), *failed_windows]),
            )
            raise _first_window_failure(final_failures)
        return _sorted_windows(results.values())

    async def _extract_window_batch(
        self,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        execution_input: _ExtractionExecutionInput,
        cue_windows: list[_CueWindow],
        window_count: int,
        retry_attempt: int,
        persist_lock: asyncio.Lock,
        run_stats: _MicroEventWindowRunStats,
    ) -> _MicroEventWindowBatchResult:
        queue: asyncio.Queue[_CueWindow] = asyncio.Queue()
        for cue_window in cue_windows:
            queue.put_nowait(cue_window)
        results: dict[int, MicroEventExtractionWindowCreate] = {}
        validation_failures: dict[int, _MicroEventWindowValidationFailure] = {}
        runtime_failures: dict[int, _MicroEventWindowRuntimeFailure] = {}
        worker_count = min(self._concurrency_limit, len(cue_windows))

        async def worker() -> None:
            while True:
                try:
                    cue_window = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    run_stats.executed_window_indices.add(cue_window.window_index)
                    window = await self._extract_window(
                        task=task,
                        job=job,
                        attempt=attempt,
                        execution_input=execution_input,
                        cue_window=cue_window,
                        window_count=window_count,
                        retry_attempt=retry_attempt,
                    )
                    async with persist_lock:
                        await self._micro_events.upsert_window(task.id, window)
                    results[cue_window.window_index] = window
                    run_stats.failed_window_indices.discard(cue_window.window_index)
                    if retry_attempt > 0:
                        await self._record_window_retry_success(
                            task=task,
                            execution_input=execution_input,
                            cue_window=cue_window,
                            window_count=window_count,
                            retry_attempt=retry_attempt,
                        )
                except _MicroEventWindowValidationFailure as exc:
                    run_stats.failed_window_indices.add(cue_window.window_index)
                    async with persist_lock:
                        await self._micro_events.upsert_window(
                            task.id,
                            exc.failed_window,
                        )
                    validation_failures[cue_window.window_index] = exc
                except Exception as exc:
                    failed_window = _runtime_failed_window(
                        task=task,
                        job=job,
                        attempt=attempt,
                        execution_input=execution_input,
                        cue_window=cue_window,
                        error_type=exc.__class__.__name__,
                        error_message=str(exc) or exc.__class__.__name__,
                    )
                    async with persist_lock:
                        await self._micro_events.upsert_window(task.id, failed_window)
                    run_stats.failed_window_indices.add(cue_window.window_index)
                    runtime_failures[cue_window.window_index] = _MicroEventWindowRuntimeFailure(
                        cue_window=cue_window,
                        error=exc,
                        failed_window=failed_window,
                    )
                finally:
                    queue.task_done()

        worker_tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
        try:
            await asyncio.gather(*worker_tasks)
        except BaseException:
            for worker_task in worker_tasks:
                if not worker_task.done():
                    worker_task.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            raise
        return _MicroEventWindowBatchResult(
            windows=results,
            validation_failures=validation_failures,
            runtime_failures=runtime_failures,
        )

    async def _extract_window(
        self,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        execution_input: _ExtractionExecutionInput,
        cue_window: _CueWindow,
        window_count: int,
        retry_attempt: int = 0,
    ) -> MicroEventExtractionWindowCreate:
        prompt = _window_prompt(execution_input, cue_window)
        retry_metadata = (
            _window_retry_metadata(
                cue_window,
                window_count=window_count,
                retry_attempt=retry_attempt,
                max_retry_attempts=_MICRO_EVENT_WINDOW_MAX_RETRY_ATTEMPTS,
            )
            if retry_attempt > 0
            else None
        )
        await self._llm_traces.record_event(
            _micro_trace_event(
                operation="extract_window",
                phase="window_retry_started" if retry_attempt > 0 else "window_started",
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                window_count=window_count,
                prompt_text=prompt,
                metadata=retry_metadata,
            )
        )
        started_at = time.monotonic()
        try:
            result = await self._extractor.extract_window(
                MicroEventExtractionRequest(
                    prompt=prompt,
                    video_id=execution_input.video.id,
                    video_task_id=task.id,
                    job_id=job.id,
                    job_attempt_id=attempt.id,
                    transcript_id=execution_input.metadata.id,
                    window_index=cue_window.window_index,
                    model=execution_input.model,
                    reasoning_effort=execution_input.reasoning_effort,
                )
            )
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            await self._llm_traces.record_event(
                _micro_trace_event(
                    operation="extract_window",
                    phase="window_retry_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    cue_window=cue_window,
                    window_count=window_count,
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type=error_type,
                    error_message=error_message,
                    metadata=_window_retry_metadata(
                        cue_window,
                        window_count=window_count,
                        retry_attempt=retry_attempt,
                        max_retry_attempts=_MICRO_EVENT_WINDOW_MAX_RETRY_ATTEMPTS,
                        error_type=error_type,
                        error_message=error_message,
                    ),
                )
            )
            raise
        await self._llm_traces.record_event(
            _micro_trace_event(
                operation="extract_window",
                phase="llm_response_received",
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                window_count=window_count,
                result=result,
                elapsed_ms=_elapsed_ms(started_at),
                raw_response_text=result.final_response,
            )
        )
        try:
            window = _validated_window(
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                result=result,
            )
            await self._llm_traces.record_event(
                _micro_trace_event(
                    operation="extract_window",
                    phase=("window_retry_succeeded" if retry_attempt > 0 else "window_succeeded"),
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    cue_window=cue_window,
                    window_count=window_count,
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    metadata={
                        "microEventCount": len(window.micro_events),
                        **(retry_metadata or {}),
                    },
                )
            )
            return window
        except MicroEventExtractionOutputInvalid as exc:
            await self._llm_traces.record_event(
                _micro_trace_event(
                    operation="extract_window",
                    phase=_micro_event_validation_failure_phase(exc),
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    cue_window=cue_window,
                    window_count=window_count,
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    raw_response_text=result.final_response,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc) or exc.__class__.__name__,
                )
            )
            repaired = await self._window_repair.repair(
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                window_count=window_count,
                original_prompt=prompt,
                original_result=result,
                original_error=exc,
            )
            if repaired is not None:
                await self._llm_traces.record_event(
                    _micro_trace_event(
                        operation="extract_window",
                        phase=(
                            "window_retry_succeeded" if retry_attempt > 0 else "window_succeeded"
                        ),
                        task=task,
                        job=job,
                        attempt=attempt,
                        execution_input=execution_input,
                        cue_window=cue_window,
                        window_count=window_count,
                        elapsed_ms=_elapsed_ms(started_at),
                        metadata={
                            "microEventCount": len(repaired.micro_events),
                            "repaired": True,
                            **(retry_metadata or {}),
                        },
                    )
                )
                return repaired
            raise _MicroEventWindowValidationFailure(
                exc,
                _failed_window(
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    cue_window=cue_window,
                    result=result,
                    validation_error=str(exc),
                ),
            ) from exc

    async def _record_window_retry_event(
        self,
        event_type: str,
        severity: OperationEventSeverity,
        message: str,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        execution_input: _ExtractionExecutionInput,
        failure: _MicroEventWindowRuntimeFailure,
        window_count: int,
        retry_attempt: int,
        phase: str,
        reason: str,
    ) -> None:
        error_type = failure.error.__class__.__name__
        error_message = str(failure.error) or error_type
        metadata = _window_retry_metadata(
            failure.cue_window,
            window_count=window_count,
            retry_attempt=retry_attempt,
            max_retry_attempts=_MICRO_EVENT_WINDOW_MAX_RETRY_ATTEMPTS,
            error_type=error_type,
            error_message=error_message,
        )
        await self._llm_traces.record_event(
            _micro_trace_event(
                operation="extract_window",
                phase=phase,
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=failure.cue_window,
                window_count=window_count,
                error_type=error_type,
                error_message=error_message,
                metadata=metadata,
            )
        )
        await self._task_events.record(
            event_type,
            severity,
            message,
            task=task,
            execution_input=execution_input,
            reason=reason,
            error_type=error_type,
            error_message=error_message,
            metadata_json=metadata,
        )

    async def _record_window_retry_success(
        self,
        *,
        task: VideoTaskRecord,
        execution_input: _ExtractionExecutionInput,
        cue_window: _CueWindow,
        window_count: int,
        retry_attempt: int,
    ) -> None:
        await self._task_events.record(
            "micro_event_extract.window_retry_succeeded",
            "info",
            "Micro-event extraction window retry succeeded.",
            task=task,
            execution_input=execution_input,
            reason="window_retry_succeeded",
            metadata_json=_window_retry_metadata(
                cue_window,
                window_count=window_count,
                retry_attempt=retry_attempt,
                max_retry_attempts=_MICRO_EVENT_WINDOW_MAX_RETRY_ATTEMPTS,
            ),
        )


def _first_window_failure(failures: _MicroEventWindowFinalFailures) -> Exception:
    indexed_errors: list[tuple[int, Exception]] = [
        (window_index, failure.error)
        for window_index, failure in failures.validation_failures.items()
    ] + [
        (window_index, failure.error) for window_index, failure in failures.runtime_failures.items()
    ]
    return min(indexed_errors, key=lambda item: item[0])[1]


def _window_run_stats_json(
    run_stats: _MicroEventWindowRunStats | None,
) -> JsonObject:
    if run_stats is None:
        return {}
    return {
        "resumedWindowCount": len(run_stats.resumed_window_indices),
        "executedWindowCount": len(run_stats.executed_window_indices),
        "failedWindowCount": len(run_stats.failed_window_indices),
    }


def _attempt_output_json(
    execution_input: _ExtractionExecutionInput,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    run_stats: _MicroEventWindowRunStats | None = None,
) -> JsonObject:
    return {
        "videoId": execution_input.video.id,
        "youtubeVideoId": execution_input.video.youtube_video_id,
        "transcriptId": execution_input.metadata.id,
        "model": execution_input.model,
        "reasoningEffort": execution_input.reasoning_effort,
        "domainKnowledgeEntryCount": len(execution_input.domain_knowledge_entries),
        "domainKnowledgeFingerprint": execution_input.domain_knowledge_fingerprint,
        "jobId": job.id,
        "jobAttemptId": attempt.id,
        **_window_run_stats_json(run_stats),
    }


def _output_json(
    execution_input: _ExtractionExecutionInput,
    detail: MicroEventExtractionDetailRecord | None,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    run_stats: _MicroEventWindowRunStats | None = None,
) -> JsonObject:
    return {
        "videoId": execution_input.video.id,
        "youtubeVideoId": execution_input.video.youtube_video_id,
        "transcriptId": execution_input.metadata.id,
        "model": execution_input.model,
        "reasoningEffort": execution_input.reasoning_effort,
        "domainKnowledgeEntryCount": len(execution_input.domain_knowledge_entries),
        "domainKnowledgeFingerprint": execution_input.domain_knowledge_fingerprint,
        "windowCount": _window_count(detail),
        "microEventCount": _micro_event_count(detail),
        "excludedRangeCount": _excluded_range_count(detail),
        "asrCorrectionCandidateCount": _asr_count(detail),
        "firstCueId": _first_cue_id(detail),
        "lastCueId": _last_cue_id(detail),
        "jobId": job.id,
        "jobAttemptId": attempt.id,
        **_window_run_stats_json(run_stats),
    }
