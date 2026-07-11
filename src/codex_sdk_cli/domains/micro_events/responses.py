from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from codex_sdk_cli.domains.codex.choices import (
    CODEX_MODEL_CHOICES,
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.video_tasks.exceptions import VideoTaskRetryNotAllowed
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord
from codex_sdk_cli.domains.videos.ports import VideoRecord

from .ports import JsonObject, MicroEventExtractionDetailRecord
from .schemas import (
    MicroEventEnqueueItemResponse,
    MicroEventEnqueueRequest,
    MicroEventEnqueueResponse,
    MicroEventExtractionDetailResponse,
    MicroEventExtractResponse,
)


@dataclass(slots=True)
class _EnqueueCounters:
    scanned_count: int = 0
    enqueued_count: int = 0
    already_pending_count: int = 0
    already_running_count: int = 0
    already_succeeded_count: int = 0
    skipped_failed_count: int = 0
    ineligible_count: int = 0


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
        _window_count(detail) if detail is not None else _int_output(output_json, "windowCount")
    )
    first_cue_id = (
        _first_cue_id(detail) if detail is not None else _str_output(output_json, "firstCueId")
    )
    last_cue_id = (
        _last_cue_id(detail) if detail is not None else _str_output(output_json, "lastCueId")
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


def _skipped_extract_response(
    video: VideoRecord,
    *,
    reason: str,
    model: CodexModelChoice | None,
    reasoning_effort: ReasoningEffortChoice | None,
) -> MicroEventExtractResponse:
    return MicroEventExtractResponse(
        videoId=video.id,
        youtubeVideoId=video.youtube_video_id,
        videoTaskId=None,
        status="skipped",
        reason=reason,
        model=model,
        reasoningEffort=reasoning_effort,
        jobId=None,
        jobAttemptId=None,
        transcriptId=None,
        windowCount=None,
        microEventCount=None,
        asrCorrectionCandidateCount=None,
        firstCueId=None,
        lastCueId=None,
        errorType=None,
        errorMessage=None,
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
    if value in CODEX_MODEL_CHOICES:
        return value
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
