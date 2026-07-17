from __future__ import annotations

from dataclasses import dataclass

from codex_sdk_cli.domains.work.models import JsonObject, WorkflowRun, WorkflowStep


@dataclass(frozen=True, slots=True)
class WorkflowSelectionItem:
    video_id: int
    youtube_video_id: str | None
    status: str
    reason: str
    workflow_run_id: int | None


@dataclass(frozen=True, slots=True)
class WorkflowBatchResult:
    batch_id: int
    requested_count: int
    created_count: int
    reused_count: int
    skipped_count: int
    items: tuple[WorkflowSelectionItem, ...]


@dataclass(frozen=True, slots=True)
class CoordinatorRunResult:
    processed: bool
    workflow_run_id: int | None = None
    status: str | None = None
    current_stage: str | None = None


def coordinator_result(workflow: WorkflowRun) -> CoordinatorRunResult:
    return CoordinatorRunResult(
        processed=True,
        workflow_run_id=workflow.id,
        status=workflow.status.value,
        current_stage=workflow.current_stage,
    )


def workflow_output(steps: list[WorkflowStep]) -> JsonObject:
    return {
        "steps": [
            {
                "stage": step.stage_name,
                "workItemId": step.work_item_id,
                "status": step.status,
            }
            for step in steps
        ]
    }
