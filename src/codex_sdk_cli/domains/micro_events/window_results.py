from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .exceptions import MicroEventExtractionOutputInvalid
from .output_validation import (
    MicroEventOutputWarning,
    _normalized_topics,
    _parse_extractor_output,
    _support_level_confidence,
    _validate_event_cue_refs,
    _validate_extractor_output,
    _validate_owned_range_coverage,
    _validate_range_cue_refs,
    _warnings_json,
)
from .ports import (
    AsrCorrectionCandidateCreate,
    MicroEventCandidateCreate,
    MicroEventExcludedRangeCreate,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionResult,
    MicroEventExtractionWindowCreate,
    MicroEventExtractionWindowRecord,
)
from .windowing import _CueWindow, _ExtractionExecutionInput


@dataclass(frozen=True, slots=True)
class _MicroEventPartialResumePlan:
    resumed_windows: dict[int, MicroEventExtractionWindowCreate]
    pending_windows: list[_CueWindow]
    skip_reason: str | None


class _MicroEventWindowValidationFailure(Exception):
    def __init__(
        self,
        error: MicroEventExtractionOutputInvalid,
        failed_window: MicroEventExtractionWindowCreate,
    ) -> None:
        super().__init__(str(error))
        self.error = error
        self.failed_window = failed_window


def _partial_resume_plan(
    detail: MicroEventExtractionDetailRecord | None,
    cue_windows: list[_CueWindow],
    *,
    execution_input: _ExtractionExecutionInput,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> _MicroEventPartialResumePlan:
    if detail is None or not detail.windows:
        return _MicroEventPartialResumePlan(
            resumed_windows={},
            pending_windows=list(cue_windows),
            skip_reason="no_partial_windows",
        )

    expected_by_index = {window.window_index: window for window in cue_windows}
    existing_by_index: dict[int, MicroEventExtractionWindowRecord] = {}
    for window in detail.windows:
        if window.window_index in existing_by_index:
            return _MicroEventPartialResumePlan(
                resumed_windows={},
                pending_windows=list(cue_windows),
                skip_reason="duplicate_window_indices",
            )
        existing_by_index[window.window_index] = window

    if set(existing_by_index) - set(expected_by_index):
        return _MicroEventPartialResumePlan(
            resumed_windows={},
            pending_windows=list(cue_windows),
            skip_reason="stale_extra_windows",
        )

    for window_index, record in existing_by_index.items():
        if not _window_record_matches_current_input(
            record,
            expected_by_index[window_index],
            execution_input=execution_input,
        ):
            return _MicroEventPartialResumePlan(
                resumed_windows={},
                pending_windows=list(cue_windows),
                skip_reason="stale_window_shape",
            )

    resumed_windows = {
        record.window_index: _window_create_from_record(
            record,
            source_job_id=record.source_job_id or job.id,
            source_job_attempt_id=record.source_job_attempt_id or attempt.id,
        )
        for record in detail.windows
        if record.status == "succeeded"
    }
    pending_windows = [
        window for window in cue_windows if window.window_index not in resumed_windows
    ]
    return _MicroEventPartialResumePlan(
        resumed_windows=resumed_windows,
        pending_windows=pending_windows,
        skip_reason=None,
    )


def _window_record_matches_current_input(
    record: MicroEventExtractionWindowRecord,
    cue_window: _CueWindow,
    *,
    execution_input: _ExtractionExecutionInput,
) -> bool:
    return (
        record.video_id == execution_input.video.id
        and record.transcript_id == execution_input.metadata.id
        and record.window_index == cue_window.window_index
        and record.start_cue_id == cue_window.owned_cues[0].cue_id
        and record.end_cue_id == cue_window.owned_cues[-1].cue_id
        and record.cue_count == len(cue_window.owned_cues)
    )


def _window_create_from_record(
    record: MicroEventExtractionWindowRecord,
    *,
    source_job_id: int,
    source_job_attempt_id: int,
) -> MicroEventExtractionWindowCreate:
    return MicroEventExtractionWindowCreate(
        video_task_id=record.video_task_id,
        video_id=record.video_id,
        transcript_id=record.transcript_id,
        window_index=record.window_index,
        start_cue_id=record.start_cue_id,
        end_cue_id=record.end_cue_id,
        cue_count=record.cue_count,
        status=record.status,
        carry_out_unfinished=record.carry_out_unfinished,
        codex_thread_id=record.codex_thread_id,
        codex_turn_id=record.codex_turn_id,
        raw_response_text=record.raw_response_text,
        parsed_response_json=record.parsed_response_json,
        validation_error=record.validation_error,
        source_job_id=source_job_id,
        source_job_attempt_id=source_job_attempt_id,
        micro_events=[
            MicroEventCandidateCreate(
                candidate_index=candidate.candidate_index,
                activity=candidate.activity,
                event=candidate.event,
                start_cue_id=candidate.start_cue_id,
                end_cue_id=candidate.end_cue_id,
                evidence_cue_ids=candidate.evidence_cue_ids,
                boundary_before=candidate.boundary_before,
                boundary_after=candidate.boundary_after,
                confidence=candidate.confidence,
                program_mode=candidate.program_mode,
                content_kind=candidate.content_kind,
                topics=candidate.topics,
                relation_to_previous=candidate.relation_to_previous,
                continues_to_next=candidate.continues_to_next,
                support_level=candidate.support_level,
            )
            for candidate in record.micro_events
        ],
        excluded_ranges=[
            MicroEventExcludedRangeCreate(
                range_index=excluded_range.range_index,
                start_cue_id=excluded_range.start_cue_id,
                end_cue_id=excluded_range.end_cue_id,
                reason=excluded_range.reason,
            )
            for excluded_range in record.excluded_ranges
        ],
        asr_correction_candidates=[
            AsrCorrectionCandidateCreate(
                candidate_index=candidate.candidate_index,
                original=candidate.original,
                suggested=candidate.suggested,
                correction_type=candidate.correction_type,
                apply_scope=candidate.apply_scope,
                confidence=candidate.confidence,
            )
            for candidate in record.asr_correction_candidates
        ],
    )


def _partial_resume_metadata(
    *,
    resumed_window_indices: dict[int, MicroEventExtractionWindowCreate],
    scheduled_windows: list[_CueWindow],
    window_count: int,
    skip_reason: str | None = None,
) -> JsonObject:
    metadata: JsonObject = {
        "resumedWindowIndices": sorted(resumed_window_indices),
        "scheduledWindowIndices": [window.window_index for window in scheduled_windows],
        "resumedWindowCount": len(resumed_window_indices),
        "scheduledWindowCount": len(scheduled_windows),
        "windowCount": window_count,
    }
    if skip_reason is not None:
        metadata["skipReason"] = skip_reason
    return metadata


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


def _runtime_failed_window(
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    execution_input: _ExtractionExecutionInput,
    cue_window: _CueWindow,
    error_type: str,
    error_message: str,
) -> MicroEventExtractionWindowCreate:
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
        codex_thread_id=None,
        codex_turn_id=None,
        raw_response_text=None,
        parsed_response_json=None,
        validation_error=f"{error_type}: {error_message}",
        source_job_id=job.id,
        source_job_attempt_id=attempt.id,
    )


def _sorted_windows(
    windows: Iterable[MicroEventExtractionWindowCreate],
) -> list[MicroEventExtractionWindowCreate]:
    return sorted(windows, key=lambda window: window.window_index)
