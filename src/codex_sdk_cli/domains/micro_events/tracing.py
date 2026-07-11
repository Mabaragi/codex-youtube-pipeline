from __future__ import annotations

import time

from codex_sdk_cli.domains.llm_traces.ports import LlmTraceEvent
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .exceptions import MicroEventExtractionOutputInvalid
from .ports import MicroEventExtractionResult
from .windowing import _CueWindow, _ExtractionExecutionInput


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


def _window_retry_metadata(
    cue_window: _CueWindow,
    *,
    window_count: int,
    retry_attempt: int,
    max_retry_attempts: int,
    error_type: str | None = None,
    error_message: str | None = None,
) -> JsonObject:
    metadata: JsonObject = {
        "windowIndex": cue_window.window_index,
        "windowCount": window_count,
        "retryAttempt": retry_attempt,
        "maxRetryAttempts": max_retry_attempts,
        "ownedStartCueId": cue_window.owned_cues[0].cue_id,
        "ownedEndCueId": cue_window.owned_cues[-1].cue_id,
    }
    if error_type is not None:
        metadata["errorType"] = error_type
    if error_message is not None:
        metadata["errorMessage"] = error_message
    return metadata
