from __future__ import annotations

import hashlib
import logging
import time

from codex_sdk_cli.domains.llm_traces.ports import LlmTraceEvent
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .models import _ComposerInput, _TimelineRawResponse
from .ports import (
    TimelineComposeResult,
    TimelineEpisodeRepairResult,
)

_TIMELINE_RAW_RESPONSE_STORED_IN = "pipelineJobAttempt.outputJson.rawResponses"
logger = logging.getLogger(__name__)


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


def _raw_response_summary(raw_responses: list[_TimelineRawResponse]) -> JsonObject:
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
