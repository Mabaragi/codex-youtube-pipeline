from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import case, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import override

from codex_sdk_cli.application.work.errors import WorkPersistenceError
from codex_sdk_cli.application.work.ports import (
    CreateWorkflowRun,
    WorkflowRepositoryPort,
    WorkflowRunQuery,
)
from codex_sdk_cli.domains.work.models import (
    JsonObject,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStep,
)
from codex_sdk_cli.infra.videos.repository import VideoModel

from .models import WorkflowRunModel, WorkflowStepModel
from .runtime_gate import runtime_accepting_work


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
            available_at=create.available_at,
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
    async def list_runs(self, query: WorkflowRunQuery) -> list[WorkflowRun]:
        statement = select(WorkflowRunModel)
        if query.workflow_type is not None:
            statement = statement.where(
                WorkflowRunModel.workflow_type == query.workflow_type
            )
        if query.status is not None:
            statement = statement.where(WorkflowRunModel.status == query.status.value)
        if query.video_id is not None:
            statement = statement.where(WorkflowRunModel.video_id == query.video_id)
        if query.cursor is not None:
            statement = statement.where(WorkflowRunModel.id < query.cursor)
        statement = statement.order_by(WorkflowRunModel.id.desc()).limit(query.limit)
        try:
            models = list((await self._session.scalars(statement)).all())
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return [_run(model) for model in models]

    @override
    async def list_steps(self, workflow_run_id: int) -> list[WorkflowStep]:
        try:
            models = list(
                (
                    await self._session.scalars(
                        select(WorkflowStepModel)
                        .where(WorkflowStepModel.workflow_run_id == workflow_run_id)
                        .order_by(WorkflowStepModel.position.asc())
                    )
                ).all()
            )
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return [_step(model) for model in models]

    @override
    async def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> WorkflowRun | None:
        if not await runtime_accepting_work(self._session):
            return None
        video_published_at = (
            select(VideoModel.published_at)
            .where(VideoModel.id == WorkflowRunModel.video_id)
            .scalar_subquery()
        )
        claimable = (
            select(WorkflowRunModel.id)
            .where(
                WorkflowRunModel.status.in_(
                    (WorkflowStatus.PENDING.value, WorkflowStatus.WAITING.value)
                ),
                or_(
                    WorkflowRunModel.lease_expires_at.is_(None),
                    WorkflowRunModel.lease_expires_at <= now,
                ),
                WorkflowRunModel.available_at <= now,
            )
            .order_by(
                case(
                    (WorkflowRunModel.status == WorkflowStatus.PENDING.value, 0),
                    else_=1,
                ),
                video_published_at.desc(),
                WorkflowRunModel.updated_at.asc(),
                WorkflowRunModel.id.asc(),
            )
            .limit(1)
            .scalar_subquery()
        )
        try:
            claimed_id = (
                await self._session.execute(
                    update(WorkflowRunModel)
                    .where(
                        WorkflowRunModel.id == claimable,
                        WorkflowRunModel.status.in_(
                            (WorkflowStatus.PENDING.value, WorkflowStatus.WAITING.value)
                        ),
                    )
                    .values(
                        status=WorkflowStatus.RUNNING.value,
                        lease_owner=worker_id,
                        lease_expires_at=lease_expires_at,
                        updated_at=now,
                    )
                    .returning(WorkflowRunModel.id)
                )
            ).scalar_one_or_none()
            if claimed_id is None:
                return None
            model = await self._session.get(WorkflowRunModel, claimed_id)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        if model is None:
            raise WorkPersistenceError("Claimed workflow disappeared.")
        return _run(model)

    @override
    async def add_step(
        self,
        *,
        workflow_run_id: int,
        stage_name: str,
        position: int,
        work_item_id: int | None,
        status: str,
        completed_at: datetime | None = None,
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
            existing.completed_at = completed_at
        else:
            self._session.add(
                WorkflowStepModel(
                    workflow_run_id=workflow_run_id,
                    stage_name=stage_name,
                    position=position,
                    work_item_id=work_item_id,
                    status=status,
                    completed_at=completed_at,
                )
            )
        try:
            await self._session.flush()
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc

    @override
    async def heartbeat(
        self,
        *,
        workflow_run_id: int,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        try:
            result = await self._session.execute(
                update(WorkflowRunModel)
                .where(
                    WorkflowRunModel.id == workflow_run_id,
                    WorkflowRunModel.status == WorkflowStatus.RUNNING.value,
                    WorkflowRunModel.lease_owner == worker_id,
                )
                .values(lease_expires_at=lease_expires_at, updated_at=now)
            )
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return bool(cast(CursorResult[object], result).rowcount)

    @override
    async def recover_expired_leases(self, *, now: datetime) -> int:
        try:
            result = await self._session.execute(
                update(WorkflowRunModel)
                .where(
                    WorkflowRunModel.status == WorkflowStatus.RUNNING.value,
                    WorkflowRunModel.lease_expires_at.is_not(None),
                    WorkflowRunModel.lease_expires_at <= now,
                )
                .values(
                    status=WorkflowStatus.WAITING.value,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        rowcount = cast(CursorResult[object], result).rowcount
        return max(rowcount if rowcount is not None else 0, 0)

    @override
    async def reset_for_retry(
        self,
        *,
        workflow_run_id: int,
        now: datetime,
    ) -> WorkflowRun:
        model = await self._session.get(WorkflowRunModel, workflow_run_id)
        if model is None:
            raise WorkPersistenceError("Workflow run was not found.")
        if model.status not in {WorkflowStatus.FAILED.value, WorkflowStatus.BLOCKED.value}:
            return _run(model)
        model.status = WorkflowStatus.PENDING.value
        model.current_stage = None
        model.error_code = None
        model.error_message = None
        model.lease_owner = None
        model.lease_expires_at = None
        model.available_at = now
        model.completed_at = None
        model.updated_at = now
        await self._session.flush()
        return _run(model)

    @override
    async def reset_linked_for_work_item_retry(
        self,
        *,
        work_item_id: int,
        now: datetime,
    ) -> list[int]:
        workflow_ids = list(
            (
                await self._session.scalars(
                    select(WorkflowStepModel.workflow_run_id)
                    .join(
                        WorkflowRunModel,
                        WorkflowRunModel.id == WorkflowStepModel.workflow_run_id,
                    )
                    .where(
                        WorkflowStepModel.work_item_id == work_item_id,
                        WorkflowRunModel.status.in_(
                            (WorkflowStatus.FAILED.value, WorkflowStatus.BLOCKED.value)
                        ),
                    )
                    .order_by(WorkflowStepModel.workflow_run_id)
                )
            ).all()
        )
        for workflow_run_id in workflow_ids:
            workflow = await self._session.get(WorkflowRunModel, workflow_run_id)
            if workflow is not None and workflow.options_json.get("automation_mode") in {
                "backfill",
                "steady",
            }:
                workflow.options_json = {
                    **workflow.options_json,
                    "retry_failed": False,
                }
            await self.reset_for_retry(workflow_run_id=workflow_run_id, now=now)
        return workflow_ids

    @override
    async def set_waiting(
        self,
        *,
        workflow_run_id: int,
        current_stage: str,
        now: datetime,
        available_at: datetime | None = None,
    ) -> WorkflowRun:
        return await self._finish_transition(
            workflow_run_id,
            status=WorkflowStatus.WAITING,
            current_stage=current_stage,
            now=now,
            available_at=available_at or now,
        )

    @override
    async def mark_succeeded(
        self,
        *,
        workflow_run_id: int,
        output_json: JsonObject,
        now: datetime,
    ) -> WorkflowRun:
        return await self._finish_transition(
            workflow_run_id,
            status=WorkflowStatus.SUCCEEDED,
            current_stage="archive_publish",
            now=now,
            output_json=output_json,
            completed_at=now,
        )

    @override
    async def mark_failed(
        self,
        *,
        workflow_run_id: int,
        error_code: str,
        error_message: str,
        blocked: bool,
        now: datetime,
    ) -> WorkflowRun:
        return await self._finish_transition(
            workflow_run_id,
            status=WorkflowStatus.BLOCKED if blocked else WorkflowStatus.FAILED,
            current_stage=None,
            now=now,
            error_code=error_code,
            error_message=error_message,
            completed_at=now,
        )

    async def _finish_transition(
        self,
        workflow_run_id: int,
        *,
        status: WorkflowStatus,
        current_stage: str | None,
        now: datetime,
        output_json: JsonObject | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
        available_at: datetime | None = None,
    ) -> WorkflowRun:
        try:
            model = await self._session.get(WorkflowRunModel, workflow_run_id)
            if model is None:
                raise WorkPersistenceError("Workflow run was not found.")
            model.status = status.value
            model.current_stage = current_stage
            model.output_json = output_json
            model.error_code = error_code
            model.error_message = error_message
            model.lease_owner = None
            model.lease_expires_at = None
            model.updated_at = now
            model.completed_at = completed_at
            model.available_at = available_at or now
            await self._session.flush()
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _run(model)

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
        available_at=model.available_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def _step(model: WorkflowStepModel) -> WorkflowStep:
    return WorkflowStep(
        id=model.id,
        workflow_run_id=model.workflow_run_id,
        stage_name=model.stage_name,
        position=model.position,
        work_item_id=model.work_item_id,
        status=model.status,
        created_at=model.created_at,
        completed_at=model.completed_at,
    )
