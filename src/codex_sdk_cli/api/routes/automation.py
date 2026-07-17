from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from codex_sdk_cli.api.schemas.automation import (
    AutomationStatusResponse,
    IncidentActionRequest,
    IncidentActionResponse,
    IncidentListResponse,
    IncidentResponse,
    IncidentUpdateRequest,
    ManagedProcessInventoryResponse,
    RuntimeStateResponse,
    RuntimeTransitionRequest,
    incident_response,
    managed_process_inventory_response,
    runtime_state_response,
)
from codex_sdk_cli.api.use_case_dependencies.automation import (
    ExecuteIncidentActionUseCaseDep,
    GetAutomationStatusUseCaseDep,
    GetIncidentUseCaseDep,
    GetManagedProcessesUseCaseDep,
    ListIncidentsUseCaseDep,
    MarkRuntimeStoppedUseCaseDep,
    RequestRuntimeDrainUseCaseDep,
    ResumeRuntimeUseCaseDep,
    UpdateIncidentUseCaseDep,
)
from codex_sdk_cli.domains.automation.ports import IncidentState

router = APIRouter()


@router.get("/automation/processes", response_model=ManagedProcessInventoryResponse)
async def managed_processes(
    use_case: GetManagedProcessesUseCaseDep,
) -> ManagedProcessInventoryResponse:
    return managed_process_inventory_response(await use_case.execute())


@router.get("/automation/status", response_model=AutomationStatusResponse)
async def automation_status(
    use_case: GetAutomationStatusUseCaseDep,
) -> AutomationStatusResponse:
    return AutomationStatusResponse.model_validate(await use_case.execute())


@router.post("/automation/runtime/drain", response_model=RuntimeStateResponse)
async def request_runtime_drain(
    request: RuntimeTransitionRequest,
    use_case: RequestRuntimeDrainUseCaseDep,
) -> RuntimeStateResponse:
    return runtime_state_response(await use_case.execute(reason=request.reason))


@router.post("/automation/runtime/mark-stopped", response_model=RuntimeStateResponse)
async def mark_runtime_stopped(
    request: RuntimeTransitionRequest,
    use_case: MarkRuntimeStoppedUseCaseDep,
) -> RuntimeStateResponse:
    return runtime_state_response(await use_case.execute(reason=request.reason))


@router.post("/automation/runtime/resume", response_model=RuntimeStateResponse)
async def resume_runtime(
    request: RuntimeTransitionRequest,
    use_case: ResumeRuntimeUseCaseDep,
) -> RuntimeStateResponse:
    return runtime_state_response(await use_case.execute(reason=request.reason))


@router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    use_case: ListIncidentsUseCaseDep,
    state: Annotated[IncidentState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> IncidentListResponse:
    return IncidentListResponse(
        items=[incident_response(item) for item in await use_case.execute(state=state, limit=limit)]
    )


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    use_case: GetIncidentUseCaseDep,
    incident_id: Annotated[int, Path(ge=1)],
) -> IncidentResponse:
    return incident_response(await use_case.execute(incident_id))


@router.patch("/incidents/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    request: IncidentUpdateRequest,
    use_case: UpdateIncidentUseCaseDep,
    incident_id: Annotated[int, Path(ge=1)],
) -> IncidentResponse:
    return incident_response(
        await use_case.execute(incident_id, state=request.state, note=request.note)
    )


@router.post("/incidents/{incident_id}/actions", response_model=IncidentActionResponse)
async def execute_incident_action(
    request: IncidentActionRequest,
    use_case: ExecuteIncidentActionUseCaseDep,
    incident_id: Annotated[int, Path(ge=1)],
) -> IncidentActionResponse:
    result = await use_case.execute(
        incident_id,
        action=request.action,
        parameters=request.parameters,
        idempotency_key=request.idempotency_key,
    )
    return IncidentActionResponse(
        incidentId=incident_id,
        action=request.action,
        result=result,
    )
