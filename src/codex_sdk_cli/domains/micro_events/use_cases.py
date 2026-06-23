from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import cast

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

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
    MICRO_EVENT_EXTRACT_PROMPT_VERSION,
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
    Activity,
    ApplyScope,
    AsrCorrectionCandidateCreate,
    CorrectionType,
    MicroEventCandidateCreate,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionRepositoryPort,
    MicroEventExtractionRequest,
    MicroEventExtractionResult,
    MicroEventExtractionWindowCreate,
    MicroEventExtractorPort,
)
from .schemas import (
    MicroEventExtractionDetailResponse,
    MicroEventExtractRequest,
    MicroEventExtractResponse,
)

PROMPT_HEADER = """너는 장시간 라이브 방송 VOD 자막을 분석하는 로컬 사건 추출기다.

너의 작업은 입력된 자막 window 안에서 후속 병합 단계에 사용할
micro_event 후보와 ASR 보정 후보를 추출하는 것이다.
최종 타임라인, 최종 챕터, 최종 요약을 만들지 않는다.

출력은 반드시 JSON 객체 하나만 반환한다. 마크다운, 설명문, 주석, 코드블록을 출력하지 않는다.
시간을 직접 출력하지 말고, cue_id만 사용한다.
start_cue_id, end_cue_id, evidence_cue_ids에는 반드시 입력에 존재하는 cue_id만 사용한다.
입력에 없는 사실을 추가하지 않는다.
event는 1문장으로 관찰 가능한 사건만 쓴다.
채팅의 농담, 질문, 과장된 주장을 스트리머가 인정한 사실처럼 쓰지 않는다.
게임 대사는 스트리머의 실제 발언이나 사실 주장으로 취급하지 않는다.
짧은 곁가지, 단발 채팅 답변, 30초 이하의 짧은 농담은 독립 micro_event로 만들지 않는다.
판단이 애매하면 confidence를 낮춘다.
원본 자막을 직접 수정하지 않는다. ASR 오류 후보는 asr_correction_candidates에만 기록한다.

activity는 다음 값 중 하나만 사용한다.
PRE_ROLL, OPENING, JUST_CHATTING, ANNOUNCEMENT, COMMUNITY_REVIEW, MEDIA_REVIEW,
GAME_SETUP, GAMEPLAY, BREAK, POST_GAME, CLOSING, UNKNOWN

correction_type은 다음 값 중 하나만 사용한다.
PROPER_NOUN, GAME_TITLE, CONTENT_TITLE, COMMON_WORD, FOOD, PLACE, STREAM_TERM,
CONTEXTUAL_TERM, UNCERTAIN

apply_scope는 다음 값 중 하나만 사용한다.
NONE, SEARCH_ONLY, SEARCH_AND_SUMMARY, DISPLAY_ALLOWED

응답 스키마:
{
  "micro_events": [
    {
      "activity": "JUST_CHATTING",
      "event": "스트리머가 방송 주제를 설명한다.",
      "start_cue_id": "tr1-c000001",
      "end_cue_id": "tr1-c000010",
      "evidence_cue_ids": ["tr1-c000001"],
      "boundary_before": true,
      "boundary_after": false,
      "confidence": 0.85
    }
  ],
  "asr_correction_candidates": [
    {
      "original": "원문 단어",
      "suggested": "교정 후보",
      "correction_type": "COMMON_WORD",
      "apply_scope": "SEARCH_ONLY",
      "evidence_cue_ids": ["tr1-c000002"],
      "confidence": 0.8
    }
  ],
  "carry_out": {"unfinished": false}
}
"""


@dataclass(frozen=True, slots=True)
class _CueWindow:
    window_index: int
    cues: list[TranscriptCueRecord]


@dataclass(frozen=True, slots=True)
class _ExtractionExecutionInput:
    video: VideoRecord
    metadata: YouTubeTranscriptMetadataRecord
    cues: list[TranscriptCueRecord]
    window_minutes: int
    overlap_minutes: int
    actor_type: OperationEventActorType


class ExtractVideoMicroEventsUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        transcripts: YouTubeTranscriptRepositoryPort,
        transcript_cues: TranscriptCueRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        micro_events: MicroEventExtractionRepositoryPort,
        extractor: MicroEventExtractorPort,
        timeout_seconds: int,
        concurrency_limit: int,
        model: str | None,
        events: OperationEventRecorderPort,
    ) -> None:
        self._videos = videos
        self._video_tasks = video_tasks
        self._transcripts = transcripts
        self._transcript_cues = transcript_cues
        self._pipeline_jobs = pipeline_jobs
        self._micro_events = micro_events
        self._extractor = extractor
        self._timeout_seconds = timeout_seconds
        self._concurrency_limit = concurrency_limit
        self._model = model
        self._events = events

    async def execute(
        self,
        video_id: int,
        request: MicroEventExtractRequest,
    ) -> MicroEventExtractResponse:
        video, metadata, cues = await self._load_inputs(video_id)
        input_hash = _task_input_hash(
            video=video,
            metadata=metadata,
            window_minutes=request.window_minutes,
            overlap_minutes=request.overlap_minutes,
            model=self._model,
        )
        task = await self._video_tasks.get_or_create_task(
            VideoTaskCreate(
                video_id=video.id,
                task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
                task_version=MICRO_EVENT_EXTRACT_TASK_VERSION,
                input_hash=input_hash,
                timeout_seconds=self._timeout_seconds,
            )
        )
        execution_input = _ExtractionExecutionInput(
            video=video,
            metadata=metadata,
            cues=cues,
            window_minutes=request.window_minutes,
            overlap_minutes=request.overlap_minutes,
            actor_type="manual_api",
        )
        await self._record_task_event(
            "micro_event_extract.task_selected",
            "info",
            "Micro-event extraction task was selected.",
            task=task,
            execution_input=execution_input,
            metadata_json={
                "taskStatus": task.status,
                "retryFailed": request.retry_failed,
                "regenerateSucceeded": request.regenerate_succeeded,
            },
        )
        return await self._process_task(
            task,
            execution_input,
            input_hash,
            retry_failed=request.retry_failed,
            regenerate_succeeded=request.regenerate_succeeded,
        )

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
        ) >= self._concurrency_limit:
            raise VideoTaskRetryNotAllowed("Micro-event extraction is already running.")

        video, metadata, cues = await self._load_inputs(_required_int(job.input_json, "videoId"))
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
            actor_type="retry_executor",
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
            )
        if task.status == "running":
            return _extract_response(
                execution_input.video,
                task,
                detail=None,
                status="skipped",
                reason="already_running",
            )
        if task.status in {"failed", "timed_out"} and not retry_failed:
            return _extract_response(
                execution_input.video,
                task,
                detail=None,
                status="skipped",
                reason=f"previously_{task.status}",
            )
        if task.status in {"skipped", "canceled", "no_transcript"}:
            return _extract_response(
                execution_input.video,
                task,
                detail=None,
                status="skipped",
                reason="not_retryable",
            )
        running_count = await self._video_tasks.count_running(
            task_name=MICRO_EVENT_EXTRACT_TASK_NAME
        )
        if running_count >= self._concurrency_limit:
            return _extract_response(
                execution_input.video,
                task,
                detail=None,
                status="skipped",
                reason="concurrency_limit",
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
            "promptVersion": MICRO_EVENT_EXTRACT_PROMPT_VERSION,
            "inputHash": input_hash,
            "windowMinutes": execution_input.window_minutes,
            "overlapMinutes": execution_input.overlap_minutes,
            "model": self._model,
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
        await self._micro_events.delete_extraction(task.id)
        try:
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
        )

    async def _extract_windows(
        self,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        execution_input: _ExtractionExecutionInput,
    ) -> list[MicroEventExtractionWindowCreate]:
        created_windows: list[MicroEventExtractionWindowCreate] = []
        cue_windows = _cue_windows(
            execution_input.cues,
            window_minutes=execution_input.window_minutes,
            overlap_minutes=execution_input.overlap_minutes,
        )
        for cue_window in cue_windows:
            prompt = _window_prompt(execution_input, cue_window)
            result = await self._extractor.extract_window(
                MicroEventExtractionRequest(prompt=prompt)
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
            except MicroEventExtractionOutputInvalid as exc:
                failed_window = _failed_window(
                    task=task,
                    job=job,
                    attempt=attempt,
                    execution_input=execution_input,
                    cue_window=cue_window,
                    result=result,
                    validation_error=str(exc),
                )
                await self._micro_events.replace_extraction(
                    task.id,
                    [*created_windows, failed_window],
                )
                raise
            created_windows.append(window)
        return created_windows

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


class _CarryOutOutput(BaseModel):
    unfinished: bool = False

    model_config = ConfigDict(extra="forbid")


class _MicroEventOutput(BaseModel):
    activity: Activity
    event: str = Field(min_length=1)
    start_cue_id: str
    end_cue_id: str
    evidence_cue_ids: list[str]
    boundary_before: bool
    boundary_after: bool
    confidence: float = Field(ge=0, le=1)

    model_config = ConfigDict(extra="forbid")


class _AsrCorrectionOutput(BaseModel):
    original: str = Field(min_length=1)
    suggested: str = Field(min_length=1)
    correction_type: CorrectionType
    apply_scope: ApplyScope
    evidence_cue_ids: list[str]
    confidence: float = Field(ge=0, le=1)

    model_config = ConfigDict(extra="forbid")


class _ExtractorOutput(BaseModel):
    micro_events: list[_MicroEventOutput] = Field(
        default_factory=list,
        validation_alias=AliasChoices("micro_events", "micro_event_candidates"),
    )
    asr_correction_candidates: list[_AsrCorrectionOutput] = Field(default_factory=list)
    carry_out: _CarryOutOutput = Field(default_factory=_CarryOutOutput)

    model_config = ConfigDict(extra="forbid")


def _cue_windows(
    cues: list[TranscriptCueRecord],
    *,
    window_minutes: int,
    overlap_minutes: int,
) -> list[_CueWindow]:
    window_ms = window_minutes * 60_000
    step_ms = (window_minutes - overlap_minutes) * 60_000
    first_start_ms = cues[0].start_ms
    last_end_ms = cues[-1].end_ms
    windows: list[_CueWindow] = []
    window_start_ms = first_start_ms
    window_index = 1
    while window_start_ms <= last_end_ms:
        window_end_ms = window_start_ms + window_ms
        window_cues = [
            cue
            for cue in cues
            if cue.end_ms > window_start_ms and cue.start_ms < window_end_ms
        ]
        if window_cues:
            windows.append(_CueWindow(window_index=window_index, cues=window_cues))
            window_index += 1
        if window_end_ms >= last_end_ms:
            break
        window_start_ms += step_ms
    return windows


def _window_prompt(
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow,
) -> str:
    payload = {
        "video": {
            "videoId": execution_input.video.id,
            "youtubeVideoId": execution_input.video.youtube_video_id,
            "title": execution_input.video.title,
        },
        "window": {
            "windowIndex": cue_window.window_index,
            "firstCueId": cue_window.cues[0].cue_id,
            "lastCueId": cue_window.cues[-1].cue_id,
            "promptVersion": MICRO_EVENT_EXTRACT_PROMPT_VERSION,
        },
        "cues": [
            {"cue_id": cue.cue_id, "text": cue.text}
            for cue in cue_window.cues
        ],
    }
    return f"{PROMPT_HEADER}\n입력 JSON:\n{json.dumps(payload, ensure_ascii=False)}"


def _validated_window(
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow,
    result: MicroEventExtractionResult,
) -> MicroEventExtractionWindowCreate:
    parsed = _parse_extractor_output(result.final_response)
    output = _validate_extractor_output(parsed)
    cue_id_to_index = {cue.cue_id: cue.cue_index for cue in cue_window.cues}
    event_creates: list[MicroEventCandidateCreate] = []
    for index, event in enumerate(output.micro_events, start=1):
        _validate_event_cue_refs(event, cue_id_to_index)
        event_creates.append(
            MicroEventCandidateCreate(
                candidate_index=index,
                activity=event.activity,
                event=event.event,
                start_cue_id=event.start_cue_id,
                end_cue_id=event.end_cue_id,
                evidence_cue_ids=event.evidence_cue_ids,
                boundary_before=event.boundary_before,
                boundary_after=event.boundary_after,
                confidence=event.confidence,
            )
        )
    asr_creates: list[AsrCorrectionCandidateCreate] = []
    for index, candidate in enumerate(output.asr_correction_candidates, start=1):
        _validate_evidence_cue_ids(candidate.evidence_cue_ids, cue_id_to_index)
        asr_creates.append(
            AsrCorrectionCandidateCreate(
                candidate_index=index,
                original=candidate.original,
                suggested=candidate.suggested,
                correction_type=candidate.correction_type,
                apply_scope=candidate.apply_scope,
                evidence_cue_ids=candidate.evidence_cue_ids,
                confidence=candidate.confidence,
            )
        )
    return MicroEventExtractionWindowCreate(
        video_task_id=task.id,
        video_id=execution_input.video.id,
        transcript_id=execution_input.metadata.id,
        window_index=cue_window.window_index,
        start_cue_id=cue_window.cues[0].cue_id,
        end_cue_id=cue_window.cues[-1].cue_id,
        cue_count=len(cue_window.cues),
        status="succeeded",
        carry_out_unfinished=output.carry_out.unfinished,
        codex_thread_id=result.thread_id,
        codex_turn_id=result.turn_id,
        raw_response_text=result.final_response,
        parsed_response_json=cast(JsonObject, output.model_dump(mode="json")),
        validation_error=None,
        source_job_id=job.id,
        source_job_attempt_id=attempt.id,
        micro_events=event_creates,
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
        start_cue_id=cue_window.cues[0].cue_id,
        end_cue_id=cue_window.cues[-1].cue_id,
        cue_count=len(cue_window.cues),
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


def _parse_extractor_output(raw_response: str) -> JsonObject:
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise MicroEventExtractionOutputInvalid("Extractor returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise MicroEventExtractionOutputInvalid("Extractor output must be a JSON object.")
    return cast(JsonObject, parsed)


def _validate_extractor_output(parsed: JsonObject) -> _ExtractorOutput:
    try:
        return _ExtractorOutput.model_validate(parsed)
    except ValidationError as exc:
        message = json.dumps(exc.errors(include_url=False), ensure_ascii=False)
        raise MicroEventExtractionOutputInvalid(message) from exc


def _validate_event_cue_refs(
    event: _MicroEventOutput,
    cue_id_to_index: dict[str, int],
) -> None:
    _validate_cue_id(event.start_cue_id, cue_id_to_index)
    _validate_cue_id(event.end_cue_id, cue_id_to_index)
    if cue_id_to_index[event.start_cue_id] > cue_id_to_index[event.end_cue_id]:
        raise MicroEventExtractionOutputInvalid(
            "start_cue_id must not come after end_cue_id."
        )
    _validate_evidence_cue_ids(event.evidence_cue_ids, cue_id_to_index)


def _validate_evidence_cue_ids(
    evidence_cue_ids: list[str],
    cue_id_to_index: dict[str, int],
) -> None:
    for cue_id in evidence_cue_ids:
        _validate_cue_id(cue_id, cue_id_to_index)


def _validate_cue_id(cue_id: str, cue_id_to_index: dict[str, int]) -> None:
    if cue_id not in cue_id_to_index:
        raise MicroEventExtractionOutputInvalid(
            f"Extractor referenced cue_id outside the input window: {cue_id}"
        )


def _task_input_hash(
    *,
    video: VideoRecord,
    metadata: YouTubeTranscriptMetadataRecord,
    window_minutes: int,
    overlap_minutes: int,
    model: str | None,
) -> str:
    payload = {
        "model": model,
        "overlapMinutes": overlap_minutes,
        "promptVersion": MICRO_EVENT_EXTRACT_PROMPT_VERSION,
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
        "windowCount": _window_count(detail),
        "microEventCount": _micro_event_count(detail),
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
    return MicroEventExtractResponse(
        videoId=video.id,
        youtubeVideoId=video.youtube_video_id,
        videoTaskId=task.id,
        status=status,
        reason=reason,
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
                        "createdAt": candidate.created_at,
                        "updatedAt": candidate.updated_at,
                    }
                    for candidate in window.micro_events
                ],
                "asrCorrectionCandidates": [
                    {
                        "asrCorrectionCandidateId": candidate.id,
                        "candidateIndex": candidate.candidate_index,
                        "original": candidate.original,
                        "suggested": candidate.suggested,
                        "correctionType": candidate.correction_type,
                        "applyScope": candidate.apply_scope,
                        "evidenceCueIds": candidate.evidence_cue_ids,
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


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise VideoTaskRetryNotAllowed(f"Pipeline job input is missing integer '{key}'.")
    return value
