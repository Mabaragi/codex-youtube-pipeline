from __future__ import annotations

from typing import cast

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventActorType,
    OperationEventCreate,
    OperationEventRecorderPort,
    OperationEventSeverity,
)
from codex_sdk_cli.domains.operation_events.recording import record_operation_event
from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord
from codex_sdk_cli.domains.videos.ports import VideoRecord


class TimelineTaskEventRecorder:
    def __init__(self, events: OperationEventRecorderPort) -> None:
        self._events = events

    async def record(
        self,
        event_type: str,
        severity: OperationEventSeverity,
        message: str,
        *,
        task: VideoTaskRecord,
        video: VideoRecord,
        reason: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata_json: JsonObject | None = None,
    ) -> None:
        metadata: JsonObject = dict(metadata_json or {})
        if reason is not None:
            metadata["reason"] = reason
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity=severity,
                message=message,
                actor_type=cast(OperationEventActorType, "system"),
                source="timelines.compose",
                metadata_json=metadata,
                job_id=task.job_id,
                job_attempt_id=task.job_attempt_id,
                video_task_id=task.id,
                video_id=video.id,
                subject_type="video",
                subject_id=video.id,
                external_key=video.youtube_video_id,
                error_type=error_type,
                error_message=error_message,
            ),
        )
