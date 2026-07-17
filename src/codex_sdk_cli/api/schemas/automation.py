from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from codex_sdk_cli.domains.automation.ports import (
    IncidentRecord,
    IncidentState,
    ManagedProcessInventory,
    RemediationAction,
    RuntimeMode,
    RuntimeState,
)


class IncidentResponse(BaseModel):
    id: int
    fingerprint: str
    incident_type: str = Field(alias="incidentType")
    severity: str
    state: str
    work_item_id: int | None = Field(alias="workItemId")
    workflow_run_id: int | None = Field(alias="workflowRunId")
    task_type: str | None = Field(alias="taskType")
    error_type: str | None = Field(alias="errorType")
    error_message: str | None = Field(alias="errorMessage")
    metadata: dict[str, object]
    occurrence_count: int = Field(alias="occurrenceCount")
    first_seen_at: datetime = Field(alias="firstSeenAt")
    last_seen_at: datetime = Field(alias="lastSeenAt")
    resolved_at: datetime | None = Field(alias="resolvedAt")

    model_config = ConfigDict(populate_by_name=True)


class IncidentListResponse(BaseModel):
    items: list[IncidentResponse]


class IncidentUpdateRequest(BaseModel):
    state: IncidentState
    note: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class IncidentActionRequest(BaseModel):
    action: RemediationAction
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=255)
    parameters: dict[str, object] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class IncidentActionResponse(BaseModel):
    incident_id: int = Field(alias="incidentId")
    action: RemediationAction
    result: dict[str, object]

    model_config = ConfigDict(populate_by_name=True)


class AutomationDataIntegrityResponse(BaseModel):
    orphan_video_count: int = Field(alias="orphanVideoCount")

    model_config = ConfigDict(populate_by_name=True)


class RuntimeTransitionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)

    model_config = ConfigDict(extra="forbid")


class RuntimeTaskCountResponse(BaseModel):
    task_type: str = Field(alias="taskType")
    count: int = Field(ge=0)

    model_config = ConfigDict(populate_by_name=True)


class RuntimeStateResponse(BaseModel):
    state: RuntimeMode
    drain_requested_at: datetime | None = Field(alias="drainRequestedAt")
    drain_reason: str | None = Field(alias="drainReason")
    running_work_item_count: int = Field(alias="runningWorkItemCount", ge=0)
    running_workflow_count: int = Field(alias="runningWorkflowCount", ge=0)
    running_by_task_type: list[RuntimeTaskCountResponse] = Field(
        alias="runningByTaskType"
    )
    ready_to_stop: bool = Field(alias="readyToStop")

    model_config = ConfigDict(populate_by_name=True)


class AutomationStatusResponse(BaseModel):
    mode: str
    backfill_started_at: str | None = Field(alias="backfillStartedAt")
    steady_started_at: str | None = Field(alias="steadyStartedAt")
    observed_at: str = Field(alias="observedAt")
    open_incident_count: int = Field(alias="openIncidentCount")
    data_integrity: AutomationDataIntegrityResponse = Field(alias="dataIntegrity")
    runtime: RuntimeStateResponse
    queues: list[dict[str, object]]

    model_config = ConfigDict(populate_by_name=True)


class ManagedProcessResponse(BaseModel):
    name: str
    role: str
    state: str
    pid: int | None
    started_at: datetime | None = Field(alias="startedAt")
    source: str
    detail_code: str | None = Field(alias="detailCode")

    model_config = ConfigDict(populate_by_name=True)


class ManagedProcessInventoryResponse(BaseModel):
    observed_at: datetime = Field(alias="observedAt")
    host_name: str = Field(alias="hostName")
    platform: str
    items: tuple[ManagedProcessResponse, ...]

    model_config = ConfigDict(populate_by_name=True)


def runtime_state_response(state: RuntimeState) -> RuntimeStateResponse:
    return RuntimeStateResponse(
        state=state.mode,
        drainRequestedAt=state.drain_requested_at,
        drainReason=state.drain_reason,
        runningWorkItemCount=state.running_work_item_count,
        runningWorkflowCount=state.running_workflow_count,
        runningByTaskType=[
            RuntimeTaskCountResponse(taskType=item.task_type, count=item.count)
            for item in state.running_by_task_type
        ],
        readyToStop=state.ready_to_stop,
    )


def incident_response(record: IncidentRecord) -> IncidentResponse:
    return IncidentResponse(
        id=record.id,
        fingerprint=record.fingerprint,
        incidentType=record.incident_type,
        severity=record.severity,
        state=record.state,
        workItemId=record.work_item_id,
        workflowRunId=record.workflow_run_id,
        taskType=record.task_type,
        errorType=record.error_type,
        errorMessage=record.error_message,
        metadata=record.metadata_json,
        occurrenceCount=record.occurrence_count,
        firstSeenAt=record.first_seen_at,
        lastSeenAt=record.last_seen_at,
        resolvedAt=record.resolved_at,
    )


def managed_process_inventory_response(
    inventory: ManagedProcessInventory,
) -> ManagedProcessInventoryResponse:
    return ManagedProcessInventoryResponse(
        observedAt=inventory.observed_at,
        hostName=inventory.host_name,
        platform=inventory.platform,
        items=tuple(
            ManagedProcessResponse(
                name=item.name,
                role=item.role,
                state=item.state,
                pid=item.pid,
                startedAt=item.started_at,
                source=item.source,
                detailCode=item.detail_code,
            )
            for item in inventory.items
        ),
    )
