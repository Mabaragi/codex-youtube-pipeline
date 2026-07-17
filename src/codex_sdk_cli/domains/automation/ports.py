from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from codex_sdk_cli.domains.work.models import JsonObject

IncidentState = Literal["open", "acknowledged", "resolved", "suppressed"]
IncidentSeverity = Literal["info", "warning", "error", "critical"]
RuntimeMode = Literal["active", "draining", "stopped"]
ManagedProcessState = Literal[
    "running",
    "stopped",
    "stale_pid",
    "identity_mismatch",
    "unreadable",
]
RemediationAction = Literal[
    "retry",
    "recover_lease",
    "extend_timeout",
    "set_temporary_concurrency",
]


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    id: int
    fingerprint: str
    incident_type: str
    severity: IncidentSeverity
    state: IncidentState
    work_item_id: int | None
    workflow_run_id: int | None
    task_type: str | None
    error_type: str | None
    error_message: str | None
    metadata_json: JsonObject
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class IncidentUpsert:
    fingerprint: str
    incident_type: str
    severity: IncidentSeverity
    work_item_id: int | None
    workflow_run_id: int | None
    task_type: str | None
    error_type: str | None
    error_message: str | None
    metadata_json: JsonObject
    seen_at: datetime
    state: IncidentState = "open"


@dataclass(frozen=True, slots=True)
class FailureCandidate:
    work_item_id: int
    task_type: str
    status: str
    error_code: str | None
    error_type: str | None
    error_message: str | None
    attempt_count: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SlaBreachCandidate:
    workflow_run_id: int
    video_id: int
    current_stage: str | None
    deadline: datetime
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class StallCandidate:
    work_item_id: int
    task_type: str
    last_progress_at: datetime
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class QueueStallCandidate:
    task_type: str
    pending_count: int
    oldest_available_at: datetime
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class OrphanVideoCandidate:
    video_id: int
    channel_id: int
    youtube_video_id: str


@dataclass(frozen=True, slots=True)
class RuntimeTaskCount:
    task_type: str
    count: int


@dataclass(frozen=True, slots=True)
class RuntimeState:
    mode: RuntimeMode
    drain_requested_at: datetime | None
    drain_reason: str | None
    running_work_item_count: int
    running_workflow_count: int
    running_by_task_type: tuple[RuntimeTaskCount, ...]

    @property
    def ready_to_stop(self) -> bool:
        return (
            self.mode in {"draining", "stopped"}
            and self.running_work_item_count == 0
            and self.running_workflow_count == 0
        )


@dataclass(frozen=True, slots=True)
class RuntimeTransition:
    previous_mode: RuntimeMode
    state: RuntimeState
    changed: bool


@dataclass(frozen=True, slots=True)
class ManagedProcess:
    name: str
    role: str
    state: ManagedProcessState
    pid: int | None
    started_at: datetime | None
    source: str
    detail_code: str | None


@dataclass(frozen=True, slots=True)
class ManagedProcessInventory:
    observed_at: datetime
    host_name: str
    platform: str
    items: tuple[ManagedProcess, ...]


class ManagedProcessReaderPort(Protocol):
    async def read(self, *, observed_at: datetime) -> ManagedProcessInventory: ...


class IncidentRepositoryPort(Protocol):
    async def list_incidents(
        self, *, state: IncidentState | None, limit: int
    ) -> list[IncidentRecord]: ...

    async def get(self, incident_id: int) -> IncidentRecord | None: ...

    async def upsert(self, incident: IncidentUpsert) -> IncidentRecord: ...

    async def set_state(
        self,
        incident_id: int,
        *,
        state: IncidentState,
        note: str | None,
        now: datetime,
    ) -> IncidentRecord | None: ...

    async def record_action(
        self,
        *,
        incident_id: int,
        action: RemediationAction,
        idempotency_key: str,
        parameters: JsonObject,
        result: JsonObject,
        now: datetime,
    ) -> None: ...

    async def action_result(self, *, idempotency_key: str) -> JsonObject | None: ...

    async def resolve_recovered(self, *, now: datetime) -> int: ...

    async def resolve_backfill_sla(self, *, now: datetime) -> int: ...


class AutomationCandidateReaderPort(Protocol):
    async def failures(self, *, limit: int) -> list[FailureCandidate]: ...

    async def sla_breaches(self, *, now: datetime, limit: int) -> list[SlaBreachCandidate]: ...

    async def stalls(self, *, now: datetime, limit: int) -> list[StallCandidate]: ...

    async def queue_stalls(self, *, now: datetime, limit: int) -> list[QueueStallCandidate]: ...

    async def orphan_videos(self, *, limit: int) -> list[OrphanVideoCandidate]: ...

    async def automation_status(self, *, now: datetime) -> JsonObject: ...


class RuntimeControlPort(Protocol):
    async def runtime_state(self, *, now: datetime) -> RuntimeState: ...

    async def request_drain(
        self,
        *,
        reason: str | None,
        now: datetime,
    ) -> RuntimeTransition: ...

    async def mark_stopped(
        self,
        *,
        reason: str | None,
        now: datetime,
    ) -> RuntimeTransition: ...

    async def resume(
        self,
        *,
        reason: str | None,
        now: datetime,
    ) -> RuntimeTransition: ...


class RuntimeAuditPort(Protocol):
    async def record_runtime_transition(
        self,
        transition: RuntimeTransition,
        *,
        reason: str | None,
        now: datetime,
    ) -> None: ...


class SafeRemediationPort(Protocol):
    async def execute(
        self,
        *,
        action: RemediationAction,
        work_item_id: int | None,
        parameters: JsonObject,
        now: datetime,
    ) -> JsonObject: ...
