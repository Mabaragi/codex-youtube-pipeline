from __future__ import annotations

import json
import time

from codex_sdk_cli.domains.llm_traces.ports import LlmTraceRecorderPort
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .exceptions import (
    MicroEventExtractionOutputInvalid,
    MicroEventWindowQualityRejected,
)
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
            _validate_repair_low_information_delta(
                original_response=original_result.final_response,
                repair_response=repair_result.final_response,
                cue_window=cue_window,
            )
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
            if _is_window_quality_rejection(str(exc)):
                raise MicroEventWindowQualityRejected(str(exc)) from exc
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
        "Extractor classified an implausibly large LOW_INFORMATION range",
    )
    return any(fragment in error_message for fragment in recoverable_fragments)


def _validate_repair_low_information_delta(
    *,
    original_response: str,
    repair_response: str,
    cue_window: _CueWindow,
) -> None:
    cue_id_to_position = {
        cue.cue_id: position for position, cue in enumerate(cue_window.owned_cues)
    }
    original_positions = _low_information_positions(
        original_response,
        cue_id_to_position=cue_id_to_position,
    )
    repaired_positions = _low_information_positions(
        repair_response,
        cue_id_to_position=cue_id_to_position,
    )
    added_positions = repaired_positions - original_positions
    owned_cue_count = len(cue_window.owned_cues)
    if (
        owned_cue_count > 0
        and len(added_positions) >= 100
        and len(added_positions) / owned_cue_count >= 0.25
    ):
        raise MicroEventExtractionOutputInvalid(
            "Repair added implausibly large LOW_INFORMATION coverage "
            f"({len(added_positions)}/{owned_cue_count} owned cues)."
        )


def _low_information_positions(
    raw_response: str,
    *,
    cue_id_to_position: dict[str, int],
) -> set[int]:
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        return set()
    if not isinstance(parsed, dict):
        return set()
    raw_ranges = parsed.get("excluded_ranges")
    if not isinstance(raw_ranges, list):
        return set()
    positions: set[int] = set()
    for raw_range in raw_ranges:
        if not isinstance(raw_range, dict):
            continue
        reason = raw_range.get("reason")
        if not isinstance(reason, str) or _normalized_reason(reason) != "LOW_INFORMATION":
            continue
        start_cue_id = raw_range.get("start_cue_id")
        end_cue_id = raw_range.get("end_cue_id")
        if not isinstance(start_cue_id, str) or not isinstance(end_cue_id, str):
            continue
        start_position = cue_id_to_position.get(start_cue_id)
        end_position = cue_id_to_position.get(end_cue_id)
        if start_position is None or end_position is None or start_position > end_position:
            continue
        positions.update(range(start_position, end_position + 1))
    return positions


def _normalized_reason(reason: str) -> str:
    return reason.strip().upper().replace("-", "_").replace(" ", "_")


def _is_window_quality_rejection(error_message: str) -> bool:
    return error_message.startswith(
        (
            "Repair added implausibly large LOW_INFORMATION coverage",
            "Extractor classified an implausibly large LOW_INFORMATION range",
        )
    )
