from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import override

from codex_sdk_cli.application.work.errors import WorkPersistenceError
from codex_sdk_cli.application.work.ports import (
    CreateWorkBatch,
    WorkBatchRepositoryPort,
)
from codex_sdk_cli.domains.work.models import WorkBatch, WorkBatchItem, WorkBatchStatus

from .models import WorkBatchItemModel, WorkBatchModel


class SqlAlchemyWorkBatchRepository(WorkBatchRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create(self, create: CreateWorkBatch) -> WorkBatch:
        model = WorkBatchModel(
            operation_type=create.operation_type,
            status=WorkBatchStatus.PENDING.value,
            actor_type=create.actor_type,
            selection_json=create.selection_json,
            options_json=create.options_json,
            requested_count=create.requested_count,
        )
        self._session.add(model)
        try:
            await self._session.flush()
            await self._session.refresh(model)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _batch(model)

    @override
    async def get(self, batch_id: int) -> WorkBatch | None:
        try:
            model = await self._session.get(WorkBatchModel, batch_id)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _batch(model) if model is not None else None

    @override
    async def list_items(self, batch_id: int) -> list[WorkBatchItem]:
        try:
            models = list(
                (
                    await self._session.scalars(
                        select(WorkBatchItemModel)
                        .where(WorkBatchItemModel.batch_id == batch_id)
                        .order_by(WorkBatchItemModel.position.asc())
                    )
                ).all()
            )
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return [_batch_item(model) for model in models]

    @override
    async def complete(
        self,
        *,
        batch_id: int,
        status: str,
        completed_at: datetime,
    ) -> WorkBatch:
        model = await self._session.get(WorkBatchModel, batch_id)
        if model is None:
            raise WorkPersistenceError("Work batch was not found.")
        model.status = WorkBatchStatus(status).value
        model.completed_at = completed_at
        try:
            await self._session.flush()
            await self._session.refresh(model)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _batch(model)

    @override
    async def add_item(
        self,
        *,
        batch_id: int,
        position: int,
        video_id: int | None,
        work_item_id: int | None,
        workflow_run_id: int | None,
        selection_status: str,
        reason: str | None,
    ) -> None:
        self._session.add(
            WorkBatchItemModel(
                batch_id=batch_id,
                position=position,
                video_id=video_id,
                work_item_id=work_item_id,
                workflow_run_id=workflow_run_id,
                selection_status=selection_status,
                reason=reason,
            )
        )
        try:
            await self._session.flush()
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc


def _batch(model: WorkBatchModel) -> WorkBatch:
    return WorkBatch(
        id=model.id,
        operation_type=model.operation_type,
        status=WorkBatchStatus(model.status),
        actor_type=model.actor_type,
        selection_json=model.selection_json,
        options_json=model.options_json,
        requested_count=model.requested_count,
        created_at=model.created_at,
        completed_at=model.completed_at,
    )


def _batch_item(model: WorkBatchItemModel) -> WorkBatchItem:
    return WorkBatchItem(
        id=model.id,
        batch_id=model.batch_id,
        position=model.position,
        video_id=model.video_id,
        work_item_id=model.work_item_id,
        workflow_run_id=model.workflow_run_id,
        selection_status=model.selection_status,
        reason=model.reason,
    )
