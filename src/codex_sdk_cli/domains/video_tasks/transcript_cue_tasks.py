from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import cast

from codex_sdk_cli.domains.channels.exceptions import ChannelNotFound
from codex_sdk_cli.domains.channels.ports import ChannelRepositoryPort
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
from codex_sdk_cli.domains.transcript_cues.schemas import TranscriptCueGenerateResponse
from codex_sdk_cli.domains.transcript_cues.use_cases import (
    GenerateTranscriptCuesUseCase,
    TranscriptCueGenerationResult,
)
from codex_sdk_cli.domains.videos.ports import VideoRecord, VideoRepositoryPort
from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    YouTubeTranscriptMetadataNotFound,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptRepositoryPort,
)

from .constants import (
    TRANSCRIPT_COLLECT_TASK_NAME,
    TRANSCRIPT_CUE_GENERATE_TASK_NAME,
    TRANSCRIPT_CUE_GENERATE_TASK_VERSION,
    TRANSCRIPT_CUE_GENERATE_WORKER_ID,
)
from .exceptions import VideoTaskNotFound, VideoTaskRetryNotAllowed
from .ports import (
    VideoTaskCreate,
    VideoTaskRecord,
    VideoTaskRepositoryPort,
    VideoTaskWithVideoRecord,
)
from .schemas import (
    GenerateAllTranscriptCueTasksResponse,
    GenerateChannelTranscriptCueTasksResponse,
    GenerateTranscriptCueTasksRequest,
    TranscriptCueTaskItemResponse,
    TranscriptCueTaskItemStatus,
)


@dataclass(frozen=True, slots=True)
class _CueTaskExecutionInput:
    video_id: int
    youtube_video_id: str
    metadata: YouTubeTranscriptMetadataRecord
    parent_job_id: int | None
    retry_failed: bool
    regenerate_succeeded: bool
    actor_type: OperationEventActorType


@dataclass(frozen=True, slots=True)
class _CueResponseCounts:
    requested_count: int
    succeeded_count: int
    skipped_count: int
    failed_count: int
    timeout_count: int


class GenerateTranscriptCueTasksUseCase:
    def __init__(
        self,
        *,
        channels: ChannelRepositoryPort,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        transcripts: YouTubeTranscriptRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        generate_cues: GenerateTranscriptCuesUseCase,
        timeout_seconds: int,
        concurrency_limit: int,
        events: OperationEventRecorderPort,
    ) -> None:
        self._channels = channels
        self._videos = videos
        self._video_tasks = video_tasks
        self._transcripts = transcripts
        self._pipeline_jobs = pipeline_jobs
        self._generate_cues = generate_cues
        self._timeout_seconds = timeout_seconds
        self._concurrency_limit = concurrency_limit
        self._events = events

    async def execute(
        self,
        channel_id: int,
        request: GenerateTranscriptCueTasksRequest,
    ) -> GenerateChannelTranscriptCueTasksResponse:
        if await self._channels.get_channel(channel_id) is None:
            raise ChannelNotFound("Channel not found.")
        candidates = await self._video_tasks.list_latest_succeeded_tasks(
            task_name=TRANSCRIPT_COLLECT_TASK_NAME,
            channel_id=channel_id,
            limit=request.limit,
        )
        items = await self._process_candidates(
            candidates,
            retry_failed=request.retry_failed,
            regenerate_succeeded=request.regenerate_succeeded,
            parent_job_id=None,
        )
        counts = _cue_response_counts(items)
        return GenerateChannelTranscriptCueTasksResponse(
            channelId=channel_id,
            requestedCount=counts.requested_count,
            succeededCount=counts.succeeded_count,
            skippedCount=counts.skipped_count,
            failedCount=counts.failed_count,
            timeoutCount=counts.timeout_count,
            items=items,
        )

    async def execute_all(
        self,
        request: GenerateTranscriptCueTasksRequest,
    ) -> GenerateAllTranscriptCueTasksResponse:
        candidates = await self._video_tasks.list_latest_succeeded_tasks(
            task_name=TRANSCRIPT_COLLECT_TASK_NAME,
            channel_id=None,
            limit=request.limit,
        )
        items = await self._process_candidates(
            candidates,
            retry_failed=request.retry_failed,
            regenerate_succeeded=request.regenerate_succeeded,
            parent_job_id=None,
        )
        counts = _cue_response_counts(items)
        return GenerateAllTranscriptCueTasksResponse(
            requestedCount=counts.requested_count,
            succeededCount=counts.succeeded_count,
            skippedCount=counts.skipped_count,
            failedCount=counts.failed_count,
            timeoutCount=counts.timeout_count,
            items=items,
        )

    async def execute_for_transcript(
        self,
        transcript_id: int,
        *,
        parent_job_id: int | None = None,
        actor_type: OperationEventActorType = "manual_api",
    ) -> TranscriptCueGenerateResponse:
        metadata = await self._get_metadata(transcript_id)
        video = await self._videos.get_video_by_youtube_video_id(metadata.video_id)
        if video is None:
            return await self._generate_cues.execute(
                transcript_id,
                parent_job_id=parent_job_id,
                actor_type=actor_type,
            )
        item = await self.execute_for_video(
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
            metadata=metadata,
            parent_job_id=parent_job_id,
            retry_failed=True,
            regenerate_succeeded=True,
            actor_type=actor_type,
        )
        if item.status != "succeeded" or item.job_id is None or item.job_attempt_id is None:
            raise VideoTaskRetryNotAllowed(
                item.error_message or f"Transcript cue task was {item.status}."
            )
        task = (
            await self._video_tasks.get_task(item.video_task_id)
            if item.video_task_id is not None
            else None
        )
        return TranscriptCueGenerateResponse(
            transcriptId=metadata.id,
            youtubeVideoId=metadata.video_id,
            jobId=item.job_id,
            jobAttemptId=item.job_attempt_id,
            cueCount=item.cue_count or 0,
            firstCueId=_str_task_output(task, "firstCueId"),
            lastCueId=_str_task_output(task, "lastCueId"),
        )

    async def execute_for_video(
        self,
        *,
        video_id: int,
        youtube_video_id: str,
        metadata: YouTubeTranscriptMetadataRecord,
        parent_job_id: int | None,
        retry_failed: bool,
        regenerate_succeeded: bool,
        actor_type: OperationEventActorType = "manual_api",
    ) -> TranscriptCueTaskItemResponse:
        input_hash = _cue_task_input_hash(
            video_id=video_id,
            youtube_video_id=youtube_video_id,
            transcript_id=metadata.id,
            response_sha256=metadata.response_sha256,
        )
        task = await self._video_tasks.get_or_create_task(
            VideoTaskCreate(
                video_id=video_id,
                task_name=TRANSCRIPT_CUE_GENERATE_TASK_NAME,
                task_version=TRANSCRIPT_CUE_GENERATE_TASK_VERSION,
                input_hash=input_hash,
                timeout_seconds=self._timeout_seconds,
            )
        )
        execution_input = _CueTaskExecutionInput(
            video_id=video_id,
            youtube_video_id=youtube_video_id,
            metadata=metadata,
            parent_job_id=parent_job_id,
            retry_failed=retry_failed,
            regenerate_succeeded=regenerate_succeeded,
            actor_type=actor_type,
        )
        await self._record_task_event(
            "transcript_cue_generate.task_selected",
            "info",
            "Transcript cue generation task was selected.",
            task=task,
            execution_input=execution_input,
            metadata_json={
                "taskStatus": task.status,
                "retryFailed": retry_failed,
                "regenerateSucceeded": regenerate_succeeded,
            },
        )
        return await self._process_task(task, execution_input, input_hash)

    async def execute_retry_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        task_id = _required_int(job.input_json, "videoTaskId")
        task = await self._video_tasks.get_task(task_id)
        if task is None:
            raise VideoTaskNotFound("Video task not found.")
        if task.status not in {"failed", "timed_out"}:
            raise VideoTaskRetryNotAllowed(
                "Only failed or timed out transcript cue tasks can be retried."
            )
        running_count = await self._video_tasks.count_running(
            task_name=TRANSCRIPT_CUE_GENERATE_TASK_NAME
        )
        if running_count >= self._concurrency_limit:
            raise VideoTaskRetryNotAllowed(
                "Transcript cue generation is already running."
            )
        metadata = await self._get_metadata(_required_int(job.input_json, "transcriptId"))
        timeout_seconds = _required_int(job.input_json, "timeoutSeconds")
        task = await self._video_tasks.mark_task_running(
            task.id,
            worker_id=TRANSCRIPT_CUE_GENERATE_WORKER_ID,
            timeout_seconds=timeout_seconds,
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        execution_input = _CueTaskExecutionInput(
            video_id=_required_int(job.input_json, "videoId"),
            youtube_video_id=_required_str(job.input_json, "youtubeVideoId"),
            metadata=metadata,
            parent_job_id=job.parent_job_id,
            retry_failed=True,
            regenerate_succeeded=True,
            actor_type="retry_executor",
        )
        await self._record_task_event(
            "transcript_cue_generate.task_running",
            "info",
            "Transcript cue generation task started running.",
            task=task,
            execution_input=execution_input,
            metadata_json={"attemptId": attempt.id},
        )
        result = await self._execute_job_attempt(
            job,
            attempt,
            task=task,
            execution_input=execution_input,
            timeout_seconds=timeout_seconds,
        )
        return result.model_dump(by_alias=True)

    async def _process_candidates(
        self,
        candidates: list[VideoTaskWithVideoRecord],
        *,
        retry_failed: bool,
        regenerate_succeeded: bool,
        parent_job_id: int | None,
    ) -> list[TranscriptCueTaskItemResponse]:
        items: list[TranscriptCueTaskItemResponse] = []
        for candidate in candidates:
            transcript_id = candidate.task.output_transcript_id
            if transcript_id is None:
                items.append(
                    _missing_cue_item_response(
                        candidate.video,
                        status="skipped",
                        reason="missing_transcript",
                    )
                )
                continue
            metadata = await self._transcripts.get_transcript_metadata(transcript_id)
            if metadata is None:
                items.append(
                    _missing_cue_item_response(
                        candidate.video,
                        status="skipped",
                        reason="missing_transcript",
                        transcript_id=transcript_id,
                    )
                )
                continue
            items.append(
                await self.execute_for_video(
                    video_id=candidate.video.id,
                    youtube_video_id=candidate.video.youtube_video_id,
                    metadata=metadata,
                    parent_job_id=parent_job_id,
                    retry_failed=retry_failed,
                    regenerate_succeeded=regenerate_succeeded,
                )
            )
        return items

    async def _process_task(
        self,
        task: VideoTaskRecord,
        execution_input: _CueTaskExecutionInput,
        input_hash: str,
    ) -> TranscriptCueTaskItemResponse:
        if task.status == "succeeded" and not execution_input.regenerate_succeeded:
            await self._record_task_event(
                "transcript_cue_generate.task_succeeded",
                "info",
                "Transcript cue generation task was already succeeded.",
                task=task,
                execution_input=execution_input,
                reason="already_succeeded",
            )
            return _cue_item_response(
                task=task,
                execution_input=execution_input,
                status="succeeded",
                reason="already_succeeded",
            )
        if task.status == "running":
            await self._record_task_event(
                "transcript_cue_generate.task_skipped",
                "warning",
                "Transcript cue generation task was skipped because it is already running.",
                task=task,
                execution_input=execution_input,
                reason="already_running",
            )
            return _cue_item_response(
                task=task,
                execution_input=execution_input,
                status="skipped",
                reason="already_running",
            )
        if task.status in {"failed", "timed_out"} and not execution_input.retry_failed:
            await self._record_task_event(
                "transcript_cue_generate.task_skipped",
                "info",
                "Transcript cue generation task was skipped because retryFailed is false.",
                task=task,
                execution_input=execution_input,
                reason=f"previously_{task.status}",
            )
            return _cue_item_response(
                task=task,
                execution_input=execution_input,
                status="skipped",
                reason=f"previously_{task.status}",
            )
        if task.status in {"skipped", "canceled", "no_transcript"}:
            await self._record_task_event(
                "transcript_cue_generate.task_skipped",
                "warning",
                "Transcript cue generation task was skipped because its status is not retryable.",
                task=task,
                execution_input=execution_input,
                reason="not_retryable",
            )
            return _cue_item_response(
                task=task,
                execution_input=execution_input,
                status="skipped",
                reason="not_retryable",
            )
        running_count = await self._video_tasks.count_running(
            task_name=TRANSCRIPT_CUE_GENERATE_TASK_NAME
        )
        if running_count >= self._concurrency_limit:
            await self._record_task_event(
                "transcript_cue_generate.task_skipped",
                "warning",
                "Transcript cue generation task was skipped by concurrency limit.",
                task=task,
                execution_input=execution_input,
                reason="concurrency_limit",
                metadata_json={"runningCount": running_count},
            )
            return _cue_item_response(
                task=task,
                execution_input=execution_input,
                status="skipped",
                reason="concurrency_limit",
            )
        return await self._execute_task(task, execution_input, input_hash)

    async def _execute_task(
        self,
        task: VideoTaskRecord,
        execution_input: _CueTaskExecutionInput,
        input_hash: str,
    ) -> TranscriptCueTaskItemResponse:
        input_json: JsonObject = {
            "videoTaskId": task.id,
            "videoId": execution_input.video_id,
            "youtubeVideoId": execution_input.youtube_video_id,
            "transcriptId": execution_input.metadata.id,
            "responseSha256": execution_input.metadata.response_sha256,
            "taskVersion": TRANSCRIPT_CUE_GENERATE_TASK_VERSION,
            "inputHash": input_hash,
            "timeoutSeconds": self._timeout_seconds,
        }
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step=TRANSCRIPT_CUE_GENERATE_TASK_NAME,
                status="running",
                subject_type="video",
                subject_id=execution_input.video_id,
                external_key=execution_input.youtube_video_id,
                input_json=input_json,
                input_hash=input_hash,
                parent_job_id=execution_input.parent_job_id,
            )
        )
        attempt = await self._pipeline_jobs.create_attempt(job_id=job.id)
        task = await self._video_tasks.mark_task_running(
            task.id,
            worker_id=TRANSCRIPT_CUE_GENERATE_WORKER_ID,
            timeout_seconds=self._timeout_seconds,
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        await self._record_task_event(
            "transcript_cue_generate.task_running",
            "info",
            "Transcript cue generation task started running.",
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
        execution_input: _CueTaskExecutionInput,
        timeout_seconds: int,
    ) -> TranscriptCueTaskItemResponse:
        try:
            generated = await asyncio.wait_for(
                self._generate_cues.execute_job_attempt(
                    job,
                    attempt,
                    metadata=execution_input.metadata,
                    actor_type=execution_input.actor_type,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            message = f"Transcript cue generation exceeded {timeout_seconds} seconds."
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type="TimeoutError",
                error_message=message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            updated = await self._video_tasks.mark_task_timed_out(
                task.id,
                error_message=message,
                output_json={"jobId": job.id, "jobAttemptId": attempt.id},
            )
            await self._record_task_event(
                "transcript_cue_generate.task_timed_out",
                "error",
                "Transcript cue generation task timed out.",
                task=updated,
                execution_input=execution_input,
                reason="timeout",
                error_type="TimeoutError",
                error_message=message,
                metadata_json={"timeoutSeconds": timeout_seconds},
            )
            return _cue_item_response(
                task=updated,
                execution_input=execution_input,
                status="timed_out",
                reason="timeout",
            )
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            updated = await self._video_tasks.mark_task_failed(
                task.id,
                error_type=error_type,
                error_message=error_message,
                output_json={"jobId": job.id, "jobAttemptId": attempt.id},
            )
            await self._record_task_event(
                "transcript_cue_generate.task_failed",
                "error",
                "Transcript cue generation task failed.",
                task=updated,
                execution_input=execution_input,
                reason="error",
                error_type=error_type,
                error_message=error_message,
            )
            return _cue_item_response(
                task=updated,
                execution_input=execution_input,
                status="failed",
                reason="error",
            )
        return await self._mark_task_succeeded(
            task,
            execution_input=execution_input,
            generated=generated,
        )

    async def _mark_task_succeeded(
        self,
        task: VideoTaskRecord,
        *,
        execution_input: _CueTaskExecutionInput,
        generated: TranscriptCueGenerationResult,
    ) -> TranscriptCueTaskItemResponse:
        output_json = generated.response.model_dump(by_alias=True)
        updated = await self._video_tasks.mark_task_succeeded(
            task.id,
            output_transcript_id=execution_input.metadata.id,
            output_json=cast(JsonObject, output_json),
        )
        await self._record_task_event(
            "transcript_cue_generate.task_succeeded",
            "info",
            "Transcript cue generation task succeeded.",
            task=updated,
            execution_input=execution_input,
            reason="generated",
            metadata_json=cast(JsonObject, output_json),
        )
        return _cue_item_response(
            task=updated,
            execution_input=execution_input,
            status="succeeded",
            reason="generated",
        )

    async def _get_metadata(
        self,
        transcript_id: int,
    ) -> YouTubeTranscriptMetadataRecord:
        metadata = await self._transcripts.get_transcript_metadata(transcript_id)
        if metadata is None:
            raise YouTubeTranscriptMetadataNotFound("Transcript metadata not found.")
        return metadata

    async def _record_task_event(
        self,
        event_type: str,
        severity: OperationEventSeverity,
        message: str,
        *,
        task: VideoTaskRecord,
        execution_input: _CueTaskExecutionInput,
        reason: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata_json: JsonObject | None = None,
    ) -> None:
        metadata: JsonObject = dict(metadata_json or {})
        if reason is not None:
            metadata["reason"] = reason
        metadata["transcriptId"] = execution_input.metadata.id
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity=severity,
                message=message,
                actor_type=execution_input.actor_type,
                source="video_tasks.transcript_cue_generate",
                job_id=task.job_id,
                job_attempt_id=task.job_attempt_id,
                video_task_id=task.id,
                video_id=execution_input.video_id,
                subject_type="video",
                subject_id=execution_input.video_id,
                external_key=execution_input.youtube_video_id,
                error_type=error_type,
                error_message=error_message,
                metadata_json=metadata,
            ),
        )


def _cue_response_counts(items: list[TranscriptCueTaskItemResponse]) -> _CueResponseCounts:
    return _CueResponseCounts(
        requested_count=len(items),
        succeeded_count=sum(item.status == "succeeded" for item in items),
        skipped_count=sum(item.status == "skipped" for item in items),
        failed_count=sum(item.status == "failed" for item in items),
        timeout_count=sum(item.status == "timed_out" for item in items),
    )


def _cue_item_response(
    *,
    task: VideoTaskRecord,
    execution_input: _CueTaskExecutionInput,
    status: TranscriptCueTaskItemStatus,
    reason: str,
) -> TranscriptCueTaskItemResponse:
    return TranscriptCueTaskItemResponse(
        videoId=execution_input.video_id,
        youtubeVideoId=execution_input.youtube_video_id,
        videoTaskId=task.id,
        status=status,
        reason=reason,
        jobId=task.job_id,
        jobAttemptId=task.job_attempt_id,
        transcriptId=execution_input.metadata.id,
        cueCount=_int_output(task, "cueCount"),
        errorType=task.error_type,
        errorMessage=task.error_message,
    )


def _missing_cue_item_response(
    video: VideoRecord,
    *,
    status: TranscriptCueTaskItemStatus,
    reason: str,
    transcript_id: int | None = None,
) -> TranscriptCueTaskItemResponse:
    return TranscriptCueTaskItemResponse(
        videoId=video.id,
        youtubeVideoId=video.youtube_video_id,
        videoTaskId=None,
        status=status,
        reason=reason,
        jobId=None,
        jobAttemptId=None,
        transcriptId=transcript_id,
        cueCount=None,
        errorType=None,
        errorMessage=None,
    )


def _cue_task_input_hash(
    *,
    video_id: int,
    youtube_video_id: str,
    transcript_id: int,
    response_sha256: str,
) -> str:
    payload = {
        "responseSha256": response_sha256,
        "taskVersion": TRANSCRIPT_CUE_GENERATE_TASK_VERSION,
        "transcriptId": transcript_id,
        "videoId": video_id,
        "youtubeVideoId": youtube_video_id,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _int_output(task: VideoTaskRecord, key: str) -> int | None:
    value = _output_value(task, key)
    return value if isinstance(value, int) else None


def _output_value(task: VideoTaskRecord, key: str) -> object | None:
    if task.output_json is None:
        return None
    return task.output_json.get(key)


def _str_task_output(task: VideoTaskRecord | None, key: str) -> str | None:
    if task is None:
        return None
    value = _output_value(task, key)
    return value if isinstance(value, str) else None


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise VideoTaskRetryNotAllowed(f"Pipeline job input is missing integer '{key}'.")
    return value


def _required_str(input_json: JsonObject, key: str) -> str:
    value = input_json.get(key)
    if not isinstance(value, str):
        raise VideoTaskRetryNotAllowed(f"Pipeline job input is missing string '{key}'.")
    return value
