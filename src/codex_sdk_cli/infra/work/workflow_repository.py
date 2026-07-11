from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import override

from codex_sdk_cli.application.work.errors import WorkPersistenceError
from codex_sdk_cli.application.work.ports import (
    CreateWorkflowRun,
    WorkflowRepositoryPort,
)
from codex_sdk_cli.domains.work.models import WorkflowRun, WorkflowStatus

from .models import WorkflowRunModel, WorkflowStepModel


class SqlAlchemyWorkflowRepository(WorkflowRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_or_get(self, create: CreateWorkflowRun) -> tuple[WorkflowRun, bool]:
        existing = await self._find(create)
        if existing is not None:
            return _run(existing), False
        model = WorkflowRunModel(
            workflow_type=create.workflow_type,
            workflow_version=create.workflow_version,
            video_id=create.video_id,
            input_hash=create.input_hash,
            status=WorkflowStatus.PENDING.value,
            options_json=create.options_json,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
            await self._session.refresh(model)
        except IntegrityError:
            existing = await self._find(create)
            if existing is None:
                raise WorkPersistenceError() from None
            return _run(existing), False
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _run(model), True

    @override
    async def get(self, workflow_run_id: int) -> WorkflowRun | None:
        try:
            model = await self._session.get(WorkflowRunModel, workflow_run_id)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _run(model) if model is not None else None

    @override
    async def add_step(
        self,
        *,
        workflow_run_id: int,
        stage_name: str,
        position: int,
        work_item_id: int | None,
        status: str,
    ) -> None:
        existing = await self._session.scalar(
            select(WorkflowStepModel).where(
                WorkflowStepModel.workflow_run_id == workflow_run_id,
                WorkflowStepModel.stage_name == stage_name,
            )
        )
        if existing is not None:
            existing.work_item_id = work_item_id
            existing.status = status
        else:
            self._session.add(
                WorkflowStepModel(
                    workflow_run_id=workflow_run_id,
                    stage_name=stage_name,
                    position=position,
                    work_item_id=work_item_id,
                    status=status,
                )
            )
        try:
            await self._session.flush()
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc

    async def _find(self, create: CreateWorkflowRun) -> WorkflowRunModel | None:
        try:
            return await self._session.scalar(
                select(WorkflowRunModel).where(
                    WorkflowRunModel.workflow_type == create.workflow_type,
                    WorkflowRunModel.workflow_version == create.workflow_version,
                    WorkflowRunModel.video_id == create.video_id,
                    WorkflowRunModel.input_hash == create.input_hash,
                )
            )
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc


def _run(model: WorkflowRunModel) -> WorkflowRun:
    return WorkflowRun(
        id=model.id,
        workflow_type=model.workflow_type,
        workflow_version=model.workflow_version,
        video_id=model.video_id,
        input_hash=model.input_hash,
        status=WorkflowStatus(model.status),
        current_stage=model.current_stage,
        options_json=model.options_json,
        output_json=model.output_json,
        error_code=model.error_code,
        error_message=model.error_message,
        lease_owner=model.lease_owner,
        lease_expires_at=model.lease_expires_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )
