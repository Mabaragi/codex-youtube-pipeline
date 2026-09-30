from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from codex_sdk_cli.application.operations.selection import VideoSelectionPort
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import (
    CreateWorkBatch,
    CreateWorkflowRun,
    WorkUnitOfWorkPort,
)
from codex_sdk_cli.application.workflows.models import WorkflowBatchResult, WorkflowSelectionItem
from codex_sdk_cli.domains.segments.models import fingerprint
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.work.models import WorkBatchStatus, WorkItemStatus

from .commands import ClassifySegmentsCommand
from .ports import SegmentInputPlannerPort, SegmentPublishedTimelineReaderPort

BACKFILL_WORKFLOW = "classify_to_publish"


@dataclass(frozen=True, slots=True)
class BackfillSegmentsCommand:
    classification: ClassifySegmentsCommand
    publish_mode: str = "prod"
    environment: str = "prod"
    variant: str = "control"
    schema_version: int = 1
    archive_timeout_seconds: int = 600


class BackfillSegmentsUseCase:
    def __init__(
        self,
        *,
        videos: VideoSelectionPort,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        planner: SegmentInputPlannerPort,
        published_sources: SegmentPublishedTimelineReaderPort,
    ) -> None:
        self._videos = videos
        self._unit_of_work_factory = unit_of_work_factory
        self._planner = planner
        self._published_sources = published_sources

    async def execute(self, command: BackfillSegmentsCommand) -> WorkflowBatchResult:
        classification = command.classification
        videos = await self._videos.select(classification.selection)
        items = []
        created_count = 0
        async with self._unit_of_work_factory() as unit:
            batch = await unit.work_batches.create(
                CreateWorkBatch(
                    operation_type=BACKFILL_WORKFLOW,
                    actor_type=classification.actor_type,
                    selection_json=asdict(classification.selection),
                    options_json={
                        "model": classification.model,
                        "reasoningEffort": classification.reasoning_effort,
                        "publishMode": command.publish_mode,
                        "environment": command.environment,
                        "variant": command.variant,
                        "schemaVersion": command.schema_version,
                    },
                    requested_count=len(videos),
                )
            )
            for position, video in enumerate(videos, 1):
                item, created = await self._prepare_video(unit, video, command)
                items.append(item)
                created_count += int(created)
                await unit.work_batches.add_item(
                    batch_id=batch.id,
                    position=position,
                    video_id=video.id,
                    work_item_id=None,
                    workflow_run_id=item.workflow_run_id,
                    selection_status=item.status,
                    reason=item.reason,
                )
            await unit.work_batches.complete(
                batch_id=batch.id,
                status=WorkBatchStatus.SUCCEEDED.value,
                completed_at=datetime.now(UTC),
            )
            await unit.commit()
        skipped = sum(item.status == "skipped" for item in items)
        return WorkflowBatchResult(
            batch.id,
            len(items),
            created_count,
            len(items) - created_count - skipped,
            skipped,
            tuple(items),
        )

    async def _prepare_video(
        self, unit: WorkUnitOfWorkPort, video: VideoRecord, command: BackfillSegmentsCommand
    ) -> tuple[WorkflowSelectionItem, bool]:
        classification = command.classification
        source_id = await self._published_sources.latest(
            video_id=video.id,
            environment=command.environment,
            variant=command.variant,
            schema_version=command.schema_version,
        )
        source = await unit.work_items.get(source_id) if source_id is not None else None
        if (
            (video.is_embeddable is False and not classification.include_non_embeddable)
            or source is None
            or source.status is not WorkItemStatus.SUCCEEDED
            or source.outcome_code is not None
        ):
            return WorkflowSelectionItem(
                video.id, video.youtube_video_id, "skipped", "timeline_not_eligible", None
            ), False
        frozen = await self._planner.prepare(
            video_id=video.id,
            timeline_work_item_id=source.id,
            model=classification.model,
            reasoning_effort=classification.reasoning_effort,
            prompt_version_id=classification.prompt_version_id,
            taxonomy_version=classification.taxonomy_version,
        )
        options: dict[str, object] = {
            "videoId": video.id,
            "youtubeVideoId": video.youtube_video_id,
            "sourceTimelineWorkItemId": source.id,
            "segmentInput": frozen,
            "segment_timeout_seconds": classification.timeout_seconds,
            "archive_timeout_seconds": command.archive_timeout_seconds,
            "retry_failed": True,
            "reuse_successful_stages": True,
            "publish_mode": command.publish_mode,
            "environment": command.environment,
            "variant": command.variant,
            "schema_version": command.schema_version,
        }
        workflow, created = await unit.workflows.create_or_get(
            CreateWorkflowRun(
                workflow_type=BACKFILL_WORKFLOW,
                workflow_version="v3",
                video_id=video.id,
                input_hash=fingerprint(options),
                options_json=options,
                available_at=datetime.now(UTC),
            )
        )
        if (
            not created
            and classification.retry_failed
            and workflow.status.value in {"failed", "blocked"}
        ):
            # An explicit retry starts another attempt even after automatic retries
            # are exhausted. Keep successful stages and all attempt history.
            for step in await unit.workflows.list_steps(workflow.id):
                work = await unit.work_items.get(step.work_item_id) if step.work_item_id else None
                if work is not None and work.status in {
                    WorkItemStatus.FAILED,
                    WorkItemStatus.TIMED_OUT,
                    WorkItemStatus.BLOCKED,
                }:
                    await unit.work_items.reset_for_retry(
                        work_item_id=work.id, now=datetime.now(UTC), allow_succeeded=False
                    )
            workflow = await unit.workflows.reset_for_retry(
                workflow_run_id=workflow.id, now=datetime.now(UTC)
            )
        return WorkflowSelectionItem(
            video.id,
            video.youtube_video_id,
            workflow.status.value,
            "created" if created else "reused",
            workflow.id,
        ), created
