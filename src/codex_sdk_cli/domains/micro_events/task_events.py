from __future__ import annotations

from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
    OperationEventSeverity,
)
from codex_sdk_cli.domains.operation_events.recording import record_operation_event
from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .windowing import _ExtractionExecutionInput


class MicroEventTaskEventRecorder:
    def __init__(self, events: OperationEventRecorderPort) -> None:
        self._events = events

    async def record(
        self,
        event_type: str,
        severity: OperationEventSeverity,
        message: str,
        *,
        task: VideoTaskRecord,
        execution_input: _ExtractionExecutionInput,
        reason: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata_json: JsonObject | None = None,
    ) -> None:
        metadata: JsonObject = dict(metadata_json or {})
        if reason is not None:
            metadata["reason"] = reason
        metadata["transcriptId"] = execution_input.metadata.id
        metadata["model"] = execution_input.model
        metadata["reasoningEffort"] = execution_input.reasoning_effort
        metadata["domainKnowledgeEntryCount"] = len(execution_input.domain_knowledge_entries)
        metadata["domainKnowledgeFingerprint"] = execution_input.domain_knowledge_fingerprint
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity=severity,
                message=message,
                actor_type=execution_input.actor_type,
                source="micro_events.extract",
                job_id=task.job_id,
                job_attempt_id=task.job_attempt_id,
                video_task_id=task.id,
                video_id=execution_input.video.id,
                subject_type="video",
                subject_id=execution_input.video.id,
                external_key=execution_input.video.youtube_video_id,
                error_type=error_type,
                error_message=error_message,
                metadata_json=metadata,
            ),
        )
