from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainKnowledgePromptAliasRecord,
    DomainKnowledgePromptEntryRecord,
    DomainKnowledgeRepositoryPort,
)
from codex_sdk_cli.domains.llm_traces.ports import (
    LlmTraceEvent,
    LlmTraceRecorderPort,
    NoopLlmTraceRecorder,
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
    ApplyScope,
    AsrCorrectionCandidateCreate,
    ContentKind,
    CorrectionType,
    ExcludedRangeReason,
    MicroEventCandidateCreate,
    MicroEventExcludedRangeCreate,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionRepositoryPort,
    MicroEventExtractionRequest,
    MicroEventExtractionResult,
    MicroEventExtractionWindowCreate,
    MicroEventExtractorPort,
    MicroEventRepairRequest,
    ProgramMode,
    RelationToPrevious,
    SupportLevel,
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

MICRO_EVENT_EXTRACT_VIDEO_TASK_CONCURRENCY_LIMIT = 1
MICRO_EVENT_EXTRACT_BATCH_SCAN_LIMIT = 500
DOMAIN_KNOWLEDGE_PROMPT_ENTRY_LIMIT = 80


@dataclass(frozen=True, slots=True)
class _CueWindow:
    window_index: int
    context_before: list[TranscriptCueRecord]
    owned_cues: list[TranscriptCueRecord]
    context_after: list[TranscriptCueRecord]


@dataclass(frozen=True, slots=True)
class _ExtractionExecutionInput:
    video: VideoRecord
    metadata: YouTubeTranscriptMetadataRecord
    cues: list[TranscriptCueRecord]
    window_minutes: int
    overlap_minutes: int
    model: CodexModelChoice
    reasoning_effort: ReasoningEffortChoice
    actor_type: OperationEventActorType
    domain_knowledge_entries: list[DomainKnowledgePromptEntryRecord]
    domain_knowledge_fingerprint: str
    streamer_name: str | None
    prompt: ResolvedPrompt


@dataclass(frozen=True, slots=True)
class _PreparedExtraction:
    execution_input: _ExtractionExecutionInput
    input_hash: str
    input_json: JsonObject


@dataclass(slots=True)
class _EnqueueCounters:
    scanned_count: int = 0
    enqueued_count: int = 0
    already_pending_count: int = 0
    already_running_count: int = 0
    already_succeeded_count: int = 0
    skipped_failed_count: int = 0
    ineligible_count: int = 0


class _MicroEventWindowValidationFailure(Exception):
    def __init__(
        self,
        error: MicroEventExtractionOutputInvalid,
        failed_window: MicroEventExtractionWindowCreate,
    ) -> None:
        super().__init__(str(error))
        self.error = error
        self.failed_window = failed_window


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
        self._events = events
        self._llm_traces = llm_traces or NoopLlmTraceRecorder()

    async def execute(
        self,
        video_id: int,
        request: MicroEventExtractRequest,
    ) -> MicroEventExtractResponse:
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
        await self._record_task_event(
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
                "domainKnowledgeEntryCount": len(
                    prepared.execution_input.domain_knowledge_entries
                ),
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
        detail = await self._micro_events.get_latest_succeeded_extraction(
            video_id=video_id
        )
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
        if await self._video_tasks.count_running(
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME
        ) >= MICRO_EVENT_EXTRACT_VIDEO_TASK_CONCURRENCY_LIMIT:
            raise VideoTaskRetryNotAllowed("Micro-event extraction is already running.")

        video, metadata, cues = await self._load_inputs(
            _required_int(job.input_json, "videoId")
        )
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
            reasoning_effort=(
                _reasoning_effort_output(job.input_json) or self._reasoning_effort
            ),
            actor_type="retry_executor",
            domain_knowledge_entries=domain_knowledge_entries,
            domain_knowledge_fingerprint=domain_knowledge_fingerprint,
            streamer_name=streamer_name,
            prompt=prompt,
        )
        await self._record_task_event(
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
        await self._record_task_event(
            "micro_event_extract.task_running",
            "info",
            "Micro-event extraction task started running.",
            task=task,
            execution_input=execution_input,
            metadata_json={"attemptId": attempt.id, "workerId": worker_id},
        )
        return await self._execute_job_attempt(
            job,
            attempt,
            task=task,
            execution_input=execution_input,
            timeout_seconds=timeout_seconds,
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
            await self._record_task_event(
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
        await self._record_task_event(
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
        domain_knowledge_fingerprint = _domain_knowledge_fingerprint(
            domain_knowledge_entries
        )
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
        domain_knowledge_fingerprint = (
            _str_output(input_json, "domainKnowledgeFingerprint")
            or _domain_knowledge_fingerprint(domain_knowledge_entries)
        )
        prompt = await self._resolve_prompt_from_input(input_json)
        return _ExtractionExecutionInput(
            video=video,
            metadata=metadata,
            cues=cues,
            window_minutes=_required_int(input_json, "windowMinutes"),
            overlap_minutes=_required_int(input_json, "overlapMinutes"),
            model=_model_output(input_json) or self._model,
            reasoning_effort=_reasoning_effort_output(input_json)
            or self._reasoning_effort,
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
            raise MicroEventExtractionPreconditionFailed(
                "Succeeded transcript cue generation task is required."
            )
        metadata = await self._transcripts.get_transcript_metadata(
            cue_task.output_transcript_id
        )
        if metadata is None:
            raise YouTubeTranscriptMetadataNotFound("Transcript metadata not found.")
        cues = await self._transcript_cues.list_cues(metadata.id)
        if not cues:
            raise MicroEventExtractionPreconditionFailed("Transcript cues are required.")
        return video, metadata, cues

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
        entries = await self._domain_knowledge.list_prompt_entries_for_streamer(
            streamer_id
        )
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
        return await self._execute_task(task, execution_input, input_hash)

    async def _execute_task(
        self,
        task: VideoTaskRecord,
        execution_input: _ExtractionExecutionInput,
        input_hash: str,
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
        await self._record_task_event(
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
        )

    async def _execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        *,
        task: VideoTaskRecord,
        execution_input: _ExtractionExecutionInput,
        timeout_seconds: int,
    ) -> MicroEventExtractResponse:
        try:
            await self._micro_events.delete_extraction(task.id)
            windows = await asyncio.wait_for(
                self._extract_windows(
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
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
                output_json=_attempt_output_json(execution_input, job=job, attempt=attempt),
            )
            await self._record_task_event(
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
                output_json=_attempt_output_json(execution_input, job=job, attempt=attempt),
            )
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=error_type,
                error_message=error_message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            await self._record_task_event(
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
        output_json = _output_json(execution_input, detail, job=job, attempt=attempt)
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
        await self._record_task_event(
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
    ) -> list[MicroEventExtractionWindowCreate]:
        cue_windows = _cue_windows(
            execution_input.cues,
            window_minutes=execution_input.window_minutes,
            overlap_minutes=execution_input.overlap_minutes,
        )
        if not cue_windows:
            return []
        queue: asyncio.Queue[_CueWindow] = asyncio.Queue()
        for cue_window in cue_windows:
            queue.put_nowait(cue_window)
        results: dict[int, MicroEventExtractionWindowCreate] = {}
        worker_count = min(self._concurrency_limit, len(cue_windows))

        async def worker() -> None:
            while True:
                try:
                    cue_window = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    results[cue_window.window_index] = await self._extract_window(
                        task=task,
                        job=job,
                        attempt=attempt,
                        execution_input=execution_input,
                        cue_window=cue_window,
                        window_count=len(cue_windows),
                    )
                finally:
                    queue.task_done()

        worker_tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
        try:
            await asyncio.gather(*worker_tasks)
        except _MicroEventWindowValidationFailure as exc:
            for worker_task in worker_tasks:
                if not worker_task.done():
                    worker_task.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            await self._micro_events.replace_extraction(
                task.id,
                _sorted_windows([*results.values(), exc.failed_window]),
            )
            raise exc.error from exc
        except Exception:
            for worker_task in worker_tasks:
                if not worker_task.done():
                    worker_task.cancel()
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            raise
        return _sorted_windows(results.values())

    async def _extract_window(
        self,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        execution_input: _ExtractionExecutionInput,
        cue_window: _CueWindow,
        window_count: int,
    ) -> MicroEventExtractionWindowCreate:
        prompt = _window_prompt(execution_input, cue_window)
        await self._llm_traces.record_event(
            _micro_trace_event(
                operation="extract_window",
                phase="window_started",
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                window_count=window_count,
                prompt_text=prompt,
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
            await self._llm_traces.record_event(
                _micro_trace_event(
                    operation="extract_window",
                    phase="task_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    cue_window=cue_window,
                    window_count=window_count,
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type=exc.__class__.__name__,
                    error_message=str(exc) or exc.__class__.__name__,
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
                    phase="window_succeeded",
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    cue_window=cue_window,
                    window_count=window_count,
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    metadata={"microEventCount": len(window.micro_events)},
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
            repaired = await self._repair_window_if_recoverable(
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
                        phase="window_succeeded",
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

    async def _repair_window_if_recoverable(
        self,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        execution_input: _ExtractionExecutionInput,
        cue_window: _CueWindow,
        window_count: int,
        original_prompt: str,
        original_result: MicroEventExtractionResult,
        original_error: MicroEventExtractionOutputInvalid,
    ) -> MicroEventExtractionWindowCreate | None:
        original_error_message = str(original_error)
        if not _is_recoverable_window_validation_error(original_error_message):
            return None
        await self._record_task_event(
            "micro_event_extract.window_repair_requested",
            "warning",
            "Micro-event extraction window repair requested.",
            task=task,
            execution_input=execution_input,
            reason="window_validation_repair",
            error_type=original_error.__class__.__name__,
            error_message=original_error_message,
            metadata_json=_repair_event_metadata(
                cue_window,
                original_error=original_error_message,
            ),
        )
        repair_prompt = _repair_window_prompt(
            original_prompt=original_prompt,
            original_response=original_result.final_response,
            validation_error=original_error_message,
            cue_window=cue_window,
        )
        await self._llm_traces.record_event(
            _micro_trace_event(
                operation="repair_window",
                phase="repair_requested",
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                window_count=window_count,
                repair_index=1,
                prompt_text=repair_prompt,
                error_type=original_error.__class__.__name__,
                error_message=original_error_message,
            )
        )
        started_at = time.monotonic()
        try:
            repair_result = await self._extractor.repair_window(
                MicroEventRepairRequest(
                    prompt=repair_prompt,
                    original_prompt=original_prompt,
                    original_response=original_result.final_response,
                    validation_error=original_error_message,
                    owned_start_cue_id=cue_window.owned_cues[0].cue_id,
                    owned_end_cue_id=cue_window.owned_cues[-1].cue_id,
                    owned_cue_ids=[cue.cue_id for cue in cue_window.owned_cues],
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
            await self._llm_traces.record_event(
                _micro_trace_event(
                    operation="repair_window",
                    phase="repair_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    cue_window=cue_window,
                    window_count=window_count,
                    repair_index=1,
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type=exc.__class__.__name__,
                    error_message=str(exc) or exc.__class__.__name__,
                )
            )
            await self._record_task_event(
                "micro_event_extract.window_repair_failed",
                "error",
                "Micro-event extraction window repair failed.",
                task=task,
                execution_input=execution_input,
                reason="window_repair_exception",
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
                metadata_json=_repair_event_metadata(
                    cue_window,
                    original_error=original_error_message,
                    repair_error=str(exc) or exc.__class__.__name__,
                ),
            )
            return None
        await self._llm_traces.record_event(
            _micro_trace_event(
                operation="repair_window",
                phase="repair_response_received",
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                window_count=window_count,
                repair_index=1,
                result=repair_result,
                elapsed_ms=_elapsed_ms(started_at),
                raw_response_text=repair_result.final_response,
            )
        )
        repair_warning: MicroEventOutputWarning = {
            "type": "llm_repaired_window",
            "originalError": original_error_message,
            "repairThreadId": repair_result.thread_id,
            "repairTurnId": repair_result.turn_id,
        }
        try:
            repaired_window = _validated_window(
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                result=repair_result,
                extra_warnings=[repair_warning],
            )
        except MicroEventExtractionOutputInvalid as exc:
            repair_error = str(exc)
            await self._llm_traces.record_event(
                _micro_trace_event(
                    operation="repair_window",
                    phase="repair_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    cue_window=cue_window,
                    window_count=window_count,
                    repair_index=1,
                    result=repair_result,
                    elapsed_ms=_elapsed_ms(started_at),
                    raw_response_text=repair_result.final_response,
                    error_type=exc.__class__.__name__,
                    error_message=repair_error,
                )
            )
            await self._record_task_event(
                "micro_event_extract.window_repair_failed",
                "error",
                "Micro-event extraction window repair produced invalid output.",
                task=task,
                execution_input=execution_input,
                reason="window_repair_invalid",
                error_type=exc.__class__.__name__,
                error_message=repair_error,
                metadata_json=_repair_event_metadata(
                    cue_window,
                    original_error=original_error_message,
                    repair_error=repair_error,
                    repair_thread_id=repair_result.thread_id,
                    repair_turn_id=repair_result.turn_id,
                ),
            )
            return None
        await self._llm_traces.record_event(
            _micro_trace_event(
                operation="repair_window",
                phase="repair_succeeded",
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                window_count=window_count,
                repair_index=1,
                result=repair_result,
                elapsed_ms=_elapsed_ms(started_at),
                metadata={"microEventCount": len(repaired_window.micro_events)},
            )
        )
        await self._record_task_event(
            "micro_event_extract.window_repaired",
            "warning",
            "Micro-event extraction window repaired.",
            task=task,
            execution_input=execution_input,
            reason="window_repaired",
            error_type=original_error.__class__.__name__,
            error_message=original_error_message,
            metadata_json=_repair_event_metadata(
                cue_window,
                original_error=original_error_message,
                repair_thread_id=repair_result.thread_id,
                repair_turn_id=repair_result.turn_id,
            ),
        )
        return repaired_window

    async def _record_task_event(
        self,
        event_type: str,
        severity: OperationEventSeverity,
        message: str,
        *,
        task: VideoTaskRecord,
        execution_input: _ExtractionExecutionInput,
        reason: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata_json: JsonObject | None = None,
    ) -> None:
        metadata: JsonObject = dict(metadata_json or {})
        if reason is not None:
            metadata["reason"] = reason
        metadata["transcriptId"] = execution_input.metadata.id
        metadata["model"] = execution_input.model
        metadata["reasoningEffort"] = execution_input.reasoning_effort
        metadata["domainKnowledgeEntryCount"] = len(
            execution_input.domain_knowledge_entries
        )
        metadata["domainKnowledgeFingerprint"] = (
            execution_input.domain_knowledge_fingerprint
        )
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity=severity,
                message=message,
                actor_type=execution_input.actor_type,
                source="micro_events.extract",
                job_id=task.job_id,
                job_attempt_id=task.job_attempt_id,
                video_task_id=task.id,
                video_id=execution_input.video.id,
                subject_type="video",
                subject_id=execution_input.video.id,
                external_key=execution_input.video.youtube_video_id,
                error_type=error_type,
                error_message=error_message,
                metadata_json=metadata,
            ),
        )


def _micro_trace_event(
    *,
    operation: str,
    phase: str,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow | None = None,
    window_count: int | None = None,
    repair_index: int | None = None,
    result: MicroEventExtractionResult | None = None,
    elapsed_ms: int | None = None,
    prompt_text: str | None = None,
    raw_response_text: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata: JsonObject | None = None,
) -> LlmTraceEvent:
    return LlmTraceEvent(
        source="micro_event_extract",
        operation=operation,
        phase=phase,
        video_task_id=task.id,
        video_id=execution_input.video.id,
        job_id=job.id,
        job_attempt_id=attempt.id,
        window_index=cue_window.window_index if cue_window is not None else None,
        window_count=window_count,
        repair_index=repair_index,
        model=str(execution_input.model),
        reasoning_effort=str(execution_input.reasoning_effort),
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


def _micro_event_validation_failure_phase(
    exc: MicroEventExtractionOutputInvalid,
) -> str:
    message = str(exc).casefold()
    if "invalid json" in message or "json" in message and "decode" in message:
        return "parse_failed"
    return "validation_failed"


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.monotonic() - started_at) * 1000))


def _normalized_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    return token.upper().replace("-", "_").replace(" ", "_")


def _normalize_program_mode(value: object) -> object:
    token = _normalized_token(value)
    allowed = {
        "OPENING",
        "JUST_CHATTING",
        "GAME_SETUP",
        "GAMEPLAY",
        "BREAK",
        "POST_GAME",
        "CLOSING",
        "UNKNOWN",
    }
    if token in allowed:
        return token
    aliases = {
        "CHAT": "JUST_CHATTING",
        "TALK": "JUST_CHATTING",
        "TALKING": "JUST_CHATTING",
        "FREE_TALK": "JUST_CHATTING",
        "GAME": "GAMEPLAY",
        "PLAYING_GAME": "GAMEPLAY",
        "ENDING": "CLOSING",
    }
    return aliases.get(token or "", "UNKNOWN")


def _normalize_content_kind(value: object) -> object:
    token = _normalized_token(value)
    allowed = {
        "ANNOUNCEMENT",
        "PERSONAL_STORY",
        "OPINION",
        "QNA",
        "REACTION",
        "TECHNICAL_SETUP",
        "GAME_PROGRESS",
        "GAME_DISCUSSION",
        "COMMUNITY_REVIEW",
        "MEDIA_REVIEW",
        "META_CHAT",
        "OTHER",
    }
    if token in allowed:
        return token
    aliases = {
        "QUESTION_AND_ANSWER": "QNA",
        "QA": "QNA",
        "GAME_TALK": "GAME_DISCUSSION",
        "GAMEPLAY": "GAME_PROGRESS",
        "SETUP": "TECHNICAL_SETUP",
        "TECHNICAL": "TECHNICAL_SETUP",
        "CHAT": "META_CHAT",
        "JUST_CHATTING": "META_CHAT",
    }
    return aliases.get(token or "", "OTHER")


def _normalize_relation_to_previous(value: object) -> object:
    token = _normalized_token(value)
    allowed = {"NEW_TOPIC", "CONTINUATION", "ASIDE", "RETURN"}
    if token in allowed:
        return token
    aliases = {
        "NEW": "NEW_TOPIC",
        "TOPIC_CHANGE": "NEW_TOPIC",
        "CONTINUE": "CONTINUATION",
        "FOLLOW_UP": "CONTINUATION",
        "SIDE_TOPIC": "ASIDE",
        "BACK": "RETURN",
        "RETURN_TO_TOPIC": "RETURN",
    }
    return aliases.get(token or "", "NEW_TOPIC")


def _normalize_support_level(value: object) -> object:
    token = _normalized_token(value)
    allowed = {"DIRECT", "CONTEXTUAL", "AMBIGUOUS"}
    if token in allowed:
        return token
    aliases = {
        "EXPLICIT": "DIRECT",
        "CLEAR": "DIRECT",
        "INFERRED": "CONTEXTUAL",
        "INDIRECT": "CONTEXTUAL",
        "UNCERTAIN": "AMBIGUOUS",
        "UNKNOWN": "AMBIGUOUS",
    }
    return aliases.get(token or "", "AMBIGUOUS")


def _normalize_excluded_range_reason(value: object) -> object:
    token = _normalized_token(value)
    allowed = {
        "MUSIC_ONLY",
        "SILENCE_OR_GAP",
        "UNINTELLIGIBLE",
        "LOW_INFORMATION",
        "TECHNICAL_NOISE",
    }
    if token in allowed:
        return token
    aliases = {
        "SILENCE": "SILENCE_OR_GAP",
        "GAP": "SILENCE_OR_GAP",
        "NO_SPEECH": "SILENCE_OR_GAP",
        "INAUDIBLE": "UNINTELLIGIBLE",
        "NOISE": "TECHNICAL_NOISE",
        "TECHNICAL": "TECHNICAL_NOISE",
        "LOW_INFO": "LOW_INFORMATION",
        "NO_INFORMATION": "LOW_INFORMATION",
    }
    return aliases.get(token or "", "LOW_INFORMATION")


def _normalize_correction_type(value: object) -> object:
    token = _normalized_token(value)
    allowed = {
        "PROPER_NOUN",
        "GAME_TITLE",
        "CONTENT_TITLE",
        "COMMON_WORD",
        "FOOD",
        "PLACE",
        "STREAM_TERM",
        "CONTEXTUAL_TERM",
        "UNCERTAIN",
    }
    if token in allowed:
        return token
    aliases = {
        "PERSON_NAME": "PROPER_NOUN",
        "PERSON": "PROPER_NOUN",
        "PEOPLE": "PROPER_NOUN",
        "CHARACTER_NAME": "PROPER_NOUN",
        "NICKNAME": "PROPER_NOUN",
        "ORGANIZATION": "PROPER_NOUN",
        "ORG_NAME": "PROPER_NOUN",
        "TITLE": "CONTENT_TITLE",
        "VIDEO_TITLE": "CONTENT_TITLE",
        "MEDIA_TITLE": "CONTENT_TITLE",
        "GAME": "GAME_TITLE",
        "GAME_NAME": "GAME_TITLE",
        "LOCATION": "PLACE",
        "TERM": "CONTEXTUAL_TERM",
        "SLANG": "STREAM_TERM",
        "STREAMING_TERM": "STREAM_TERM",
        "UNKNOWN": "UNCERTAIN",
        "OTHER": "UNCERTAIN",
    }
    return aliases.get(token or "", "UNCERTAIN")


def _normalize_apply_scope(value: object) -> object:
    token = _normalized_token(value)
    allowed = {"NONE", "SEARCH_ONLY", "SEARCH_AND_SUMMARY", "DISPLAY_ALLOWED"}
    if token in allowed:
        return token
    aliases = {
        "SEARCH": "SEARCH_ONLY",
        "SUMMARY": "SEARCH_AND_SUMMARY",
        "SEARCH_SUMMARY": "SEARCH_AND_SUMMARY",
        "BOTH": "SEARCH_AND_SUMMARY",
        "DISPLAY": "DISPLAY_ALLOWED",
        "VISIBLE": "DISPLAY_ALLOWED",
        "UNKNOWN": "NONE",
        "OTHER": "NONE",
    }
    return aliases.get(token or "", "NONE")


class _MicroEventOutput(BaseModel):
    start_cue_id: str
    end_cue_id: str
    event: str = Field(min_length=1)
    program_mode: ProgramMode
    content_kind: ContentKind
    topics: list[str] = Field(min_length=1)
    relation_to_previous: RelationToPrevious
    continues_to_next: bool
    evidence_cue_ids: list[str] = Field(min_length=1, max_length=6)
    support_level: SupportLevel

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "program_mode",
        "content_kind",
        "relation_to_previous",
        "support_level",
        mode="before",
    )
    @classmethod
    def _normalize_enum_fields(cls, value: object, info: object) -> object:
        field_name = getattr(info, "field_name", "")
        if field_name == "program_mode":
            return _normalize_program_mode(value)
        if field_name == "content_kind":
            return _normalize_content_kind(value)
        if field_name == "relation_to_previous":
            return _normalize_relation_to_previous(value)
        if field_name == "support_level":
            return _normalize_support_level(value)
        return value


class _ExcludedRangeOutput(BaseModel):
    start_cue_id: str
    end_cue_id: str
    reason: ExcludedRangeReason

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: object) -> object:
        return _normalize_excluded_range_reason(value)


class _AsrCorrectionOutput(BaseModel):
    original: str = Field(min_length=1)
    suggested: str = Field(min_length=1)
    correction_type: CorrectionType
    apply_scope: ApplyScope
    confidence: float = Field(ge=0, le=1)

    model_config = ConfigDict(extra="ignore")

    @field_validator("correction_type", mode="before")
    @classmethod
    def _normalize_correction_type(cls, value: object) -> object:
        return _normalize_correction_type(value)

    @field_validator("apply_scope", mode="before")
    @classmethod
    def _normalize_apply_scope(cls, value: object) -> object:
        return _normalize_apply_scope(value)


class _ExtractorOutput(BaseModel):
    events: list[_MicroEventOutput] = Field(default_factory=list)
    excluded_ranges: list[_ExcludedRangeOutput] = Field(default_factory=list)
    asr_correction_candidates: list[_AsrCorrectionOutput] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


MicroEventOutputWarning = JsonObject


def _cue_windows(
    cues: list[TranscriptCueRecord],
    *,
    window_minutes: int,
    overlap_minutes: int,
) -> list[_CueWindow]:
    window_ms = window_minutes * 60_000
    context_ms = overlap_minutes * 60_000
    first_start_ms = cues[0].start_ms
    last_end_ms = cues[-1].end_ms
    windows: list[_CueWindow] = []
    window_start_ms = first_start_ms
    window_index = 1
    while window_start_ms <= last_end_ms:
        window_end_ms = window_start_ms + window_ms
        owned_cues = [
            cue
            for cue in cues
            if cue.end_ms > window_start_ms and cue.start_ms < window_end_ms
        ]
        if owned_cues:
            context_before = [
                cue
                for cue in cues
                if cue.end_ms > window_start_ms - context_ms
                and cue.end_ms <= window_start_ms
            ]
            context_after = [
                cue
                for cue in cues
                if cue.start_ms >= window_end_ms
                and cue.start_ms < window_end_ms + context_ms
            ]
            windows.append(
                _CueWindow(
                    window_index=window_index,
                    context_before=context_before,
                    owned_cues=owned_cues,
                    context_after=context_after,
                )
            )
            window_index += 1
        if window_end_ms >= last_end_ms:
            break
        window_start_ms += window_ms
    return windows


def _window_prompt(
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow,
) -> str:
    term_annotations = _window_term_annotations(execution_input, cue_window)
    video_metadata: JsonObject = {
        "videoTitle": execution_input.video.title,
        "videoDescription": _compact_prompt_text(execution_input.video.description),
        "publishedAt": execution_input.video.published_at.isoformat(),
        "streamerName": execution_input.streamer_name,
        "transcriptLanguage": execution_input.metadata.language,
        "transcriptLanguageCode": execution_input.metadata.language_code,
        "transcriptSource": (
            "generated" if execution_input.metadata.is_generated else "manual"
        ),
        "windowIndex": cue_window.window_index,
    }
    return "\n\n".join(
        [
            execution_input.prompt.body,
            "# INPUT_METADATA",
            json.dumps(video_metadata, ensure_ascii=False),
            "# ?ъ쟾 ?먯젙???⑹뼱 annotation",
            json.dumps(term_annotations, ensure_ascii=False),
            "# 泥섎━ 踰붿쐞",
            "\n".join(
                [
                    f"OWNED_START_CUE_ID: {cue_window.owned_cues[0].cue_id}",
                    f"OWNED_END_CUE_ID: {cue_window.owned_cues[-1].cue_id}",
                ]
            ),
            "# CONTEXT_BEFORE",
            _format_cue_block(cue_window.context_before, execution_input.cues),
            "# OWNED_RANGE",
            _format_cue_block(cue_window.owned_cues, execution_input.cues),
            "# CONTEXT_AFTER",
            _format_cue_block(cue_window.context_after, execution_input.cues),
        ]
    )


def _repair_window_prompt(
    *,
    original_prompt: str,
    original_response: str,
    validation_error: str,
    cue_window: _CueWindow,
) -> str:
    return "\n\n".join(
        [
            "# 역할",
            "너는 micro-event extractor가 만든 JSON을 고치는 repair step이다.",
            (
                "새 사건을 만들지 말고, 원본 응답의 의미와 분류를 가능한 한 "
                "유지하면서 cue 범위와 coverage 정합성만 고친다."
            ),
            "# 실패 원인",
            validation_error,
            "# 반드시 지킬 규칙",
            "\n".join(
                [
                    "1. 반드시 JSON 객체만 출력한다.",
                    (
                        "2. 출력 schema는 events, excluded_ranges, "
                        "asr_correction_candidates만 사용한다."
                    ),
                    "3. OWNED_RANGE 밖 cue_id는 절대 사용하지 않는다.",
                    "4. 모든 OWNED_RANGE cue를 event 또는 excluded_range로 정확히 한 번 덮는다.",
                    (
                        "5. event 문장, program_mode, content_kind, topics는 "
                        "원본 의미를 가능한 한 유지한다."
                    ),
                    (
                        "6. cue 범위를 고치기 어렵거나 정보가 낮은 구간은 "
                        "excluded_range reason=LOW_INFORMATION으로 덮는다."
                    ),
                    "7. asr_correction_candidates에는 evidence_cue_ids를 출력하지 않는다.",
                ]
            ),
            "# OWNED_RANGE",
            json.dumps(
                {
                    "ownedStartCueId": cue_window.owned_cues[0].cue_id,
                    "ownedEndCueId": cue_window.owned_cues[-1].cue_id,
                    "ownedCueIds": [cue.cue_id for cue in cue_window.owned_cues],
                },
                ensure_ascii=False,
            ),
            "# 원본 window prompt",
            original_prompt,
            "# 고쳐야 할 원본 응답",
            original_response,
        ]
    )


def _is_recoverable_window_validation_error(error_message: str) -> bool:
    if error_message in {
        "Extractor returned invalid JSON.",
        "Extractor output must be a JSON object.",
        "event must have at least one evidence_cue_id inside its cue range.",
    }:
        return False
    recoverable_fragments = (
        "Extractor referenced cue_id outside OWNED_RANGE",
        "Extractor left a gap in OWNED_RANGE coverage.",
        "Extractor returned overlapping",
        "Extractor did not cover every owned cue exactly once.",
        "start_cue_id must not come after end_cue_id.",
        "Extractor must cover OWNED_RANGE with events or excluded_ranges.",
    )
    return any(fragment in error_message for fragment in recoverable_fragments)


def _repair_event_metadata(
    cue_window: _CueWindow,
    *,
    original_error: str,
    repair_error: str | None = None,
    repair_thread_id: str | None = None,
    repair_turn_id: str | None = None,
) -> JsonObject:
    metadata: JsonObject = {
        "windowIndex": cue_window.window_index,
        "originalError": original_error,
        "ownedStartCueId": cue_window.owned_cues[0].cue_id,
        "ownedEndCueId": cue_window.owned_cues[-1].cue_id,
    }
    if repair_error is not None:
        metadata["repairError"] = repair_error
    if repair_thread_id is not None:
        metadata["repairThreadId"] = repair_thread_id
    if repair_turn_id is not None:
        metadata["repairTurnId"] = repair_turn_id
    return metadata


def _window_term_annotations(
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow,
) -> list[JsonObject]:
    cue_text = " ".join(
        cue.text
        for cue in [
            *cue_window.context_before,
            *cue_window.owned_cues,
            *cue_window.context_after,
        ]
    ).casefold()
    selected: list[DomainKnowledgePromptEntryRecord] = []
    for entry in execution_input.domain_knowledge_entries:
        if entry.prompt_policy == "ALWAYS_FOR_SCOPED_STREAMER":
            selected.append(entry)
            continue
        if entry.prompt_policy == "AUTO_ON_MATCH" and _domain_entry_matches_text(
            entry,
            cue_text,
        ):
            selected.append(entry)
    selected.sort(key=lambda entry: (-entry.priority, entry.entry_id))
    return [
        _domain_prompt_entry_json(entry)
        for entry in selected[:DOMAIN_KNOWLEDGE_PROMPT_ENTRY_LIMIT]
    ]


def _domain_entry_matches_text(
    entry: DomainKnowledgePromptEntryRecord,
    cue_text: str,
) -> bool:
    values = [entry.canonical_name, entry.display_name]
    values.extend(alias.surface_form for alias in entry.aliases)
    return any(value.strip().casefold() in cue_text for value in values if value)


def _domain_prompt_entry_json(
    entry: DomainKnowledgePromptEntryRecord,
) -> JsonObject:
    return {
        "entryId": entry.entry_id,
        "typeKey": entry.type_key,
        "typeLabel": entry.type_label,
        "canonicalForm": entry.canonical_name,
        "displayName": entry.display_name,
        "disambiguation": entry.disambiguation,
        "detail": entry.detail,
        "promptPolicy": entry.prompt_policy,
        "priority": entry.priority,
        "aliases": [_domain_prompt_alias_json(alias) for alias in entry.aliases],
    }


def _domain_prompt_alias_json(
    alias: DomainKnowledgePromptAliasRecord,
) -> JsonObject:
    return {
        "surfaceForm": alias.surface_form,
        "relation": alias.alias_kind,
        "certainty": alias.certainty,
        "applyScope": alias.apply_scope,
        "languageCode": alias.language_code,
        "note": alias.note,
    }


def _validated_window(
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow,
    result: MicroEventExtractionResult,
    extra_warnings: list[MicroEventOutputWarning] | None = None,
) -> MicroEventExtractionWindowCreate:
    parsed = _parse_extractor_output(result.final_response)
    output, warnings = _validate_extractor_output(parsed)
    if extra_warnings:
        warnings.extend(extra_warnings)
    cue_id_to_position = {
        cue.cue_id: position for position, cue in enumerate(cue_window.owned_cues)
    }
    event_creates: list[MicroEventCandidateCreate] = []
    ranges: list[tuple[str, int, int]] = []
    for index, event in enumerate(output.events, start=1):
        (
            start_cue_id,
            end_cue_id,
            start_position,
            end_position,
            evidence_cue_ids,
        ) = _validate_event_cue_refs(
            event,
            cue_id_to_position,
            warnings=warnings,
            event_index=index - 1,
        )
        ranges.append(("event", start_position, end_position))
        event_creates.append(
            MicroEventCandidateCreate(
                candidate_index=index,
                activity=event.program_mode,
                event=event.event,
                start_cue_id=start_cue_id,
                end_cue_id=end_cue_id,
                evidence_cue_ids=evidence_cue_ids,
                boundary_before=event.relation_to_previous in {"NEW_TOPIC", "RETURN"},
                boundary_after=not event.continues_to_next,
                confidence=_support_level_confidence(event.support_level),
                program_mode=event.program_mode,
                content_kind=event.content_kind,
                topics=_normalized_topics(event.topics),
                relation_to_previous=event.relation_to_previous,
                continues_to_next=event.continues_to_next,
                support_level=event.support_level,
            )
        )
    excluded_creates: list[MicroEventExcludedRangeCreate] = []
    for index, excluded_range in enumerate(output.excluded_ranges, start=1):
        (
            start_cue_id,
            end_cue_id,
            start_position,
            end_position,
        ) = _validate_range_cue_refs(
            excluded_range.start_cue_id,
            excluded_range.end_cue_id,
            cue_id_to_position,
        )
        ranges.append(("excluded_range", start_position, end_position))
        excluded_creates.append(
            MicroEventExcludedRangeCreate(
                range_index=index,
                start_cue_id=start_cue_id,
                end_cue_id=end_cue_id,
                reason=excluded_range.reason,
            )
        )
    _validate_owned_range_coverage(ranges, owned_cue_count=len(cue_window.owned_cues))
    asr_creates: list[AsrCorrectionCandidateCreate] = []
    for index, candidate in enumerate(output.asr_correction_candidates, start=1):
        asr_creates.append(
            AsrCorrectionCandidateCreate(
                candidate_index=index,
                original=candidate.original,
                suggested=candidate.suggested,
                correction_type=candidate.correction_type,
                apply_scope=candidate.apply_scope,
                confidence=candidate.confidence,
            )
        )
    return MicroEventExtractionWindowCreate(
        video_task_id=task.id,
        video_id=execution_input.video.id,
        transcript_id=execution_input.metadata.id,
        window_index=cue_window.window_index,
        start_cue_id=cue_window.owned_cues[0].cue_id,
        end_cue_id=cue_window.owned_cues[-1].cue_id,
        cue_count=len(cue_window.owned_cues),
        status="succeeded",
        carry_out_unfinished=any(event.continues_to_next for event in output.events),
        codex_thread_id=result.thread_id,
        codex_turn_id=result.turn_id,
        raw_response_text=result.final_response,
        parsed_response_json=cast(JsonObject, output.model_dump(mode="json")),
        validation_error=_warnings_json(warnings),
        source_job_id=job.id,
        source_job_attempt_id=attempt.id,
        micro_events=event_creates,
        excluded_ranges=excluded_creates,
        asr_correction_candidates=asr_creates,
    )


def _failed_window(
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow,
    result: MicroEventExtractionResult,
    validation_error: str,
) -> MicroEventExtractionWindowCreate:
    parsed_response: JsonObject | None = None
    try:
        parsed = json.loads(result.final_response)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        parsed_response = cast(JsonObject, parsed)
    return MicroEventExtractionWindowCreate(
        video_task_id=task.id,
        video_id=execution_input.video.id,
        transcript_id=execution_input.metadata.id,
        window_index=cue_window.window_index,
        start_cue_id=cue_window.owned_cues[0].cue_id,
        end_cue_id=cue_window.owned_cues[-1].cue_id,
        cue_count=len(cue_window.owned_cues),
        status="failed",
        carry_out_unfinished=False,
        codex_thread_id=result.thread_id,
        codex_turn_id=result.turn_id,
        raw_response_text=result.final_response,
        parsed_response_json=parsed_response,
        validation_error=validation_error,
        source_job_id=job.id,
        source_job_attempt_id=attempt.id,
    )


def _sorted_windows(
    windows: Iterable[MicroEventExtractionWindowCreate],
) -> list[MicroEventExtractionWindowCreate]:
    return sorted(windows, key=lambda window: window.window_index)


def _warnings_json(warnings: list[MicroEventOutputWarning]) -> str | None:
    if not warnings:
        return None
    return json.dumps(warnings, ensure_ascii=False)


def _parse_extractor_output(raw_response: str) -> JsonObject:
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise MicroEventExtractionOutputInvalid("Extractor returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise MicroEventExtractionOutputInvalid("Extractor output must be a JSON object.")
    return cast(JsonObject, parsed)


def _validate_extractor_output(
    parsed: JsonObject,
) -> tuple[_ExtractorOutput, list[MicroEventOutputWarning]]:
    normalized, warnings = _normalize_extractor_output(parsed)
    try:
        return _ExtractorOutput.model_validate(normalized), warnings
    except ValidationError as exc:
        message = json.dumps(exc.errors(include_url=False), ensure_ascii=False)
        raise MicroEventExtractionOutputInvalid(message) from exc


def _normalize_extractor_output(
    parsed: JsonObject,
) -> tuple[JsonObject, list[MicroEventOutputWarning]]:
    normalized: JsonObject = dict(parsed)
    warnings: list[MicroEventOutputWarning] = []
    _merge_continued_events(normalized, warnings)
    events = normalized.get("events")
    excluded_ranges = normalized.get("excluded_ranges")
    existing_excluded_ranges = excluded_ranges if isinstance(excluded_ranges, list) else []
    moved_excluded_ranges: list[object] = []
    if isinstance(events, list):
        normalized_events: list[object] = []
        for index, event in enumerate(events):
            if _is_misplaced_excluded_range_event(event):
                target_index = len(existing_excluded_ranges) + len(moved_excluded_ranges)
                moved_excluded_ranges.append(
                    _normalize_misplaced_excluded_range_event(
                        event,
                        from_index=index,
                        to_index=target_index,
                        warnings=warnings,
                    )
                )
                continue
            normalized_events.append(_normalize_event_output(event, index, warnings))
        normalized["events"] = normalized_events
    if isinstance(excluded_ranges, list):
        normalized["excluded_ranges"] = [
            _normalize_excluded_range_output(excluded_range, index, warnings)
            for index, excluded_range in enumerate(excluded_ranges)
        ]
    if moved_excluded_ranges:
        normalized["excluded_ranges"] = [
            *(
                normalized["excluded_ranges"]
                if isinstance(normalized.get("excluded_ranges"), list)
                else []
            ),
            *moved_excluded_ranges,
        ]
    term_annotations = normalized.pop("term_annotations", None)
    asr_candidates = normalized.get("asr_correction_candidates")
    if term_annotations is not None:
        moved_asr_candidates = _normalize_term_annotations(
            term_annotations,
            warnings,
        )
        if moved_asr_candidates:
            existing_asr_candidates = asr_candidates if isinstance(asr_candidates, list) else []
            normalized["asr_correction_candidates"] = [
                *existing_asr_candidates,
                *moved_asr_candidates,
            ]
            asr_candidates = normalized["asr_correction_candidates"]
    if isinstance(asr_candidates, list):
        normalized["asr_correction_candidates"] = [
            _normalize_asr_correction_output(candidate, index, warnings)
            for index, candidate in enumerate(asr_candidates)
        ]
    _drop_unknown_top_level_fields(normalized, warnings)
    return normalized, warnings


def _merge_continued_events(
    normalized: JsonObject,
    warnings: list[MicroEventOutputWarning],
) -> None:
    continued_events = normalized.pop("events_continued", None)
    if continued_events is None:
        return
    if not isinstance(continued_events, list):
        warnings.append(
            {
                "type": "ignored_events_continued",
                "path": "events_continued",
                "reason": "expected list",
            }
        )
        return
    events = normalized.get("events")
    if events is None:
        normalized["events"] = continued_events
    elif isinstance(events, list):
        normalized["events"] = [*events, *continued_events]
    else:
        warnings.append(
            {
                "type": "ignored_events_continued",
                "path": "events_continued",
                "reason": "events is not a list",
                "ignoredCount": len(continued_events),
            }
        )
        return
    warnings.append(
        {
            "type": "moved_events_continued_to_events",
            "fromPath": "events_continued",
            "toPath": "events",
            "movedCount": len(continued_events),
        }
    )


def _drop_unknown_top_level_fields(
    normalized: JsonObject,
    warnings: list[MicroEventOutputWarning],
) -> None:
    allowed_fields = {"events", "excluded_ranges", "asr_correction_candidates"}
    for key in sorted(set(normalized) - allowed_fields):
        normalized.pop(key, None)
        warnings.append(
            {
                "type": "ignored_unknown_top_level_field",
                "path": key,
            }
        )


def _normalize_term_annotations(
    annotations: object,
    warnings: list[MicroEventOutputWarning],
) -> list[JsonObject]:
    if not isinstance(annotations, list):
        warnings.append(
            {
                "type": "ignored_term_annotations",
                "path": "term_annotations",
                "reason": "expected list",
            }
        )
        return []

    moved: list[JsonObject] = []
    skipped = 0
    for index, annotation in enumerate(annotations):
        candidate = _term_annotation_to_asr_candidate(annotation)
        if candidate is None:
            skipped += 1
            warnings.append(
                {
                    "type": "ignored_term_annotation",
                    "path": f"term_annotations[{index}]",
                    "reason": "missing term/canonical text",
                }
            )
            continue
        moved.append(candidate)
    warnings.append(
        {
            "type": "moved_term_annotations_to_asr_correction_candidates",
            "fromPath": "term_annotations",
            "toPath": "asr_correction_candidates",
            "originalCount": len(annotations),
            "movedCount": len(moved),
            "skippedCount": skipped,
        }
    )
    return moved


def _term_annotation_to_asr_candidate(annotation: object) -> JsonObject | None:
    if not isinstance(annotation, dict):
        return None
    original = _first_non_empty_string(
        annotation.get("original"),
        annotation.get("surface"),
        annotation.get("term"),
    )
    suggested = _first_non_empty_string(
        annotation.get("suggested"),
        annotation.get("canonical"),
    )
    if original is None or suggested is None:
        return None
    annotation_type = _first_non_empty_string(
        annotation.get("correction_type"),
        annotation.get("annotation_type"),
        annotation.get("type"),
    )
    return {
        "original": original,
        "suggested": suggested,
        "correction_type": _term_annotation_correction_type(annotation_type),
        "apply_scope": _term_annotation_apply_scope(annotation_type),
        "confidence": _term_annotation_confidence(annotation.get("confidence")),
    }


def _first_non_empty_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _term_annotation_correction_type(annotation_type: str | None) -> CorrectionType:
    token = _normalized_token(annotation_type)
    if token in {"WORDPLAY_OR_NICKNAME", "SEARCH_ALIAS"}:
        return "STREAM_TERM"
    if token in {"ASR_ERROR", "SPEAKER_MISTAKE"}:
        return "UNCERTAIN"
    return cast(CorrectionType, _normalize_correction_type(annotation_type))


def _term_annotation_apply_scope(annotation_type: str | None) -> ApplyScope:
    token = _normalized_token(annotation_type)
    if token in {"WORDPLAY_OR_NICKNAME", "SEARCH_ALIAS"}:
        return "SEARCH_AND_SUMMARY"
    if token == "UNCERTAIN":
        return "NONE"
    return "SEARCH_ONLY"


def _term_annotation_confidence(value: object) -> float:
    if isinstance(value, int | float):
        return min(max(float(value), 0.0), 1.0)
    return 0.6


def _is_misplaced_excluded_range_event(event: object) -> bool:
    return (
        isinstance(event, dict)
        and "event" not in event
        and "start_cue_id" in event
        and "end_cue_id" in event
        and "reason" in event
    )


def _normalize_misplaced_excluded_range_event(
    event: object,
    *,
    from_index: int,
    to_index: int,
    warnings: list[MicroEventOutputWarning],
) -> object:
    if not isinstance(event, dict):
        return event
    misplaced_range: JsonObject = {
        "start_cue_id": event["start_cue_id"],
        "end_cue_id": event["end_cue_id"],
        "reason": event["reason"],
    }
    normalized = _normalize_excluded_range_output(
        misplaced_range,
        to_index,
        warnings,
    )
    warnings.append(
        {
            "type": "moved_event_to_excluded_range",
            "fromPath": f"events[{from_index}]",
            "toPath": f"excluded_ranges[{to_index}]",
            "reason": event["reason"],
        }
    )
    return normalized


def _normalize_event_output(
    event: object,
    index: int,
    warnings: list[MicroEventOutputWarning],
) -> object:
    if not isinstance(event, dict):
        return event
    normalized: JsonObject = dict(event)
    if "event" in normalized and "reason" in normalized:
        normalized.pop("reason", None)
        warnings.append(
            {
                "type": "removed_event_reason_field",
                "path": f"events[{index}].reason",
            }
        )
    _normalize_enum_value(
        normalized,
        "program_mode",
        f"events[{index}].program_mode",
        _normalize_program_mode,
        warnings,
    )
    _normalize_enum_value(
        normalized,
        "content_kind",
        f"events[{index}].content_kind",
        _normalize_content_kind,
        warnings,
    )
    _normalize_enum_value(
        normalized,
        "relation_to_previous",
        f"events[{index}].relation_to_previous",
        _normalize_relation_to_previous,
        warnings,
    )
    _normalize_enum_value(
        normalized,
        "support_level",
        f"events[{index}].support_level",
        _normalize_support_level,
        warnings,
    )
    topics = normalized.get("topics")
    if isinstance(topics, list) and len(topics) > 6:
        normalized["topics"] = topics[:6]
        warnings.append(
            {
                "type": "truncated_topics",
                "path": f"events[{index}].topics",
                "originalCount": len(topics),
                "keptCount": 6,
            }
        )
    evidence_cue_ids = normalized.get("evidence_cue_ids")
    if isinstance(evidence_cue_ids, list) and len(evidence_cue_ids) > 6:
        normalized["evidence_cue_ids"] = evidence_cue_ids[:6]
        warnings.append(
            {
                "type": "truncated_evidence_cue_ids",
                "path": f"events[{index}].evidence_cue_ids",
                "originalCount": len(evidence_cue_ids),
                "keptCount": 6,
            }
        )
    return normalized


def _normalize_excluded_range_output(
    excluded_range: object,
    index: int,
    warnings: list[MicroEventOutputWarning],
) -> object:
    if not isinstance(excluded_range, dict):
        return excluded_range
    normalized: JsonObject = dict(excluded_range)
    _normalize_enum_value(
        normalized,
        "reason",
        f"excluded_ranges[{index}].reason",
        _normalize_excluded_range_reason,
        warnings,
    )
    return normalized


def _normalize_asr_correction_output(
    candidate: object,
    index: int,
    warnings: list[MicroEventOutputWarning],
) -> object:
    if not isinstance(candidate, dict):
        return candidate
    normalized: JsonObject = dict(candidate)
    if "evidence_cue_ids" in normalized:
        normalized.pop("evidence_cue_ids", None)
        warnings.append(
            {
                "type": "ignored_asr_evidence_cue_ids",
                "path": f"asr_correction_candidates[{index}].evidence_cue_ids",
            }
        )
    _normalize_enum_value(
        normalized,
        "correction_type",
        f"asr_correction_candidates[{index}].correction_type",
        _normalize_correction_type,
        warnings,
    )
    _normalize_enum_value(
        normalized,
        "apply_scope",
        f"asr_correction_candidates[{index}].apply_scope",
        _normalize_apply_scope,
        warnings,
    )
    return normalized


def _normalize_enum_value(
    values: JsonObject,
    key: str,
    path: str,
    normalize: Callable[[object], object],
    warnings: list[MicroEventOutputWarning],
) -> None:
    if key not in values:
        return
    original = values[key]
    normalized = normalize(original)
    values[key] = normalized
    if original != normalized:
        warnings.append(
            {
                "type": "normalized_enum",
                "path": path,
                "original": original,
                "normalized": normalized,
            }
        )


def _validate_event_cue_refs(
    event: _MicroEventOutput,
    cue_id_to_position: dict[str, int],
    *,
    warnings: list[MicroEventOutputWarning],
    event_index: int,
) -> tuple[str, str, int, int, list[str]]:
    start_cue_id, end_cue_id, start_position, end_position = _validate_range_cue_refs(
        event.start_cue_id,
        event.end_cue_id,
        cue_id_to_position,
        warnings=warnings,
        path_prefix=f"events[{event_index}]",
    )
    valid_evidence_cue_ids: list[str] = []
    removed_evidence_cue_ids: list[str] = []
    for cue_id in event.evidence_cue_ids:
        resolved_cue_id = _resolve_cue_id(
            cue_id,
            cue_id_to_position,
            warnings=warnings,
            path=f"events[{event_index}].evidence_cue_ids",
        )
        if start_position <= cue_id_to_position[resolved_cue_id] <= end_position:
            valid_evidence_cue_ids.append(resolved_cue_id)
        else:
            removed_evidence_cue_ids.append(resolved_cue_id)
    if removed_evidence_cue_ids:
        warnings.append(
            {
                "type": "removed_out_of_event_range_evidence_cue_ids",
                "path": f"events[{event_index}].evidence_cue_ids",
                "removedCueIds": removed_evidence_cue_ids,
            }
        )
    if not valid_evidence_cue_ids:
        raise MicroEventExtractionOutputInvalid(
            "event must have at least one evidence_cue_id inside its cue range."
        )
    return start_cue_id, end_cue_id, start_position, end_position, valid_evidence_cue_ids


def _validate_range_cue_refs(
    start_cue_id: str,
    end_cue_id: str,
    cue_id_to_position: dict[str, int],
    *,
    warnings: list[MicroEventOutputWarning] | None = None,
    path_prefix: str | None = None,
) -> tuple[str, str, int, int]:
    resolved_start_cue_id = _resolve_cue_id(
        start_cue_id,
        cue_id_to_position,
        warnings=warnings,
        path=f"{path_prefix}.start_cue_id" if path_prefix else None,
    )
    resolved_end_cue_id = _resolve_cue_id(
        end_cue_id,
        cue_id_to_position,
        warnings=warnings,
        path=f"{path_prefix}.end_cue_id" if path_prefix else None,
    )
    start_position = cue_id_to_position[resolved_start_cue_id]
    end_position = cue_id_to_position[resolved_end_cue_id]
    if start_position > end_position:
        raise MicroEventExtractionOutputInvalid(
            "start_cue_id must not come after end_cue_id."
        )
    return resolved_start_cue_id, resolved_end_cue_id, start_position, end_position


def _validate_evidence_cue_ids(
    evidence_cue_ids: list[str],
    cue_id_to_position: dict[str, int],
) -> list[str]:
    return [_resolve_cue_id(cue_id, cue_id_to_position) for cue_id in evidence_cue_ids]


def _resolve_cue_id(
    cue_id: str,
    cue_id_to_position: dict[str, int],
    *,
    warnings: list[MicroEventOutputWarning] | None = None,
    path: str | None = None,
) -> str:
    if cue_id not in cue_id_to_position:
        resolved_cue_id = _unique_nearby_cue_id(cue_id, cue_id_to_position)
        if resolved_cue_id is not None:
            if warnings is not None:
                warnings.append(
                    {
                        "type": "repaired_cue_id",
                        "path": path or "cue_id",
                        "originalCueId": cue_id,
                        "repairedCueId": resolved_cue_id,
                    }
                )
            return resolved_cue_id
        raise MicroEventExtractionOutputInvalid(
            f"Extractor referenced cue_id outside OWNED_RANGE: {cue_id}"
        )
    return cue_id


def _unique_nearby_cue_id(
    cue_id: str,
    cue_id_to_position: dict[str, int],
) -> str | None:
    split = cue_id.rsplit("-c", maxsplit=1)
    if len(split) != 2:
        return None
    prefix, suffix = split
    matches = [
        candidate
        for candidate in cue_id_to_position
        if candidate.startswith(f"{prefix}-c")
        and _edit_distance_at_most_one(candidate.rsplit("-c", maxsplit=1)[1], suffix)
    ]
    return matches[0] if len(matches) == 1 else None


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) == 1
    if len(left) > len(right):
        left, right = right, left
    left_index = 0
    right_index = 0
    edits = 0
    while left_index < len(left) and right_index < len(right):
        if left[left_index] == right[right_index]:
            left_index += 1
            right_index += 1
            continue
        edits += 1
        right_index += 1
        if edits > 1:
            return False
    return edits + (len(right) - right_index) == 1


def _validate_owned_range_coverage(
    ranges: list[tuple[str, int, int]],
    *,
    owned_cue_count: int,
) -> None:
    if not ranges:
        raise MicroEventExtractionOutputInvalid(
            "Extractor must cover OWNED_RANGE with events or excluded_ranges."
        )
    sorted_ranges = sorted(ranges, key=lambda item: item[1])
    previous_end = -1
    for kind, start_position, end_position in sorted_ranges:
        if start_position <= previous_end:
            raise MicroEventExtractionOutputInvalid(
                f"Extractor returned overlapping {kind} ranges."
            )
        if start_position != previous_end + 1:
            raise MicroEventExtractionOutputInvalid(
                "Extractor left a gap in OWNED_RANGE coverage."
            )
        previous_end = end_position
    if previous_end != owned_cue_count - 1:
        raise MicroEventExtractionOutputInvalid(
            "Extractor did not cover every owned cue exactly once."
        )


def _support_level_confidence(support_level: SupportLevel) -> float:
    if support_level == "DIRECT":
        return 0.9
    if support_level == "CONTEXTUAL":
        return 0.7
    return 0.4


def _normalized_topics(topics: list[str]) -> list[str]:
    normalized: list[str] = []
    for topic in topics:
        stripped = topic.strip()
        if stripped:
            normalized.append(stripped)
        if len(normalized) == 6:
            break
    return normalized or ["UNKNOWN"]


def _compact_prompt_text(text: str, *, limit: int = 1500) -> str | None:
    compacted = " ".join(text.split())
    if not compacted:
        return None
    if len(compacted) <= limit:
        return compacted
    return f"{compacted[: limit - 3]}..."


def _format_cue_block(
    cues: list[TranscriptCueRecord],
    all_cues: list[TranscriptCueRecord],
) -> str:
    if not cues:
        return "(none)"
    cue_gaps = _cue_gap_lookup(all_cues)
    return "\n".join(
        json.dumps(
            {
                "cue_id": cue.cue_id,
                "text": cue.text,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "duration_ms": cue.duration_ms,
                "gap_from_previous_ms": cue_gaps.get(cue.cue_id, (None, None))[0],
                "gap_to_next_ms": cue_gaps.get(cue.cue_id, (None, None))[1],
            },
            ensure_ascii=False,
        )
        for cue in cues
    )


def _cue_gap_lookup(
    cues: list[TranscriptCueRecord],
) -> dict[str, tuple[int | None, int | None]]:
    gaps: dict[str, tuple[int | None, int | None]] = {}
    for index, cue in enumerate(cues):
        previous_gap = None
        next_gap = None
        if index > 0:
            previous_gap = max(0, cue.start_ms - cues[index - 1].end_ms)
        if index + 1 < len(cues):
            next_gap = max(0, cues[index + 1].start_ms - cue.end_ms)
        gaps[cue.cue_id] = (previous_gap, next_gap)
    return gaps


def _domain_knowledge_fingerprint(
    entries: list[DomainKnowledgePromptEntryRecord],
) -> str:
    payload = [
        _domain_prompt_entry_json(entry)
        for entry in sorted(entries, key=lambda item: item.entry_id)
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _single_extract_request(
    request: MicroEventBatchExtractRequest,
) -> MicroEventExtractRequest:
    return MicroEventExtractRequest(
        retryFailed=request.retry_failed,
        regenerateSucceeded=request.regenerate_succeeded,
        windowMinutes=request.window_minutes,
        overlapMinutes=request.overlap_minutes,
        model=request.model,
        reasoningEffort=request.reasoning_effort,
        promptVersionId=request.prompt_version_id,
    )


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
    metadata: YouTubeTranscriptMetadataRecord,
    window_minutes: int,
    overlap_minutes: int,
    model: CodexModelChoice,
    reasoning_effort: ReasoningEffortChoice,
    domain_knowledge_fingerprint: str,
    prompt: ResolvedPrompt,
) -> str:
    payload = {
        "domainKnowledgeFingerprint": domain_knowledge_fingerprint,
        "model": model,
        "overlapMinutes": overlap_minutes,
        **_prompt_metadata_json(prompt),
        "reasoningEffort": reasoning_effort,
        "responseSha256": metadata.response_sha256,
        "taskVersion": MICRO_EVENT_EXTRACT_TASK_VERSION,
        "transcriptId": metadata.id,
        "videoId": video.id,
        "windowMinutes": window_minutes,
        "youtubeVideoId": video.youtube_video_id,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _task_input_json(
    execution_input: _ExtractionExecutionInput,
    *,
    input_hash: str,
    timeout_seconds: int,
) -> JsonObject:
    return {
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
        "timeoutSeconds": timeout_seconds,
    }


def _enqueue_response(
    request: MicroEventEnqueueRequest,
    counters: _EnqueueCounters,
    items: list[MicroEventEnqueueItemResponse],
) -> MicroEventEnqueueResponse:
    requested_count = min(
        request.limit,
        len(request.video_ids) if request.target == "selected_videos" else request.limit,
    )
    return MicroEventEnqueueResponse(
        requestedCount=requested_count,
        scannedCount=counters.scanned_count,
        enqueuedCount=counters.enqueued_count,
        alreadyPendingCount=counters.already_pending_count,
        alreadyRunningCount=counters.already_running_count,
        alreadySucceededCount=counters.already_succeeded_count,
        skippedFailedCount=counters.skipped_failed_count,
        ineligibleCount=counters.ineligible_count,
        items=items,
    )


def _enqueue_item_from_task(
    task: VideoTaskRecord,
    *,
    request: MicroEventEnqueueRequest,
    video: VideoRecord,
    status: str,
    reason: str,
    transcript_id: int | None,
) -> MicroEventEnqueueItemResponse:
    return _enqueue_item(
        video_id=video.id,
        youtube_video_id=video.youtube_video_id,
        task=task,
        status=status,
        reason=reason,
        request=request,
        transcript_id=transcript_id,
        error_type=task.error_type,
        error_message=task.error_message,
    )


def _enqueue_item(
    *,
    video_id: int,
    youtube_video_id: str | None,
    task: VideoTaskRecord | None,
    status: str,
    reason: str,
    request: MicroEventEnqueueRequest,
    transcript_id: int | None,
    error_type: str | None,
    error_message: str | None,
) -> MicroEventEnqueueItemResponse:
    return MicroEventEnqueueItemResponse(
        videoId=video_id,
        youtubeVideoId=youtube_video_id,
        videoTaskId=task.id if task is not None else None,
        status=status,
        reason=reason,
        model=request.model,
        reasoningEffort=request.reasoning_effort,
        transcriptId=transcript_id,
        errorType=error_type,
        errorMessage=error_message,
    )


def _attempt_output_json(
    execution_input: _ExtractionExecutionInput,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
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
    }


def _output_json(
    execution_input: _ExtractionExecutionInput,
    detail: MicroEventExtractionDetailRecord | None,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
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
    }


def _extract_response(
    video: VideoRecord,
    task: VideoTaskRecord,
    *,
    detail: MicroEventExtractionDetailRecord | None,
    status: str,
    reason: str,
    model: CodexModelChoice | None = None,
    reasoning_effort: ReasoningEffortChoice | None = None,
) -> MicroEventExtractResponse:
    output_json = task.output_json or {}
    window_count = (
        _window_count(detail)
        if detail is not None
        else _int_output(output_json, "windowCount")
    )
    first_cue_id = (
        _first_cue_id(detail)
        if detail is not None
        else _str_output(output_json, "firstCueId")
    )
    last_cue_id = (
        _last_cue_id(detail)
        if detail is not None
        else _str_output(output_json, "lastCueId")
    )
    model = model or _model_output(output_json)
    reasoning_effort = reasoning_effort or _reasoning_effort_output(output_json)
    return MicroEventExtractResponse(
        videoId=video.id,
        youtubeVideoId=video.youtube_video_id,
        videoTaskId=task.id,
        status=status,
        reason=reason,
        model=model,
        reasoningEffort=reasoning_effort,
        jobId=task.job_id,
        jobAttemptId=task.job_attempt_id,
        transcriptId=task.output_transcript_id,
        windowCount=window_count,
        microEventCount=(
            _micro_event_count(detail)
            if detail is not None
            else _int_output(output_json, "microEventCount")
        ),
        asrCorrectionCandidateCount=(
            _asr_count(detail)
            if detail is not None
            else _int_output(output_json, "asrCorrectionCandidateCount")
        ),
        firstCueId=first_cue_id,
        lastCueId=last_cue_id,
        errorType=task.error_type,
        errorMessage=task.error_message,
    )


def _detail_response(
    detail: MicroEventExtractionDetailRecord,
) -> MicroEventExtractionDetailResponse:
    return MicroEventExtractionDetailResponse(
        videoTaskId=detail.video_task_id,
        videoId=detail.video_id,
        youtubeVideoId=detail.youtube_video_id,
        model=_model_output(detail.output_json or {}),
        reasoningEffort=_reasoning_effort_output(detail.output_json or {}),
        transcriptId=detail.transcript_id,
        status=detail.status,
        jobId=detail.job_id,
        jobAttemptId=detail.job_attempt_id,
        windowCount=_window_count(detail),
        microEventCount=_micro_event_count(detail),
        asrCorrectionCandidateCount=_asr_count(detail),
        firstCueId=_first_cue_id(detail),
        lastCueId=_last_cue_id(detail),
        outputJson=detail.output_json,
        errorType=detail.error_type,
        errorMessage=detail.error_message,
        startedAt=detail.started_at,
        completedAt=detail.completed_at,
        createdAt=detail.created_at,
        updatedAt=detail.updated_at,
        windows=[
            {
                "windowId": window.id,
                "windowIndex": window.window_index,
                "startCueId": window.start_cue_id,
                "endCueId": window.end_cue_id,
                "cueCount": window.cue_count,
                "status": window.status,
                "carryOutUnfinished": window.carry_out_unfinished,
                "codexThreadId": window.codex_thread_id,
                "codexTurnId": window.codex_turn_id,
                "rawResponseText": window.raw_response_text,
                "parsedResponseJson": window.parsed_response_json,
                "validationError": window.validation_error,
                "sourceJobId": window.source_job_id,
                "sourceJobAttemptId": window.source_job_attempt_id,
                "createdAt": window.created_at,
                "updatedAt": window.updated_at,
                "microEvents": [
                    {
                        "microEventCandidateId": candidate.id,
                        "candidateIndex": candidate.candidate_index,
                        "activity": candidate.activity,
                        "event": candidate.event,
                        "startCueId": candidate.start_cue_id,
                        "endCueId": candidate.end_cue_id,
                        "evidenceCueIds": candidate.evidence_cue_ids,
                        "boundaryBefore": candidate.boundary_before,
                        "boundaryAfter": candidate.boundary_after,
                        "confidence": candidate.confidence,
                        "programMode": candidate.program_mode,
                        "contentKind": candidate.content_kind,
                        "topics": candidate.topics,
                        "relationToPrevious": candidate.relation_to_previous,
                        "continuesToNext": candidate.continues_to_next,
                        "supportLevel": candidate.support_level,
                        "createdAt": candidate.created_at,
                        "updatedAt": candidate.updated_at,
                    }
                    for candidate in window.micro_events
                ],
                "excludedRanges": [
                    {
                        "excludedRangeId": excluded_range.id,
                        "rangeIndex": excluded_range.range_index,
                        "startCueId": excluded_range.start_cue_id,
                        "endCueId": excluded_range.end_cue_id,
                        "reason": excluded_range.reason,
                        "createdAt": excluded_range.created_at,
                        "updatedAt": excluded_range.updated_at,
                    }
                    for excluded_range in window.excluded_ranges
                ],
                "asrCorrectionCandidates": [
                    {
                        "asrCorrectionCandidateId": candidate.id,
                        "candidateIndex": candidate.candidate_index,
                        "original": candidate.original,
                        "suggested": candidate.suggested,
                        "correctionType": candidate.correction_type,
                        "applyScope": candidate.apply_scope,
                        "confidence": candidate.confidence,
                        "createdAt": candidate.created_at,
                        "updatedAt": candidate.updated_at,
                    }
                    for candidate in window.asr_correction_candidates
                ],
            }
            for window in detail.windows
        ],
    )


def _window_count(detail: MicroEventExtractionDetailRecord | None) -> int:
    return len(detail.windows) if detail is not None else 0


def _micro_event_count(detail: MicroEventExtractionDetailRecord | None) -> int:
    if detail is None:
        return 0
    return sum(len(window.micro_events) for window in detail.windows)


def _excluded_range_count(detail: MicroEventExtractionDetailRecord | None) -> int:
    if detail is None:
        return 0
    return sum(len(window.excluded_ranges) for window in detail.windows)


def _asr_count(detail: MicroEventExtractionDetailRecord | None) -> int:
    if detail is None:
        return 0
    return sum(len(window.asr_correction_candidates) for window in detail.windows)


def _first_cue_id(detail: MicroEventExtractionDetailRecord | None) -> str | None:
    if detail is None or not detail.windows:
        return None
    return detail.windows[0].start_cue_id


def _last_cue_id(detail: MicroEventExtractionDetailRecord | None) -> str | None:
    if detail is None or not detail.windows:
        return None
    return detail.windows[-1].end_cue_id


def _int_output(output_json: JsonObject, key: str) -> int | None:
    value = output_json.get(key)
    return value if isinstance(value, int) else None


def _str_output(output_json: JsonObject, key: str) -> str | None:
    value = output_json.get(key)
    return value if isinstance(value, str) else None


def _model_output(output_json: JsonObject) -> CodexModelChoice | None:
    value = _str_output(output_json, "model")
    if value in {"gpt-5.5", "gpt-5.4", "gpt-5.4-mini"}:
        return cast(CodexModelChoice, value)
    return None


def _reasoning_effort_output(output_json: JsonObject) -> ReasoningEffortChoice | None:
    value = _str_output(output_json, "reasoningEffort")
    if value in {"low", "medium", "high", "xhigh"}:
        return cast(ReasoningEffortChoice, value)
    return None


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise VideoTaskRetryNotAllowed(f"Pipeline job input is missing integer '{key}'.")
    return value
