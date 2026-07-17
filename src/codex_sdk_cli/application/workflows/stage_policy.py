from __future__ import annotations

from datetime import datetime, timedelta

from codex_sdk_cli.application.asr.executors import (
    ASR_TRANSCRIBE_TASK,
    ASR_TRANSCRIBE_VERSION,
)
from codex_sdk_cli.application.processing.commands import (
    MICRO_EVENT_TASK,
    MICRO_EVENT_VERSION,
    TIMELINE_TASK,
    TIMELINE_VERSION,
)
from codex_sdk_cli.application.transcripts.commands import (
    TRANSCRIPT_COLLECT_TASK,
    TRANSCRIPT_COLLECT_VERSION,
    TRANSCRIPT_CUE_TASK,
    TRANSCRIPT_CUE_VERSION,
)
from codex_sdk_cli.domains.work.models import WorkflowRun, WorkItem

from .options import aware_datetime, option_int, option_int_default

ARCHIVE_PUBLISH_TASK = "archive_publish"
ARCHIVE_PUBLISH_VERSION = "v2"
TRANSCRIPT_RECHECK_STAGE = "transcript_recheck"
STAGES = (
    TRANSCRIPT_COLLECT_TASK,
    TRANSCRIPT_CUE_TASK,
    MICRO_EVENT_TASK,
    TIMELINE_TASK,
    ARCHIVE_PUBLISH_TASK,
)
V2_STAGES = (
    TRANSCRIPT_COLLECT_TASK,
    TRANSCRIPT_RECHECK_STAGE,
    ASR_TRANSCRIBE_TASK,
    TRANSCRIPT_CUE_TASK,
    MICRO_EVENT_TASK,
    TIMELINE_TASK,
    ARCHIVE_PUBLISH_TASK,
)


def stage_version(stage_name: str) -> str:
    return {
        TRANSCRIPT_COLLECT_TASK: TRANSCRIPT_COLLECT_VERSION,
        TRANSCRIPT_RECHECK_STAGE: TRANSCRIPT_COLLECT_VERSION,
        ASR_TRANSCRIBE_TASK: ASR_TRANSCRIBE_VERSION,
        TRANSCRIPT_CUE_TASK: TRANSCRIPT_CUE_VERSION,
        MICRO_EVENT_TASK: MICRO_EVENT_VERSION,
        TIMELINE_TASK: TIMELINE_VERSION,
        ARCHIVE_PUBLISH_TASK: ARCHIVE_PUBLISH_VERSION,
    }[stage_name]


def stage_timeout(workflow: WorkflowRun, stage_name: str) -> int:
    key = {
        TRANSCRIPT_COLLECT_TASK: "transcript_timeout_seconds",
        TRANSCRIPT_RECHECK_STAGE: "transcript_timeout_seconds",
        ASR_TRANSCRIBE_TASK: "asr_timeout_seconds",
        TRANSCRIPT_CUE_TASK: "cue_timeout_seconds",
        MICRO_EVENT_TASK: "micro_timeout_seconds",
        TIMELINE_TASK: "timeline_timeout_seconds",
        ARCHIVE_PUBLISH_TASK: "archive_timeout_seconds",
    }[stage_name]
    return option_int(workflow, key)


def stage_task_type(stage_name: str) -> str:
    return TRANSCRIPT_COLLECT_TASK if stage_name == TRANSCRIPT_RECHECK_STAGE else stage_name


def stage_position(workflow: WorkflowRun, stage_name: str) -> int:
    stages = V2_STAGES if workflow.workflow_version == "v2" else STAGES
    return stages.index(stage_name) + 1


def stage_available_at(
    workflow: WorkflowRun,
    stage_name: str,
    now: datetime,
    dependency: WorkItem | None,
) -> datetime:
    if stage_name != TRANSCRIPT_RECHECK_STAGE:
        return now
    if dependency is None or dependency.completed_at is None:
        raise RuntimeError("Transcript recheck requires a completed initial transcript check.")
    deadline = transcript_recheck_deadline(workflow, dependency)
    interval = timedelta(
        seconds=option_int_default(
            workflow,
            "transcript_recheck_interval_seconds",
            1800,
        )
    )
    first_recheck = min(aware_datetime(dependency.completed_at) + interval, deadline)
    return max(now, first_recheck)


def transcript_recheck_deadline(workflow: WorkflowRun, initial: WorkItem) -> datetime:
    if initial.completed_at is None:
        raise RuntimeError("Initial transcript check has no completion timestamp.")
    grace = timedelta(seconds=option_int(workflow, "transcript_fallback_grace_seconds"))
    return aware_datetime(initial.completed_at) + grace
