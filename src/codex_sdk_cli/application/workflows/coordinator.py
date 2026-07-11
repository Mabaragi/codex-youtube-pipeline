from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta

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
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import CreateWorkItem, WorkUnitOfWorkPort
from codex_sdk_cli.domains.work.models import (
    TERMINAL_WORK_ITEM_STATUSES,
    JsonObject,
    WorkExecutionMode,
    WorkflowRun,
    WorkflowStep,
    WorkItem,
    WorkItemStatus,
)

from .models import CoordinatorRunResult
from .ports import InlineWorkRunnerPort

ARCHIVE_PUBLISH_TASK = "archive_publish"
ARCHIVE_PUBLISH_VERSION = "v2"
STAGES = (
    TRANSCRIPT_COLLECT_TASK,
    TRANSCRIPT_CUE_TASK,
    MICRO_EVENT_TASK,
    TIMELINE_TASK,
    ARCHIVE_PUBLISH_TASK,
)
Now = Callable[[], datetime]


class ProcessToPublishCoordinator:
    def __init__(
        self,
        *,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        inline_runner: InlineWorkRunnerPort,
        worker_id: str,
        lease_seconds: int = 90,
        heartbeat_seconds: int = 30,
        now: Now | None = None,
    ) -> None:
        if heartbeat_seconds >= lease_seconds:
            raise ValueError("Workflow heartbeat must be shorter than its lease.")
        self._unit_of_work_factory = unit_of_work_factory
        self._inline_runner = inline_runner
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._now = now or (lambda: datetime.now(UTC))

    async def run_once(self) -> CoordinatorRunResult:
        workflow = await self._claim()
        if workflow is None:
            return CoordinatorRunResult(processed=False)
        return await self._advance(workflow.id)

    async def recover_expired(self) -> tuple[int, int]:
        now = self._aware_now()
        async with self._unit_of_work_factory() as unit_of_work:
            work_count = await unit_of_work.work_items.recover_expired_leases(now=now)
            workflow_count = await unit_of_work.workflows.recover_expired_leases(now=now)
            await unit_of_work.commit()
        return work_count, workflow_count

    async def _claim(self) -> WorkflowRun | None:
        now = self._aware_now()
        async with self._unit_of_work_factory() as unit_of_work:
            workflow = await unit_of_work.workflows.claim_next(
                worker_id=self._worker_id,
                now=now,
                lease_expires_at=now + timedelta(seconds=self._lease_seconds),
            )
            await unit_of_work.commit()
        return workflow

    async def _advance(self, workflow_run_id: int) -> CoordinatorRunResult:
        for _ in STAGES:
            inline_work_item_id: int | None = None
            async with self._unit_of_work_factory() as unit_of_work:
                workflow = await unit_of_work.workflows.get(workflow_run_id)
                if workflow is None:
                    return CoordinatorRunResult(
                        processed=True,
                        workflow_run_id=workflow_run_id,
                        status="missing",
                    )
                steps = await unit_of_work.workflows.list_steps(workflow_run_id)
                stage_name, step = _next_stage(steps)
                if stage_name is None:
                    completed = await unit_of_work.workflows.mark_succeeded(
                        workflow_run_id=workflow.id,
                        output_json=_workflow_output(steps),
                        now=self._aware_now(),
                    )
                    await unit_of_work.commit()
                    return _result(completed)

                item = await self._ensure_stage_item(
                    unit_of_work,
                    workflow=workflow,
                    steps=steps,
                    stage_name=stage_name,
                    step=step,
                )
                await unit_of_work.workflows.add_step(
                    workflow_run_id=workflow.id,
                    stage_name=stage_name,
                    position=STAGES.index(stage_name) + 1,
                    work_item_id=item.id,
                    status=item.status.value,
                    completed_at=(
                        item.completed_at if item.status in TERMINAL_WORK_ITEM_STATUSES else None
                    ),
                )
                if item.status is WorkItemStatus.SUCCEEDED:
                    if item.outcome_code is not None:
                        failed = await unit_of_work.workflows.mark_failed(
                            workflow_run_id=workflow.id,
                            error_code=item.outcome_code,
                            error_message=f"{stage_name} completed with {item.outcome_code}.",
                            blocked=True,
                            now=self._aware_now(),
                        )
                        await unit_of_work.commit()
                        return _result(failed)
                    if stage_name == ARCHIVE_PUBLISH_TASK:
                        refreshed_steps = await unit_of_work.workflows.list_steps(workflow.id)
                        completed = await unit_of_work.workflows.mark_succeeded(
                            workflow_run_id=workflow.id,
                            output_json=_workflow_output(refreshed_steps),
                            now=self._aware_now(),
                        )
                        await unit_of_work.commit()
                        return _result(completed)
                    await unit_of_work.commit()
                    continue

                if item.status in TERMINAL_WORK_ITEM_STATUSES:
                    failed = await unit_of_work.workflows.mark_failed(
                        workflow_run_id=workflow.id,
                        error_code=item.error_code or "dependency_failed",
                        error_message=item.error_message or f"{stage_name} did not succeed.",
                        blocked=item.status in {WorkItemStatus.BLOCKED, WorkItemStatus.CANCELED},
                        now=self._aware_now(),
                    )
                    await unit_of_work.commit()
                    return _result(failed)

                if stage_name == ARCHIVE_PUBLISH_TASK and item.status is WorkItemStatus.PENDING:
                    inline_work_item_id = item.id
                    await unit_of_work.commit()
                else:
                    waiting = await unit_of_work.workflows.set_waiting(
                        workflow_run_id=workflow.id,
                        current_stage=stage_name,
                        now=self._aware_now(),
                    )
                    await unit_of_work.commit()
                    return _result(waiting)

            if inline_work_item_id is not None:
                await self._run_inline_with_heartbeat(workflow_run_id, inline_work_item_id)
                continue

        raise RuntimeError("Workflow stage advancement exceeded the configured stage count.")

    async def _ensure_stage_item(
        self,
        unit_of_work: WorkUnitOfWorkPort,
        *,
        workflow: WorkflowRun,
        steps: list[WorkflowStep],
        stage_name: str,
        step: WorkflowStep | None,
    ) -> WorkItem:
        if step is not None and step.work_item_id is not None:
            existing = await unit_of_work.work_items.get(step.work_item_id)
            if existing is None:
                raise RuntimeError(f"Workflow step {step.id} references a missing work item.")
            if existing.status in {
                WorkItemStatus.FAILED,
                WorkItemStatus.TIMED_OUT,
                WorkItemStatus.BLOCKED,
            } and _option_bool(workflow, "retry_failed"):
                attempts = await unit_of_work.work_attempts.list_for_work_item(existing.id)
                if len(attempts) < 2:
                    return await unit_of_work.work_items.reset_for_retry(
                        work_item_id=existing.id,
                        now=self._aware_now(),
                        allow_succeeded=False,
                    )
            return existing

        dependency = await _dependency_item(unit_of_work, steps, stage_name)
        input_json = _stage_input(workflow, stage_name, dependency)
        input_hash = _hash(input_json)
        execution_mode = (
            WorkExecutionMode.INLINE
            if stage_name == ARCHIVE_PUBLISH_TASK
            else WorkExecutionMode.WORKER
        )
        item, _ = await unit_of_work.work_items.get_or_create(
            CreateWorkItem(
                task_type=stage_name,
                subject_type="video",
                subject_id=workflow.video_id,
                external_key=_option_str(workflow, "youtubeVideoId"),
                task_version=_stage_version(stage_name),
                input_hash=input_hash,
                idempotency_key=(
                    f"{stage_name}:video:{workflow.video_id}:"
                    f"{_stage_version(stage_name)}:{input_hash}"
                ),
                execution_mode=execution_mode,
                timeout_seconds=_stage_timeout(workflow, stage_name),
                input_json=input_json,
                available_at=self._aware_now(),
            )
        )
        if dependency is not None:
            await unit_of_work.work_items.add_dependency(
                work_item_id=item.id,
                dependency_work_item_id=dependency.id,
            )
        return item

    async def _run_inline_with_heartbeat(
        self,
        workflow_run_id: int,
        work_item_id: int,
    ) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_loop(workflow_run_id))
        try:
            await self._inline_runner.run(work_item_id)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat_loop(self, workflow_run_id: int) -> None:
        while True:
            await asyncio.sleep(float(self._heartbeat_seconds))
            now = self._aware_now()
            async with self._unit_of_work_factory() as unit_of_work:
                alive = await unit_of_work.workflows.heartbeat(
                    workflow_run_id=workflow_run_id,
                    worker_id=self._worker_id,
                    now=now,
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                )
                await unit_of_work.commit()
            if not alive:
                return

    def _aware_now(self) -> datetime:
        value = self._now()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _next_stage(steps: list[WorkflowStep]) -> tuple[str | None, WorkflowStep | None]:
    by_stage = {step.stage_name: step for step in steps}
    for stage in STAGES:
        step = by_stage.get(stage)
        if step is None or step.status != WorkItemStatus.SUCCEEDED.value:
            return stage, step
    return None, None


async def _dependency_item(
    unit_of_work: WorkUnitOfWorkPort,
    steps: list[WorkflowStep],
    stage_name: str,
) -> WorkItem | None:
    position = STAGES.index(stage_name)
    if position == 0:
        return None
    previous = next((step for step in steps if step.stage_name == STAGES[position - 1]), None)
    if previous is None or previous.work_item_id is None:
        raise RuntimeError(f"{stage_name} cannot be created without its preceding workflow step.")
    item = await unit_of_work.work_items.get(previous.work_item_id)
    if item is None or item.status is not WorkItemStatus.SUCCEEDED:
        raise RuntimeError(f"{stage_name} dependency is not ready.")
    return item


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
    if stage_name == TRANSCRIPT_COLLECT_TASK:
        return {
            **base,
            "languages": _option_str_list(workflow, "languages"),
            "preserveFormatting": _option_bool(workflow, "preserve_formatting"),
        }
    if dependency is None:
        raise RuntimeError(f"{stage_name} requires a dependency.")
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
    return {
        **base,
        "sourceTimelineWorkItemId": dependency.id,
        "publishMode": _option_str(workflow, "publish_mode"),
        "environment": _option_str(workflow, "environment"),
        "variant": _option_str(workflow, "variant"),
        "schemaVersion": _option_int(workflow, "schema_version"),
    }


def _stage_version(stage_name: str) -> str:
    return {
        TRANSCRIPT_COLLECT_TASK: TRANSCRIPT_COLLECT_VERSION,
        TRANSCRIPT_CUE_TASK: TRANSCRIPT_CUE_VERSION,
        MICRO_EVENT_TASK: MICRO_EVENT_VERSION,
        TIMELINE_TASK: TIMELINE_VERSION,
        ARCHIVE_PUBLISH_TASK: ARCHIVE_PUBLISH_VERSION,
    }[stage_name]


def _stage_timeout(workflow: WorkflowRun, stage_name: str) -> int:
    key = {
        TRANSCRIPT_COLLECT_TASK: "transcript_timeout_seconds",
        TRANSCRIPT_CUE_TASK: "cue_timeout_seconds",
        MICRO_EVENT_TASK: "micro_timeout_seconds",
        TIMELINE_TASK: "timeline_timeout_seconds",
        ARCHIVE_PUBLISH_TASK: "archive_timeout_seconds",
    }[stage_name]
    return _option_int(workflow, key)


def _workflow_output(steps: list[WorkflowStep]) -> JsonObject:
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


def _result(workflow: WorkflowRun) -> CoordinatorRunResult:
    return CoordinatorRunResult(
        processed=True,
        workflow_run_id=workflow.id,
        status=workflow.status.value,
        current_stage=workflow.current_stage,
    )


def _required_output_int(item: WorkItem, key: str) -> int:
    value = item.output_json.get(key) if item.output_json is not None else None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if key == "transcriptId" and item.output_transcript_id is not None:
        return item.output_transcript_id
    raise RuntimeError(f"Work item {item.id} has no integer {key} output.")


def _required_output_str(item: WorkItem, key: str) -> str:
    value = item.output_json.get(key) if item.output_json is not None else None
    if isinstance(value, str) and value:
        return value
    raise RuntimeError(f"Work item {item.id} has no string {key} output.")


def _option_str(workflow: WorkflowRun, key: str) -> str:
    value = workflow.options_json.get(key)
    if isinstance(value, str) and value:
        return value
    raise RuntimeError(f"Workflow option {key} must be a non-empty string.")


def _option_str_list(workflow: WorkflowRun, key: str) -> list[str]:
    value = workflow.options_json.get(key)
    if isinstance(value, (list, tuple)) and value and all(
        isinstance(item, str) and item for item in value
    ):
        return list(value)
    raise RuntimeError(f"Workflow option {key} must be a non-empty string list.")


def _option_bool(workflow: WorkflowRun, key: str) -> bool:
    value = workflow.options_json.get(key)
    if isinstance(value, bool):
        return value
    raise RuntimeError(f"Workflow option {key} must be a boolean.")


def _option_int(workflow: WorkflowRun, key: str) -> int:
    value = workflow.options_json.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise RuntimeError(f"Workflow option {key} must be an integer.")


def _option_optional_int(workflow: WorkflowRun, key: str) -> int | None:
    value = workflow.options_json.get(key)
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise RuntimeError(f"Workflow option {key} must be an integer or null.")


def _hash(values: JsonObject) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
