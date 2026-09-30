from __future__ import annotations

from codex_sdk_cli.application.asr.executors import ASR_TRANSCRIBE_TASK
from codex_sdk_cli.application.processing.commands import MICRO_EVENT_TASK, TIMELINE_TASK
from codex_sdk_cli.application.transcripts.commands import (
    TRANSCRIPT_COLLECT_TASK,
    TRANSCRIPT_CUE_TASK,
)
from codex_sdk_cli.domains.work.models import JsonObject, WorkflowRun, WorkItem

from .options import (
    input_int as _input_int,
)
from .options import (
    option_bool as _option_bool,
)
from .options import (
    option_int as _option_int,
)
from .options import (
    option_optional_int as _option_optional_int,
)
from .options import (
    option_str as _option_str,
)
from .options import (
    option_str_list as _option_str_list,
)
from .options import (
    output_int as _output_int,
)
from .options import (
    required_output_int as _required_output_int,
)
from .options import (
    required_output_str as _required_output_str,
)
from .stage_policy import (
    ARCHIVE_PUBLISH_TASK,
    TRANSCRIPT_RECHECK_STAGE,
)
from .stage_policy import (
    stage_timeout as _stage_timeout,
)
from .stage_policy import (
    stage_version as _stage_version,
)


def _stage_input(
    workflow: WorkflowRun,
    stage_name: str,
    dependency: WorkItem | None,
) -> JsonObject:
    base: JsonObject = {
        "videoId": workflow.video_id,
        "youtubeVideoId": _option_str(workflow, "youtubeVideoId"),
        "timeoutSeconds": _stage_timeout(workflow, stage_name),
        "taskVersion": _stage_version(stage_name),
    }
    if stage_name in {TRANSCRIPT_COLLECT_TASK, TRANSCRIPT_RECHECK_STAGE}:
        return {
            **base,
            "languages": _option_str_list(workflow, "languages"),
            "preserveFormatting": _option_bool(workflow, "preserve_formatting"),
            "recheckNoTranscript": stage_name == TRANSCRIPT_RECHECK_STAGE,
        }
    if dependency is None:
        raise RuntimeError(f"{stage_name} requires a dependency.")
    if stage_name == ASR_TRANSCRIBE_TASK:
        return {
            **base,
            "model": _option_str(workflow, "asr_model"),
            "language": _option_str(workflow, "asr_language"),
            "device": _option_str(workflow, "asr_device"),
            "computeType": _option_str(workflow, "asr_compute_type"),
            "chunkMinutes": _option_int(workflow, "asr_chunk_minutes"),
            "overlapSeconds": _option_int(workflow, "asr_overlap_seconds"),
            "beamSize": _option_int(workflow, "asr_beam_size"),
            "vadFilter": _option_bool(workflow, "asr_vad_filter"),
        }
    if stage_name == TRANSCRIPT_CUE_TASK:
        return {
            **base,
            "transcriptId": _required_output_int(dependency, "transcriptId"),
            "responseSha256": _required_output_str(dependency, "responseSha256"),
        }
    if stage_name == MICRO_EVENT_TASK:
        return {
            **base,
            "transcriptId": _required_output_int(dependency, "transcriptId"),
            "sourceTranscriptCueWorkItemId": dependency.id,
            "windowMinutes": _option_int(workflow, "micro_window_minutes"),
            "overlapMinutes": _option_int(workflow, "micro_overlap_minutes"),
            "model": _option_str(workflow, "micro_model"),
            "reasoningEffort": _option_str(workflow, "micro_reasoning_effort"),
            "promptVersionId": _option_optional_int(workflow, "micro_prompt_version_id"),
        }
    if stage_name == TIMELINE_TASK:
        return {
            **base,
            "sourceMicroEventWorkItemId": dependency.id,
            "model": _option_str(workflow, "timeline_model"),
            "reasoningEffort": _option_str(workflow, "timeline_reasoning_effort"),
            "copyStyle": _option_str(workflow, "timeline_copy_style"),
            "promptVersionId": _option_optional_int(workflow, "timeline_prompt_version_id"),
        }
    archive_input = {
        **base,
        "sourceTimelineWorkItemId": dependency.id,
        "publishMode": _option_str(workflow, "publish_mode"),
        "environment": _option_str(workflow, "environment"),
        "variant": _option_str(workflow, "variant"),
        "schemaVersion": _option_int(workflow, "schema_version"),
    }
    if workflow.workflow_version == "v3":
        archive_input.update(
            sourceTimelineWorkItemId=_required_source_timeline(dependency),
            sourceClassificationWorkItemId=dependency.id,
            sourceClassificationId=_required_output_int(dependency, "classificationId"),
            sourceClassificationFingerprint=_required_output_str(dependency, "inputFingerprint"),
        )
    return archive_input


def _can_reuse(item: WorkItem, stage_name: str, dependency: WorkItem | None) -> bool:
    if item.outcome_code is not None:
        return False
    if stage_name == TRANSCRIPT_COLLECT_TASK:
        return item.output_transcript_id is not None
    if stage_name in {TRANSCRIPT_RECHECK_STAGE, ASR_TRANSCRIBE_TASK}:
        return False
    if dependency is None:
        return False
    if stage_name == TRANSCRIPT_CUE_TASK:
        return _output_int(item, "transcriptId") == _required_output_int(dependency, "transcriptId")
    source_key = {
        MICRO_EVENT_TASK: "sourceTranscriptCueWorkItemId",
        TIMELINE_TASK: "sourceMicroEventWorkItemId",
        ARCHIVE_PUBLISH_TASK: "sourceTimelineWorkItemId",
    }[stage_name]
    return _input_int(item, source_key) == dependency.id


def _required_source_timeline(item: WorkItem) -> int:
    value = _input_int(item, "sourceTimelineWorkItemId")
    if value is None:
        raise RuntimeError("Classification is missing its source timeline.")
    return value
