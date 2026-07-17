from __future__ import annotations

from typing import cast

from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionResult,
    WorkExecutorPort,
)
from codex_sdk_cli.domains.codex.choices import (
    CODEX_MODEL_CHOICES,
    CodexModelChoice,
    ReasoningEffortChoice,
)
from codex_sdk_cli.domains.timelines.ports import CopyStyle

from .ports import MicroEventProcessorPort, TimelineProcessorPort


class MicroEventExtractionExecutor(WorkExecutorPort):
    def __init__(self, processor: MicroEventProcessorPort) -> None:
        self._processor = processor

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        values = context.work_item.input_json
        result = await self._processor.process(
            work_item_id=context.work_item.id,
            work_attempt_id=context.attempt_id,
            video_id=_required_int(values, "videoId"),
            transcript_id=_required_int(values, "transcriptId"),
            window_minutes=_required_int(values, "windowMinutes"),
            overlap_minutes=_required_int(values, "overlapMinutes"),
            model=_required_model(values, "model"),
            reasoning_effort=_required_reasoning(values, "reasoningEffort"),
            prompt_version_id=_optional_int(values, "promptVersionId"),
        )
        return WorkExecutionResult(
            output_json={
                "videoId": result.video_id,
                "transcriptId": result.transcript_id,
                "windowCount": result.window_count,
                "microEventCount": result.micro_event_count,
                "validationWarningCount": result.validation_warning_count,
            },
            output_transcript_id=result.transcript_id,
        )


class TimelineCompositionExecutor(WorkExecutorPort):
    def __init__(self, processor: TimelineProcessorPort) -> None:
        self._processor = processor

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        values = context.work_item.input_json
        result = await self._processor.process(
            work_item_id=context.work_item.id,
            work_attempt_id=context.attempt_id,
            video_id=_required_int(values, "videoId"),
            source_micro_event_work_item_id=_required_int_alias(
                values,
                "sourceMicroEventWorkItemId",
                "sourceMicroEventTaskId",
            ),
            model=_required_model(values, "model"),
            reasoning_effort=_required_reasoning(values, "reasoningEffort"),
            copy_style=_required_copy_style(values, "copyStyle"),
            prompt_version_id=_optional_int(values, "promptVersionId"),
        )
        return WorkExecutionResult(
            output_json={
                "videoId": result.video_id,
                "compositionId": result.composition_id,
                "timelineTitle": result.title,
                "blockCount": result.block_count,
                "episodeCount": result.episode_count,
                "topicClusterCount": result.topic_cluster_count,
                "reviewFlagCount": result.review_flag_count,
                "validationWarningCount": result.validation_warning_count,
                "timelineState": result.timeline_state,
                "emptyReason": result.empty_reason,
                "generationMode": result.generation_mode,
            }
        )


def _required_int(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be an integer.")


def _required_int_alias(
    values: dict[str, object],
    key: str,
    legacy_key: str,
) -> int:
    value = values.get(key, values.get(legacy_key))
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be an integer.")


def _optional_int(values: dict[str, object], key: str) -> int | None:
    value = values.get(key)
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be an integer or null.")


def _required_str(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if isinstance(value, str) and value:
        return value
    raise ValueError(f"{key} must be a non-empty string.")


def _required_model(values: dict[str, object], key: str) -> CodexModelChoice:
    value = _required_str(values, key)
    if value not in CODEX_MODEL_CHOICES:
        raise ValueError(f"{key} is not a supported model.")
    return value


def _required_reasoning(
    values: dict[str, object],
    key: str,
) -> ReasoningEffortChoice:
    value = _required_str(values, key)
    if value not in {"low", "medium", "high", "xhigh"}:
        raise ValueError(f"{key} is not a supported reasoning effort.")
    return cast(ReasoningEffortChoice, value)


def _required_copy_style(values: dict[str, object], key: str) -> CopyStyle:
    value = _required_str(values, key)
    if value != "LIGHT_FANDOM_V1":
        raise ValueError(f"{key} is not a supported copy style.")
    return value
