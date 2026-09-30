from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from codex_sdk_cli.application.operations.results import OperationBatchResult, OperationItem
from codex_sdk_cli.application.operations.selection import VideoSelection, VideoSelectionPort
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import CreateWorkBatch, CreateWorkItem
from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.segments.models import (
    SEGMENT_TASK,
    SEGMENT_TASK_VERSION,
    TAXONOMY_VERSION,
    fingerprint,
)
from codex_sdk_cli.domains.work.models import WorkBatchStatus, WorkExecutionMode, WorkItemStatus

from .ports import SegmentInputPlannerPort


@dataclass(frozen=True, slots=True)
class ClassifySegmentsCommand:
    selection: VideoSelection
    model: CodexModelChoice = "gpt-6-luna"
    reasoning_effort: ReasoningEffortChoice = "high"
    prompt_version_id: int | None = None
    taxonomy_version: str = TAXONOMY_VERSION
    retry_failed: bool = False
    rerun_succeeded: bool = False
    include_non_embeddable: bool = False
    timeout_seconds: int = 600
    actor_type: str = "manual_api"


class ClassifySegmentsUseCase:
    def __init__(
        self,
        *,
        videos: VideoSelectionPort,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        planner: SegmentInputPlannerPort,
    ) -> None:
        self._videos = videos
        self._unit_of_work_factory = unit_of_work_factory
        self._planner = planner

    async def execute(self, command: ClassifySegmentsCommand) -> OperationBatchResult:
        videos = await self._videos.select(command.selection)
        now = datetime.now(UTC)
        items: list[OperationItem] = []
        created_count = reused_count = 0
        async with self._unit_of_work_factory() as uow:
            batch = await uow.work_batches.create(
                CreateWorkBatch(
                    operation_type=SEGMENT_TASK,
                    actor_type=command.actor_type,
                    selection_json={
                        "kind": type(command.selection).__name__,
                        **asdict(command.selection),
                    },
                    options_json={
                        k: v
                        for k, v in asdict(command).items()
                        if k not in {"selection", "actor_type"}
                    },
                    requested_count=len(videos),
                )
            )
            for position, video in enumerate(videos, 1):
                source = await uow.work_items.find_latest(
                    task_type="timeline_compose",
                    subject_type="video",
                    subject_id=video.id,
                    status=WorkItemStatus.SUCCEEDED,
                )
                if (
                    (video.is_embeddable is False and not command.include_non_embeddable)
                    or source is None
                    or source.outcome_code is not None
                ):
                    reason = (
                        "not_embeddable" if video.is_embeddable is False else "timeline_not_ready"
                    )
                    item = OperationItem(video.id, video.youtube_video_id, "skipped", reason, None)
                else:
                    values = await self._planner.prepare(
                        video_id=video.id,
                        timeline_work_item_id=source.id,
                        model=command.model,
                        reasoning_effort=command.reasoning_effort,
                        prompt_version_id=command.prompt_version_id,
                        taxonomy_version=command.taxonomy_version,
                    )
                    digest = fingerprint(values)
                    work, created = await uow.work_items.get_or_create(
                        CreateWorkItem(
                            task_type=SEGMENT_TASK,
                            subject_type="video",
                            subject_id=video.id,
                            external_key=video.youtube_video_id,
                            task_version=SEGMENT_TASK_VERSION,
                            input_hash=digest,
                            idempotency_key=f"{SEGMENT_TASK}:video:{video.id}:{SEGMENT_TASK_VERSION}:{digest}",
                            execution_mode=WorkExecutionMode.WORKER,
                            timeout_seconds=command.timeout_seconds,
                            input_json=values,
                            available_at=now,
                        )
                    )
                    await uow.work_items.add_dependency(
                        work_item_id=work.id, dependency_work_item_id=source.id
                    )
                    failed = work.status in {
                        WorkItemStatus.FAILED,
                        WorkItemStatus.TIMED_OUT,
                        WorkItemStatus.BLOCKED,
                        WorkItemStatus.CANCELED,
                    }
                    rerun = work.status is WorkItemStatus.SUCCEEDED and command.rerun_succeeded
                    if not created and ((failed and command.retry_failed) or rerun):
                        work = await uow.work_items.reset_for_retry(
                            work_item_id=work.id,
                            now=now,
                            allow_succeeded=rerun,
                        )
                    created_count += int(created)
                    reused_count += int(not created)
                    item = OperationItem(
                        video.id,
                        video.youtube_video_id,
                        work.status.value,
                        "enqueued" if created else "reused",
                        work.id,
                    )
                items.append(item)
                await uow.work_batches.add_item(
                    batch_id=batch.id,
                    position=position,
                    video_id=video.id,
                    work_item_id=item.work_item_id,
                    workflow_run_id=None,
                    selection_status=item.status,
                    reason=item.reason,
                )
            await uow.work_batches.complete(
                batch_id=batch.id, status=WorkBatchStatus.SUCCEEDED.value, completed_at=now
            )
            await uow.commit()
        return OperationBatchResult(
            batch.id,
            len(items),
            created_count,
            reused_count,
            sum(i.status == "skipped" for i in items),
            tuple(items),
        )
