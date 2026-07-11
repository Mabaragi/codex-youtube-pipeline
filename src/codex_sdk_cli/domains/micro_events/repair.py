from __future__ import annotations

import time

from codex_sdk_cli.domains.llm_traces.ports import LlmTraceRecorderPort
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .exceptions import MicroEventExtractionOutputInvalid
from .output_validation import MicroEventOutputWarning
from .ports import (
    MicroEventExtractionResult,
    MicroEventExtractionWindowCreate,
    MicroEventExtractorPort,
    MicroEventRepairRequest,
)
from .task_events import MicroEventTaskEventRecorder
from .tracing import (
    _elapsed_ms,
    _micro_trace_event,
    _repair_event_metadata,
)
from .window_results import _validated_window
from .windowing import (
    _CueWindow,
    _ExtractionExecutionInput,
    _repair_window_prompt,
)


class MicroEventWindowRepairService:
    def __init__(
        self,
        *,
        extractor: MicroEventExtractorPort,
        llm_traces: LlmTraceRecorderPort,
        task_events: MicroEventTaskEventRecorder,
    ) -> None:
        self._extractor = extractor
        self._llm_traces = llm_traces
        self._task_events = task_events

    async def repair(
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
        await self._task_events.record(
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
            await self._record_failed_call(
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                window_count=window_count,
                started_at=started_at,
                original_error=original_error,
                original_error_message=original_error_message,
                repair_error=exc,
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
            await self._record_invalid_output(
                task=task,
                job=job,
                attempt=attempt,
                execution_input=execution_input,
                cue_window=cue_window,
                window_count=window_count,
                started_at=started_at,
                original_error=original_error,
                original_error_message=original_error_message,
                repair_result=repair_result,
                repair_error=exc,
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
        await self._task_events.record(
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

    async def _record_failed_call(
        self,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        execution_input: _ExtractionExecutionInput,
        cue_window: _CueWindow,
        window_count: int,
        started_at: float,
        original_error: MicroEventExtractionOutputInvalid,
        original_error_message: str,
        repair_error: Exception,
    ) -> None:
        repair_error_message = str(repair_error) or repair_error.__class__.__name__
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
                error_type=repair_error.__class__.__name__,
                error_message=repair_error_message,
            )
        )
        await self._task_events.record(
            "micro_event_extract.window_repair_failed",
            "error",
            "Micro-event extraction window repair failed.",
            task=task,
            execution_input=execution_input,
            reason="window_repair_exception",
            error_type=repair_error.__class__.__name__,
            error_message=repair_error_message,
            metadata_json=_repair_event_metadata(
                cue_window,
                original_error=original_error_message,
                repair_error=repair_error_message,
            ),
        )

    async def _record_invalid_output(
        self,
        *,
        task: VideoTaskRecord,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        execution_input: _ExtractionExecutionInput,
        cue_window: _CueWindow,
        window_count: int,
        started_at: float,
        original_error: MicroEventExtractionOutputInvalid,
        original_error_message: str,
        repair_result: MicroEventExtractionResult,
        repair_error: MicroEventExtractionOutputInvalid,
    ) -> None:
        repair_error_message = str(repair_error)
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
                error_type=repair_error.__class__.__name__,
                error_message=repair_error_message,
            )
        )
        await self._task_events.record(
            "micro_event_extract.window_repair_failed",
            "error",
            "Micro-event extraction window repair produced invalid output.",
            task=task,
            execution_input=execution_input,
            reason="window_repair_invalid",
            error_type=repair_error.__class__.__name__,
            error_message=repair_error_message,
            metadata_json=_repair_event_metadata(
                cue_window,
                original_error=original_error_message,
                repair_error=repair_error_message,
                repair_thread_id=repair_result.thread_id,
                repair_turn_id=repair_result.turn_id,
            ),
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
