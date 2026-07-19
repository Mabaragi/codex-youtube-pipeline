from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import DatabaseSessionFactoryDep, SettingsDep
from codex_sdk_cli.application.automation.use_cases import (
    ExecuteIncidentActionUseCase,
    GetAutomationStatusUseCase,
    GetIncidentUseCase,
    GetManagedProcessesUseCase,
    ListIncidentsUseCase,
    MarkRuntimeStoppedUseCase,
    RequestRuntimeDrainUseCase,
    ResumeRuntimeUseCase,
    UpdateIncidentUseCase,
)
from codex_sdk_cli.infra.automation.processes import PsutilManagedProcessReader
from codex_sdk_cli.infra.automation.repository import (
    SqlAlchemyAutomationRepository,
    SqlAlchemySafeRemediator,
)
from codex_sdk_cli.infra.work.scheduler import SqlAlchemyWorkflowCandidateReader


def get_automation_repository(
    session_factory: DatabaseSessionFactoryDep,
) -> SqlAlchemyAutomationRepository:
    return SqlAlchemyAutomationRepository(session_factory)


AutomationRepositoryDep = Annotated[
    SqlAlchemyAutomationRepository,
    Depends(get_automation_repository),
]


def get_list_incidents_use_case(
    repository: AutomationRepositoryDep,
) -> ListIncidentsUseCase:
    return ListIncidentsUseCase(repository)


def get_incident_use_case(repository: AutomationRepositoryDep) -> GetIncidentUseCase:
    return GetIncidentUseCase(repository)


def get_update_incident_use_case(
    repository: AutomationRepositoryDep,
) -> UpdateIncidentUseCase:
    return UpdateIncidentUseCase(repository)


def get_execute_incident_action_use_case(
    repository: AutomationRepositoryDep,
    session_factory: DatabaseSessionFactoryDep,
) -> ExecuteIncidentActionUseCase:
    return ExecuteIncidentActionUseCase(
        repository,
        SqlAlchemySafeRemediator(session_factory),
    )


def get_automation_status_use_case(
    repository: AutomationRepositoryDep,
    session_factory: DatabaseSessionFactoryDep,
    settings: SettingsDep,
) -> GetAutomationStatusUseCase:
    return GetAutomationStatusUseCase(
        repository,
        workflow_candidates=SqlAlchemyWorkflowCandidateReader(session_factory),
        schedule_state=repository,
        daily_workflow_limit=settings.pipeline_scheduler_daily_workflow_limit,
        channel_daily_minimum=settings.pipeline_scheduler_channel_daily_minimum,
        quota_timezone=settings.pipeline_scheduler_quota_timezone,
    )


def get_managed_processes_use_case(settings: SettingsDep) -> GetManagedProcessesUseCase:
    return GetManagedProcessesUseCase(
        PsutilManagedProcessReader(
            pid_dir=settings.local_runtime_pid_dir,
            repository_root=settings.local_runtime_pid_dir.parent.parent,
        )
    )


def get_request_runtime_drain_use_case(
    repository: AutomationRepositoryDep,
) -> RequestRuntimeDrainUseCase:
    return RequestRuntimeDrainUseCase(repository, repository)


def get_mark_runtime_stopped_use_case(
    repository: AutomationRepositoryDep,
) -> MarkRuntimeStoppedUseCase:
    return MarkRuntimeStoppedUseCase(repository, repository)


def get_resume_runtime_use_case(
    repository: AutomationRepositoryDep,
) -> ResumeRuntimeUseCase:
    return ResumeRuntimeUseCase(repository, repository)


ListIncidentsUseCaseDep = Annotated[
    ListIncidentsUseCase,
    Depends(get_list_incidents_use_case),
]
GetIncidentUseCaseDep = Annotated[GetIncidentUseCase, Depends(get_incident_use_case)]
UpdateIncidentUseCaseDep = Annotated[
    UpdateIncidentUseCase,
    Depends(get_update_incident_use_case),
]
ExecuteIncidentActionUseCaseDep = Annotated[
    ExecuteIncidentActionUseCase,
    Depends(get_execute_incident_action_use_case),
]
GetAutomationStatusUseCaseDep = Annotated[
    GetAutomationStatusUseCase,
    Depends(get_automation_status_use_case),
]
GetManagedProcessesUseCaseDep = Annotated[
    GetManagedProcessesUseCase,
    Depends(get_managed_processes_use_case),
]
RequestRuntimeDrainUseCaseDep = Annotated[
    RequestRuntimeDrainUseCase,
    Depends(get_request_runtime_drain_use_case),
]
MarkRuntimeStoppedUseCaseDep = Annotated[
    MarkRuntimeStoppedUseCase,
    Depends(get_mark_runtime_stopped_use_case),
]
ResumeRuntimeUseCaseDep = Annotated[
    ResumeRuntimeUseCase,
    Depends(get_resume_runtime_use_case),
]
