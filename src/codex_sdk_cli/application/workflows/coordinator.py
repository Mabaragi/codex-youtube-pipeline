from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from codex_sdk_cli.application.asr.executors import ASR_TRANSCRIBE_TASK
from codex_sdk_cli.application.processing.commands import (
    MICRO_EVENT_TASK,
    TIMELINE_TASK,
)
from codex_sdk_cli.application.transcripts.commands import (
    TRANSCRIPT_COLLECT_TASK,
    TRANSCRIPT_CUE_TASK,
)
from codex_sdk_cli.application.work.execution import WorkRunResult, WorkUnitOfWorkFactory
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

from .artifact_reuse import reuse_transcript_artifact
from .models import CoordinatorRunResult
from .models import coordinator_result as _result
from .models import workflow_output as _workflow_output
from .options import (
    aware_datetime as _aware_datetime,
)
from .options import (
    input_int as _input_int,
)
from .options import (
    option_bool as _option_bool,
)
from .options import (
    option_bool_default as _option_bool_default,
)
from .options import (
    option_int as _option_int,
)
from .options import (
    option_int_default as _option_int_default,
)
from .options import (
    option_optional_int as _option_optional_int,
)
from .options import (
    option_str as _option_str,
)
from .options import (
    option_str_default as _option_str_default,
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
from .ports import InlineWorkRunnerPort, TranscriptArtifactReaderPort
from .publish import wait_for_archive_publish_resume
from .stage_policy import (
    ARCHIVE_PUBLISH_TASK,
    STAGES,
    TRANSCRIPT_RECHECK_STAGE,
    V2_STAGES,
)
from .stage_policy import stage_available_at as _stage_available_at
from .stage_policy import stage_position as _stage_position
from .stage_policy import stage_task_type as _stage_task_type
from .stage_policy import stage_timeout as _stage_timeout
from .stage_policy import stage_version as _stage_version
from .stage_policy import transcript_recheck_deadline as _transcript_recheck_deadline

Now = Callable[[], datetime]


class ProcessToPublishCoordinator:
    def __init__(
        self,
        *,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        inline_runner: InlineWorkRunnerPort,
        transcript_artifacts: TranscriptArtifactReaderPort | None = None,
        worker_id: str,
        lease_seconds: int = 90,
        heartbeat_seconds: int = 30,
        now: Now | None = None,
    ) -> None:
        if heartbeat_seconds >= lease_seconds:
            raise ValueError("Workflow heartbeat must be shorter than its lease.")
        self._unit_of_work_factory = unit_of_work_factory
        self._inline_runner = inline_runner
        self._transcript_artifacts = transcript_artifacts
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
        for _ in V2_STAGES:
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
                step_items = await _step_items(unit_of_work, steps)
                stage_name, step = _next_stage(workflow, steps, step_items)
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
                    step_items=step_items,
                    stage_name=stage_name,
                    step=step,
                )
                await unit_of_work.workflows.add_step(
                    workflow_run_id=workflow.id,
                    stage_name=stage_name,
                    position=_stage_position(workflow, stage_name),
                    work_item_id=item.id,
                    status=item.status.value,
                    completed_at=(
                        item.completed_at if item.status in TERMINAL_WORK_ITEM_STATUSES else None
                    ),
                )
                if item.status is WorkItemStatus.SUCCEEDED:
                    completed = await self._handle_succeeded(
                        unit_of_work,
                        workflow=workflow,
                        step_items=step_items,
                        stage_name=stage_name,
                        item=item,
                    )
                    if completed is not None:
                        return completed
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
                        available_at=(
                            _aware_datetime(item.available_at)
                            if _aware_datetime(item.available_at) > self._aware_now()
                            else self._aware_now()
                        ),
                    )
                    await unit_of_work.commit()
                    return _result(waiting)

            if inline_work_item_id is not None:
                inline_result = await self._run_inline_with_heartbeat(
                    workflow_run_id, inline_work_item_id
                )
                if not inline_result.processed:
                    return await wait_for_archive_publish_resume(
                        self._unit_of_work_factory,
                        workflow_run_id=workflow_run_id,
                        now=self._aware_now(),
                    )
                continue

        raise RuntimeError("Workflow stage advancement exceeded the configured stage count.")

    async def _handle_succeeded(
        self,
        unit_of_work: WorkUnitOfWorkPort,
        *,
        workflow: WorkflowRun,
        step_items: dict[str, WorkItem],
        stage_name: str,
        item: WorkItem,
    ) -> CoordinatorRunResult | None:
        if item.outcome_code is not None:
            if _is_v2_no_transcript_branch(workflow, stage_name, item):
                if stage_name == TRANSCRIPT_RECHECK_STAGE:
                    waiting = await self._repeat_transcript_recheck(
                        unit_of_work,
                        workflow=workflow,
                        step_items=step_items,
                        item=item,
                    )
                    if waiting is not None:
                        return waiting
                await unit_of_work.commit()
                return None
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
        return None

    async def _repeat_transcript_recheck(
        self,
        unit_of_work: WorkUnitOfWorkPort,
        *,
        workflow: WorkflowRun,
        step_items: dict[str, WorkItem],
        item: WorkItem,
    ) -> CoordinatorRunResult | None:
        initial = step_items.get(TRANSCRIPT_COLLECT_TASK)
        if initial is None or initial.completed_at is None:
            raise RuntimeError("Transcript recheck requires a completed initial transcript check.")
        if item.completed_at is None:
            raise RuntimeError("Succeeded transcript recheck has no completion timestamp.")
        deadline = _transcript_recheck_deadline(workflow, initial)
        completed_at = _aware_datetime(item.completed_at)
        if completed_at >= deadline:
            return None
        interval = timedelta(
            seconds=_option_int_default(
                workflow,
                "transcript_recheck_interval_seconds",
                1800,
            )
        )
        target = min(completed_at + interval, deadline)
        now = self._aware_now()
        pending = await unit_of_work.work_items.reset_for_retry(
            work_item_id=item.id,
            now=now,
            allow_succeeded=True,
            available_at=max(now, target),
        )
        await unit_of_work.workflows.add_step(
            workflow_run_id=workflow.id,
            stage_name=TRANSCRIPT_RECHECK_STAGE,
            position=_stage_position(workflow, TRANSCRIPT_RECHECK_STAGE),
            work_item_id=pending.id,
            status=pending.status.value,
            completed_at=None,
        )
        waiting = await unit_of_work.workflows.set_waiting(
            workflow_run_id=workflow.id,
            current_stage=TRANSCRIPT_RECHECK_STAGE,
            now=now,
            available_at=pending.available_at,
        )
        await unit_of_work.commit()
        return _result(waiting)

    async def _ensure_stage_item(
        self,
        unit_of_work: WorkUnitOfWorkPort,
        *,
        workflow: WorkflowRun,
        steps: list[WorkflowStep],
        step_items: dict[str, WorkItem],
        stage_name: str,
        step: WorkflowStep | None,
    ) -> WorkItem:
        if step is not None and step.work_item_id is not None:
            existing = await unit_of_work.work_items.get(step.work_item_id)
            if existing is None:
                raise RuntimeError(f"Workflow step {step.id} references a missing work item.")
            reused = await reuse_transcript_artifact(
                unit_of_work,
                reader=self._transcript_artifacts,
                stage_name=stage_name,
                video_id=workflow.video_id,
                youtube_video_id=_option_str(workflow, "youtubeVideoId"),
                timeout_seconds=_stage_timeout(workflow, stage_name),
                now=self._aware_now(),
                existing=existing,
            )
            if reused is not None:
                return reused
            if existing.status in {
                WorkItemStatus.FAILED,
                WorkItemStatus.TIMED_OUT,
                WorkItemStatus.BLOCKED,
            } and _option_bool(workflow, "retry_failed"):
                attempts = await unit_of_work.work_attempts.list_for_work_item(existing.id)
                if len(attempts) < 3:
                    return await unit_of_work.work_items.reset_for_retry(
                        work_item_id=existing.id,
                        now=self._aware_now(),
                        allow_succeeded=False,
                    )
            return existing

        dependency = await _dependency_item(
            unit_of_work,
            workflow=workflow,
            steps=steps,
            step_items=step_items,
            stage_name=stage_name,
        )
        task_type = _stage_task_type(stage_name)
        if _option_bool_default(workflow, "reuse_successful_stages", False):
            reusable = await unit_of_work.work_items.find_latest(
                task_type=task_type,
                subject_type="video",
                subject_id=workflow.video_id,
                status=WorkItemStatus.SUCCEEDED,
            )
            if reusable is not None and _can_reuse(reusable, stage_name, dependency):
                return reusable
        reused = await reuse_transcript_artifact(
            unit_of_work,
            reader=self._transcript_artifacts,
            stage_name=stage_name,
            video_id=workflow.video_id,
            youtube_video_id=_option_str(workflow, "youtubeVideoId"),
            timeout_seconds=_stage_timeout(workflow, stage_name),
            now=self._aware_now(),
        )
        if reused is not None:
            return reused
        input_json = _stage_input(workflow, stage_name, dependency)
        input_hash = _hash(input_json)
        execution_mode = (
            WorkExecutionMode.INLINE
            if stage_name == ARCHIVE_PUBLISH_TASK
            else WorkExecutionMode.WORKER
        )
        item, _ = await unit_of_work.work_items.get_or_create(
            CreateWorkItem(
                task_type=task_type,
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
                available_at=_stage_available_at(
                    workflow,
                    stage_name,
                    self._aware_now(),
                    dependency,
                ),
            )
        )
        if dependency is not None:
            await unit_of_work.work_items.add_dependency(
                work_item_id=item.id,
                dependency_work_item_id=dependency.id,
                requires_successful_output=stage_name
                not in {TRANSCRIPT_RECHECK_STAGE, ASR_TRANSCRIBE_TASK},
            )
        return item

    async def _run_inline_with_heartbeat(
        self, workflow_run_id: int, work_item_id: int
    ) -> WorkRunResult:
        heartbeat = asyncio.create_task(self._heartbeat_loop(workflow_run_id))
        try:
            return await self._inline_runner.run(work_item_id)
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


def _next_stage(
    workflow: WorkflowRun,
    steps: list[WorkflowStep],
    items: dict[str, WorkItem],
) -> tuple[str | None, WorkflowStep | None]:
    by_stage = {step.stage_name: step for step in steps}
    changed = _out_of_sync_step(steps, items)
    if changed is not None:
        return changed.stage_name, changed
    if workflow.workflow_version != "v2":
        return _first_incomplete(STAGES, by_stage)
    transcript_stage = _next_v2_transcript_stage(workflow, items)
    if transcript_stage is not None:
        return transcript_stage, by_stage.get(transcript_stage)

    for stage in (
        TRANSCRIPT_CUE_TASK,
        MICRO_EVENT_TASK,
        TIMELINE_TASK,
        ARCHIVE_PUBLISH_TASK,
    ):
        if not _succeeded(items.get(stage)):
            return stage, by_stage.get(stage)
    return None, None


def _out_of_sync_step(
    steps: list[WorkflowStep],
    items: dict[str, WorkItem],
) -> WorkflowStep | None:
    return next(
        (
            step
            for step in steps
            if (item := items.get(step.stage_name)) is not None and step.status != item.status.value
        ),
        None,
    )


def _next_v2_transcript_stage(
    workflow: WorkflowRun,
    items: dict[str, WorkItem],
) -> str | None:
    transcript = items.get(TRANSCRIPT_COLLECT_TASK)
    if not _succeeded(transcript):
        return TRANSCRIPT_COLLECT_TASK
    if transcript is None or transcript.outcome_code != "no_transcript":
        return None
    if _option_str_default(workflow, "transcript_fallback_mode", "disabled") == "disabled":
        return TRANSCRIPT_COLLECT_TASK
    recheck = items.get(TRANSCRIPT_RECHECK_STAGE)
    if not _succeeded(recheck):
        return TRANSCRIPT_RECHECK_STAGE
    if recheck is None or recheck.outcome_code != "no_transcript":
        return None
    return ASR_TRANSCRIBE_TASK if not _succeeded(items.get(ASR_TRANSCRIBE_TASK)) else None


def _first_incomplete(
    stages: tuple[str, ...],
    by_stage: dict[str, WorkflowStep],
) -> tuple[str | None, WorkflowStep | None]:
    for stage in stages:
        step = by_stage.get(stage)
        if step is None or step.status != WorkItemStatus.SUCCEEDED.value:
            return stage, step
    return None, None


async def _step_items(
    unit_of_work: WorkUnitOfWorkPort,
    steps: list[WorkflowStep],
) -> dict[str, WorkItem]:
    result: dict[str, WorkItem] = {}
    for step in steps:
        if step.work_item_id is None:
            continue
        item = await unit_of_work.work_items.get(step.work_item_id)
        if item is not None:
            result[step.stage_name] = item
    return result


async def _dependency_item(
    unit_of_work: WorkUnitOfWorkPort,
    *,
    workflow: WorkflowRun,
    steps: list[WorkflowStep],
    step_items: dict[str, WorkItem],
    stage_name: str,
) -> WorkItem | None:
    if stage_name == TRANSCRIPT_COLLECT_TASK:
        return None
    if workflow.workflow_version != "v2":
        position = STAGES.index(stage_name)
        previous_stage = STAGES[position - 1]
    else:
        previous_stage = _v2_dependency_stage(stage_name, step_items)
    previous = next((step for step in steps if step.stage_name == previous_stage), None)
    if previous is None or previous.work_item_id is None:
        raise RuntimeError(f"{stage_name} cannot be created without its preceding workflow step.")
    item = await unit_of_work.work_items.get(previous.work_item_id)
    if item is None or item.status is not WorkItemStatus.SUCCEEDED:
        raise RuntimeError(f"{stage_name} dependency is not ready.")
    return item


def _v2_dependency_stage(stage_name: str, items: dict[str, WorkItem]) -> str:
    if stage_name == TRANSCRIPT_RECHECK_STAGE:
        return TRANSCRIPT_COLLECT_TASK
    if stage_name == ASR_TRANSCRIBE_TASK:
        return TRANSCRIPT_RECHECK_STAGE
    if stage_name == TRANSCRIPT_CUE_TASK:
        asr = items.get(ASR_TRANSCRIBE_TASK)
        if _succeeded(asr) and asr is not None and asr.outcome_code is None:
            return ASR_TRANSCRIBE_TASK
        recheck = items.get(TRANSCRIPT_RECHECK_STAGE)
        if _succeeded(recheck) and recheck is not None and recheck.outcome_code is None:
            return TRANSCRIPT_RECHECK_STAGE
        return TRANSCRIPT_COLLECT_TASK
    return {
        MICRO_EVENT_TASK: TRANSCRIPT_CUE_TASK,
        TIMELINE_TASK: MICRO_EVENT_TASK,
        ARCHIVE_PUBLISH_TASK: TIMELINE_TASK,
    }[stage_name]


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
    return {
        **base,
        "sourceTimelineWorkItemId": dependency.id,
        "publishMode": _option_str(workflow, "publish_mode"),
        "environment": _option_str(workflow, "environment"),
        "variant": _option_str(workflow, "variant"),
        "schemaVersion": _option_int(workflow, "schema_version"),
    }


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


def _is_v2_no_transcript_branch(
    workflow: WorkflowRun,
    stage_name: str,
    item: WorkItem,
) -> bool:
    return (
        workflow.workflow_version == "v2"
        and stage_name in {TRANSCRIPT_COLLECT_TASK, TRANSCRIPT_RECHECK_STAGE}
        and item.outcome_code == "no_transcript"
        and _option_str_default(workflow, "transcript_fallback_mode", "disabled")
        == "asr_after_grace"
    )


def _succeeded(item: WorkItem | None) -> bool:
    return item is not None and item.status is WorkItemStatus.SUCCEEDED


def _hash(values: JsonObject) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
