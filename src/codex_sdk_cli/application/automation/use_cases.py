from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from codex_sdk_cli.application.errors import ApplicationError, ErrorKind
from codex_sdk_cli.domains.automation.ports import (
    AutomationCandidateReaderPort,
    IncidentRecord,
    IncidentRepositoryPort,
    IncidentState,
    IncidentUpsert,
    ManagedProcessInventory,
    ManagedProcessReaderPort,
    RemediationAction,
    RuntimeAuditPort,
    RuntimeControlPort,
    RuntimeState,
    RuntimeTransition,
    SafeRemediationPort,
)
from codex_sdk_cli.domains.work.models import JsonObject

Now = Callable[[], datetime]


class IncidentNotFound(ApplicationError):
    def __init__(self, incident_id: int) -> None:
        super().__init__(
            code="automation.incident_not_found",
            message="Pipeline incident was not found.",
            kind=ErrorKind.NOT_FOUND,
            details={"incidentId": incident_id},
        )


class RuntimeNotDrained(ApplicationError):
    def __init__(self, state: RuntimeState) -> None:
        super().__init__(
            code="pipeline.runtime_not_drained",
            message="Pipeline runtime still has active work.",
            kind=ErrorKind.CONFLICT,
            details={
                "runtimeMode": state.mode,
                "runningWorkItemCount": state.running_work_item_count,
                "runningWorkflowCount": state.running_workflow_count,
            },
        )


class IncidentActionNotAllowed(ApplicationError):
    def __init__(self, incident_id: int, action: RemediationAction) -> None:
        super().__init__(
            code="automation.incident_action_not_allowed",
            message="The incident action requires a linked work item.",
            kind=ErrorKind.VALIDATION,
            details={"incidentId": incident_id, "action": action},
        )


class ListIncidentsUseCase:
    def __init__(self, repository: IncidentRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self, *, state: IncidentState | None, limit: int
    ) -> list[IncidentRecord]:
        return await self._repository.list_incidents(state=state, limit=limit)


class GetIncidentUseCase:
    def __init__(self, repository: IncidentRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, incident_id: int) -> IncidentRecord:
        incident = await self._repository.get(incident_id)
        if incident is None:
            raise IncidentNotFound(incident_id)
        return incident


class UpdateIncidentUseCase:
    def __init__(self, repository: IncidentRepositoryPort, *, now: Now | None = None) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self, incident_id: int, *, state: IncidentState, note: str | None
    ) -> IncidentRecord:
        incident = await self._repository.set_state(
            incident_id,
            state=state,
            note=note,
            now=_aware(self._now()),
        )
        if incident is None:
            raise IncidentNotFound(incident_id)
        return incident


class ExecuteIncidentActionUseCase:
    def __init__(
        self,
        repository: IncidentRepositoryPort,
        remediator: SafeRemediationPort,
        *,
        now: Now | None = None,
    ) -> None:
        self._repository = repository
        self._remediator = remediator
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self,
        incident_id: int,
        *,
        action: RemediationAction,
        parameters: JsonObject,
        idempotency_key: str,
    ) -> JsonObject:
        incident = await self._repository.get(incident_id)
        if incident is None:
            raise IncidentNotFound(incident_id)
        existing = await self._repository.action_result(idempotency_key=idempotency_key)
        if existing is not None:
            return existing
        if action in {"retry", "extend_timeout"} and incident.work_item_id is None:
            raise IncidentActionNotAllowed(incident.id, action)
        now = _aware(self._now())
        result = await self._remediator.execute(
            action=action,
            work_item_id=incident.work_item_id,
            parameters=parameters,
            now=now,
        )
        await self._repository.record_action(
            incident_id=incident.id,
            action=action,
            idempotency_key=idempotency_key,
            parameters=parameters,
            result=result,
            now=now,
        )
        return result


class GetAutomationStatusUseCase:
    def __init__(self, reader: AutomationCandidateReaderPort, *, now: Now | None = None) -> None:
        self._reader = reader
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self) -> JsonObject:
        return await self._reader.automation_status(now=_aware(self._now()))


class GetManagedProcessesUseCase:
    def __init__(self, reader: ManagedProcessReaderPort, *, now: Now | None = None) -> None:
        self._reader = reader
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self) -> ManagedProcessInventory:
        return await self._reader.read(observed_at=_aware(self._now()))


class RequestRuntimeDrainUseCase:
    def __init__(
        self,
        control: RuntimeControlPort,
        audit: RuntimeAuditPort,
        *,
        now: Now | None = None,
    ) -> None:
        self._control = control
        self._audit = audit
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, *, reason: str | None) -> RuntimeState:
        now = _aware(self._now())
        transition = await self._control.request_drain(reason=reason, now=now)
        await _record_transition(self._audit, transition, reason=reason, now=now)
        return transition.state


class MarkRuntimeStoppedUseCase:
    def __init__(
        self,
        control: RuntimeControlPort,
        audit: RuntimeAuditPort,
        *,
        now: Now | None = None,
    ) -> None:
        self._control = control
        self._audit = audit
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, *, reason: str | None) -> RuntimeState:
        now = _aware(self._now())
        transition = await self._control.mark_stopped(reason=reason, now=now)
        if transition.state.mode != "stopped":
            raise RuntimeNotDrained(transition.state)
        await _record_transition(self._audit, transition, reason=reason, now=now)
        return transition.state


class ResumeRuntimeUseCase:
    def __init__(
        self,
        control: RuntimeControlPort,
        audit: RuntimeAuditPort,
        *,
        now: Now | None = None,
    ) -> None:
        self._control = control
        self._audit = audit
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, *, reason: str | None) -> RuntimeState:
        now = _aware(self._now())
        transition = await self._control.resume(reason=reason, now=now)
        await _record_transition(self._audit, transition, reason=reason, now=now)
        return transition.state


class RunPipelineSupervisorUseCase:
    def __init__(
        self,
        *,
        reader: AutomationCandidateReaderPort,
        incidents: IncidentRepositoryPort,
        remediator: SafeRemediationPort,
        now: Now | None = None,
    ) -> None:
        self._reader = reader
        self._incidents = incidents
        self._remediator = remediator
        self._now = now or (lambda: datetime.now(UTC))

    async def execute_once(self) -> JsonObject:
        now = _aware(self._now())
        recovered = await self._remediator.execute(
            action="recover_lease",
            work_item_id=None,
            parameters={},
            now=now,
        )
        resolved = await self._incidents.resolve_recovered(now=now)
        resolved += await self._incidents.resolve_backfill_sla(now=now)
        opened, retried = await self._process_failures(now)
        opened += await self._record_observation_incidents(now)
        return {
            "openedIncidentCount": opened,
            "automaticRetryCount": retried,
            "resolvedIncidentCount": resolved,
            **recovered,
        }

    async def _process_failures(self, now: datetime) -> tuple[int, int]:
        opened = 0
        retried = 0
        for candidate in await self._reader.failures(limit=200):
            transient = _is_transient(
                candidate.task_type,
                candidate.error_code,
                candidate.error_type,
                candidate.error_message,
            )
            fingerprint = _fingerprint(
                "work_failure",
                candidate.work_item_id,
                candidate.error_type,
                candidate.error_message,
            )
            state: IncidentState = (
                "acknowledged"
                if transient and candidate.attempt_count < 3
                else "open"
            )
            incident = await self._incidents.upsert(
                IncidentUpsert(
                    fingerprint=fingerprint,
                    incident_type="work_failure",
                    severity="warning" if state == "acknowledged" else "error",
                    work_item_id=candidate.work_item_id,
                    workflow_run_id=None,
                    task_type=candidate.task_type,
                    error_type=candidate.error_type,
                    error_message=candidate.error_message,
                    metadata_json={
                        "status": candidate.status,
                        "attemptCount": candidate.attempt_count,
                        "errorCode": candidate.error_code,
                        "automaticRetry": state == "acknowledged",
                    },
                    seen_at=now,
                    state=state,
                )
            )
            if state == "acknowledged":
                delay_seconds = 300 if candidate.attempt_count == 1 else 1200
                result = await self._remediator.execute(
                    action="retry",
                    work_item_id=candidate.work_item_id,
                    parameters={"delaySeconds": delay_seconds},
                    now=now,
                )
                await self._incidents.record_action(
                    incident_id=incident.id,
                    action="retry",
                    idempotency_key=(
                        f"supervisor:{incident.id}:attempt:{candidate.attempt_count + 1}"
                    ),
                    parameters={"delaySeconds": delay_seconds},
                    result=result,
                    now=now,
                )
                retried += 1
            else:
                opened += 1
        return opened, retried

    async def _record_observation_incidents(self, now: datetime) -> int:
        opened = 0
        for breach in await self._reader.sla_breaches(now=now, limit=200):
            await self._incidents.upsert(
                IncidentUpsert(
                    fingerprint=_fingerprint("sla_breach", breach.workflow_run_id, None, None),
                    incident_type="sla_breach",
                    severity="error",
                    work_item_id=None,
                    workflow_run_id=breach.workflow_run_id,
                    task_type=breach.current_stage,
                    error_type="SlaDeadlineExceeded",
                    error_message="Workflow exceeded its configured SLA deadline.",
                    metadata_json={
                        "videoId": breach.video_id,
                        "deadline": breach.deadline.isoformat(),
                    },
                    seen_at=now,
                )
            )
            opened += 1
        for stall in await self._reader.stalls(now=now, limit=200):
            await self._incidents.upsert(
                IncidentUpsert(
                    fingerprint=_fingerprint("work_stalled", stall.work_item_id, None, None),
                    incident_type="work_stalled",
                    severity="error",
                    work_item_id=stall.work_item_id,
                    workflow_run_id=None,
                    task_type=stall.task_type,
                    error_type="WorkProgressStalled",
                    error_message="Work made no checkpoint progress for 30 minutes.",
                    metadata_json={
                        "lastProgressAt": stall.last_progress_at.isoformat(),
                    },
                    seen_at=now,
                )
            )
            opened += 1
        for queue in await self._reader.queue_stalls(now=now, limit=50):
            await self._incidents.upsert(
                IncidentUpsert(
                    fingerprint=_fingerprint("queue_stalled", 0, queue.task_type, None),
                    incident_type="queue_stalled",
                    severity="warning",
                    work_item_id=None,
                    workflow_run_id=None,
                    task_type=queue.task_type,
                    error_type="QueueProgressStalled",
                    error_message="Eligible work remained pending for more than 30 minutes.",
                    metadata_json={
                        "pendingCount": queue.pending_count,
                        "oldestAvailableAt": queue.oldest_available_at.isoformat(),
                    },
                    seen_at=now,
                )
            )
            opened += 1
        for orphan in await self._reader.orphan_videos(limit=200):
            await self._incidents.upsert(
                IncidentUpsert(
                    fingerprint=_fingerprint(
                        "data_integrity",
                        orphan.video_id,
                        "OrphanVideoChannelMissing",
                        str(orphan.channel_id),
                    ),
                    incident_type="data_integrity",
                    severity="error",
                    work_item_id=None,
                    workflow_run_id=None,
                    task_type=None,
                    error_type="OrphanVideoChannelMissing",
                    error_message="Video references a missing channel.",
                    metadata_json={
                        "errorCode": "pipeline.orphan_video_channel",
                        "videoId": orphan.video_id,
                        "channelId": orphan.channel_id,
                        "youtubeVideoId": orphan.youtube_video_id,
                    },
                    seen_at=now,
                )
            )
            opened += 1
        return opened


def _is_transient(
    task_type: str,
    error_code: str | None,
    error_type: str | None,
    message: str | None,
) -> bool:
    if error_code == "work.timed_out":
        return True
    if error_code is not None and any(
        marker in error_code
        for marker in (
            "persistence",
            "validation",
            "data_integrity",
            "audio_unavailable",
            "configuration",
        )
    ):
        return False
    text = f"{error_type or ''} {message or ''}".lower()
    markers = (
        "timeout",
        "connection",
        "temporar",
        "rate limit",
        "429",
        "502",
        "503",
        "504",
        "app-server",
        "codex process",
    )
    return any(marker in text for marker in markers) or (
        task_type in {"micro_event_extract", "asr_transcribe"} and "timed" in text
    )


def _fingerprint(kind: str, identifier: int, error_type: str | None, message: str | None) -> str:
    payload = f"{kind}|{identifier}|{error_type or ''}|{message or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _record_transition(
    audit: RuntimeAuditPort,
    transition: RuntimeTransition,
    *,
    reason: str | None,
    now: datetime,
) -> None:
    if transition.changed:
        await audit.record_runtime_transition(transition, reason=reason, now=now)
