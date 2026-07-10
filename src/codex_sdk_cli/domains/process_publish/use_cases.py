from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from codex_sdk_cli.domains.archive_publish.schemas import (
    ArchivePublishItemResponse,
    ArchivePublishRequest,
    ArchivePublishResponse,
)
from codex_sdk_cli.domains.micro_events.schemas import (
    MicroEventEnqueueItemResponse,
    MicroEventEnqueueRequest,
    MicroEventEnqueueResponse,
)
from codex_sdk_cli.domains.timelines.schemas import (
    TimelineComposeEnqueueItemResponse,
    TimelineComposeEnqueueRequest,
    TimelineComposeEnqueueResponse,
)
from codex_sdk_cli.domains.video_tasks.ports import (
    VideoTaskRecord,
)

from .schemas import (
    ProcessToPublishItemResponse,
    ProcessToPublishRequest,
    ProcessToPublishResponse,
    ProcessToPublishStageResponse,
)

_ACTIVE_TASK_STATUSES = {"pending", "running"}
_MICRO_SUCCESS_REASONS = {"already_succeeded"}
_TIMELINE_SUCCESS_REASONS = {"already_succeeded"}
_PUBLISH_SUCCESS_REASONS = {"already_published"}
_WAIT_REASONS = {
    "already_pending",
    "already_running",
    "enqueued",
    "requeued",
    "retry_queued",
}


class MicroEventEnqueuePort(Protocol):
    async def enqueue(self, request: MicroEventEnqueueRequest) -> MicroEventEnqueueResponse:
        ...


class TimelineEnqueuePort(Protocol):
    async def enqueue(
        self,
        request: TimelineComposeEnqueueRequest,
    ) -> TimelineComposeEnqueueResponse:
        ...


class ArchivePublishPort(Protocol):
    async def publish(self, request: ArchivePublishRequest) -> ArchivePublishResponse:
        ...


class VideoTaskReaderPort(Protocol):
    async def get_task(self, task_id: int) -> VideoTaskRecord | None:
        ...


@dataclass(slots=True)
class _WaitResult:
    stage: ProcessToPublishStageResponse
    succeeded: bool
    timeout: bool = False


class ProcessToPublishUseCase:
    def __init__(
        self,
        *,
        micro_events: MicroEventEnqueuePort,
        timelines: TimelineEnqueuePort,
        archive_publish: ArchivePublishPort,
        video_tasks: VideoTaskReaderPort,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._micro_events = micro_events
        self._timelines = timelines
        self._archive_publish = archive_publish
        self._video_tasks = video_tasks
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        request: ProcessToPublishRequest,
    ) -> ProcessToPublishResponse:
        video_ids = _dedupe_preserving_order(request.video_ids)
        items = {
            video_id: ProcessToPublishItemResponse(
                videoId=video_id,
                youtubeVideoId=None,
                status="pending",
                reason="pending",
            )
            for video_id in video_ids
        }

        micro_response = await self._micro_events.enqueue(
            MicroEventEnqueueRequest(
                target="selected_videos",
                videoIds=video_ids,
                limit=len(video_ids),
                retryFailed=request.retry_failed,
                reasoningEffort=request.micro_reasoning,
            )
        )
        micro_success_ids: list[int] = []
        for enqueue_item in micro_response.items:
            item = items[enqueue_item.video_id]
            item.youtube_video_id = enqueue_item.youtube_video_id
            wait = await self._resolve_micro_stage(enqueue_item, request)
            item.micro = wait.stage
            if wait.succeeded:
                item.status = "pending"
                item.reason = "micro_succeeded"
                micro_success_ids.append(enqueue_item.video_id)
            else:
                item.status = "failed" if wait.timeout else "skipped"
                item.reason = wait.stage.reason or "micro_failed"

        if micro_success_ids:
            timeline_response = await self._timelines.enqueue(
                TimelineComposeEnqueueRequest(
                    target="selected_videos",
                    videoIds=micro_success_ids,
                    limit=len(micro_success_ids),
                    retryFailed=request.retry_failed,
                    reasoningEffort=request.timeline_reasoning,
                )
            )
            timeline_success_ids: list[int] = []
            for enqueue_item in timeline_response.items:
                item = items[enqueue_item.video_id]
                item.youtube_video_id = item.youtube_video_id or enqueue_item.youtube_video_id
                wait = await self._resolve_timeline_stage(enqueue_item, request)
                item.timeline = wait.stage
                if wait.succeeded:
                    item.status = "pending"
                    item.reason = "timeline_succeeded"
                    timeline_success_ids.append(enqueue_item.video_id)
                else:
                    item.status = "failed" if wait.timeout else "skipped"
                    item.reason = wait.stage.reason or "timeline_failed"
        else:
            timeline_success_ids = []

        if timeline_success_ids:
            publish_response = await self._archive_publish.publish(
                _archive_publish_request(request, timeline_success_ids)
            )
            for publish_item in publish_response.items:
                item = items[publish_item.video_id]
                item.youtube_video_id = item.youtube_video_id or publish_item.youtube_video_id
                stage = _publish_stage_response(publish_item)
                item.publish = stage
                if _publish_succeeded(publish_item):
                    item.status = "succeeded"
                    item.reason = publish_item.reason
                else:
                    item.status = "skipped" if publish_item.status == "skipped" else "failed"
                    item.reason = publish_item.reason

        for item in items.values():
            if item.status == "pending":
                item.status = "skipped"
                item.reason = "not_reached"

        ordered_items = [items[video_id] for video_id in video_ids]
        return ProcessToPublishResponse(
            requestedCount=len(video_ids),
            microSucceededCount=sum(_stage_succeeded(item.micro) for item in ordered_items),
            timelineSucceededCount=sum(
                _stage_succeeded(item.timeline) for item in ordered_items
            ),
            publishedCount=sum(item.status == "succeeded" for item in ordered_items),
            failedCount=sum(item.status == "failed" for item in ordered_items),
            skippedCount=sum(item.status == "skipped" for item in ordered_items),
            items=ordered_items,
        )

    async def _resolve_micro_stage(
        self,
        item: MicroEventEnqueueItemResponse,
        request: ProcessToPublishRequest,
    ) -> _WaitResult:
        stage = _micro_stage_response(item)
        if _micro_succeeded(item):
            return _WaitResult(
                stage=await self._stage_with_task_details(stage),
                succeeded=True,
            )
        if _should_wait(item.video_task_id, item.status, item.reason):
            return await self._wait_for_task(
                stage,
                reason_prefix="micro",
                timeout_reason="micro_wait_timeout",
                request=request,
            )
        return _WaitResult(stage=stage, succeeded=False)

    async def _resolve_timeline_stage(
        self,
        item: TimelineComposeEnqueueItemResponse,
        request: ProcessToPublishRequest,
    ) -> _WaitResult:
        stage = _timeline_stage_response(item)
        if _timeline_succeeded(item):
            return _WaitResult(
                stage=await self._stage_with_task_details(stage),
                succeeded=True,
            )
        if _should_wait(item.video_task_id, item.status, item.reason):
            return await self._wait_for_task(
                stage,
                reason_prefix="timeline",
                timeout_reason="timeline_wait_timeout",
                request=request,
            )
        return _WaitResult(stage=stage, succeeded=False)

    async def _wait_for_task(
        self,
        stage: ProcessToPublishStageResponse,
        *,
        reason_prefix: str,
        timeout_reason: str,
        request: ProcessToPublishRequest,
    ) -> _WaitResult:
        if stage.video_task_id is None:
            return _WaitResult(stage=stage, succeeded=False)
        deadline = _utc(self._clock()) + timedelta(minutes=request.wait_timeout_minutes)
        current = stage
        while True:
            task = await self._video_tasks.get_task(stage.video_task_id)
            if task is None:
                current.status = "missing"
                current.reason = f"{reason_prefix}_task_missing"
                return _WaitResult(stage=current, succeeded=False)
            current = _task_stage_response(
                task,
                default_reason=stage.reason,
                source_stage=stage,
            )
            if task.status == "succeeded":
                current.reason = "succeeded"
                return _WaitResult(stage=current, succeeded=True)
            if task.status not in _ACTIVE_TASK_STATUSES:
                current.reason = f"{reason_prefix}_task_{task.status}"
                return _WaitResult(stage=current, succeeded=False)
            if _utc(self._clock()) >= deadline:
                current.status = "wait_timeout"
                current.reason = timeout_reason
                return _WaitResult(stage=current, succeeded=False, timeout=True)
            await self._sleep(float(request.poll_interval_seconds))

    async def _stage_with_task_details(
        self,
        stage: ProcessToPublishStageResponse,
    ) -> ProcessToPublishStageResponse:
        if stage.video_task_id is None:
            return stage
        task = await self._video_tasks.get_task(stage.video_task_id)
        if task is None:
            return stage
        return _task_stage_response(
            task,
            default_reason=stage.reason,
            source_stage=stage,
        )


def _archive_publish_request(
    request: ProcessToPublishRequest,
    video_ids: list[int],
) -> ArchivePublishRequest:
    payload: dict[str, object] = {
        "target": "selected_videos",
        "videoIds": video_ids,
        "limit": len(video_ids),
        "retryFailed": request.retry_failed,
        "publishMode": request.publish_mode,
    }
    if request.environment is not None:
        payload["environment"] = request.environment
    if request.variant is not None:
        payload["variant"] = request.variant
    if request.schema_version is not None:
        payload["schemaVersion"] = request.schema_version
    return ArchivePublishRequest.model_validate(payload)


def _micro_stage_response(item: MicroEventEnqueueItemResponse) -> ProcessToPublishStageResponse:
    return ProcessToPublishStageResponse(
        videoTaskId=item.video_task_id,
        status=item.status,
        reason=item.reason,
        errorType=item.error_type,
        errorMessage=item.error_message,
    )


def _timeline_stage_response(
    item: TimelineComposeEnqueueItemResponse,
) -> ProcessToPublishStageResponse:
    return ProcessToPublishStageResponse(
        videoTaskId=item.video_task_id,
        status=item.status,
        reason=item.reason,
        sourceMicroEventTaskId=item.source_micro_event_task_id,
        errorType=item.error_type,
        errorMessage=item.error_message,
    )


def _publish_stage_response(
    item: ArchivePublishItemResponse,
) -> ProcessToPublishStageResponse:
    return ProcessToPublishStageResponse(
        videoTaskId=item.video_task_id,
        status=item.status,
        reason=item.reason,
        sourceTimelineTaskId=item.source_timeline_task_id,
        sourceTimelineCompositionId=item.source_timeline_composition_id,
        artifactId=item.artifact_id,
        publicUrl=item.public_url,
        errorType=item.error_type,
        errorMessage=item.error_message,
    )


def _task_stage_response(
    task: VideoTaskRecord,
    *,
    default_reason: str | None,
    source_stage: ProcessToPublishStageResponse | None = None,
) -> ProcessToPublishStageResponse:
    return ProcessToPublishStageResponse(
        videoTaskId=task.id,
        jobId=task.job_id,
        jobAttemptId=task.job_attempt_id,
        status=task.status,
        reason=default_reason,
        errorType=task.error_type,
        errorMessage=task.error_message,
        sourceMicroEventTaskId=(
            source_stage.source_micro_event_task_id if source_stage is not None else None
        ),
        sourceTimelineTaskId=(
            source_stage.source_timeline_task_id if source_stage is not None else None
        ),
        sourceTimelineCompositionId=(
            source_stage.source_timeline_composition_id
            if source_stage is not None
            else None
        ),
        artifactId=source_stage.artifact_id if source_stage is not None else None,
        publicUrl=source_stage.public_url if source_stage is not None else None,
    )


def _should_wait(task_id: int | None, status: str, reason: str) -> bool:
    return task_id is not None and (status in _ACTIVE_TASK_STATUSES or reason in _WAIT_REASONS)


def _micro_succeeded(item: MicroEventEnqueueItemResponse) -> bool:
    return item.status == "succeeded" or item.reason in _MICRO_SUCCESS_REASONS


def _timeline_succeeded(item: TimelineComposeEnqueueItemResponse) -> bool:
    return item.status == "succeeded" or item.reason in _TIMELINE_SUCCESS_REASONS


def _publish_succeeded(item: ArchivePublishItemResponse) -> bool:
    return item.status == "succeeded" or item.reason in _PUBLISH_SUCCESS_REASONS


def _stage_succeeded(stage: ProcessToPublishStageResponse | None) -> bool:
    return (
        stage is not None
        and (stage.status == "succeeded" or stage.reason in {"already_succeeded"})
    )


def _dedupe_preserving_order(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
