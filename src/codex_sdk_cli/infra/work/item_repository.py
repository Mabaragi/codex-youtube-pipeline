from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from typing_extensions import override

from codex_sdk_cli.application.work.errors import (
    WorkItemNotFound,
    WorkItemTransitionNotAllowed,
    WorkPersistenceError,
)
from codex_sdk_cli.application.work.ports import (
    CreateWorkItem,
    WorkAttemptRepositoryPort,
    WorkItemQuery,
    WorkItemRepositoryPort,
)
from codex_sdk_cli.domains.work.models import (
    JsonObject,
    WorkAttempt,
    WorkAttemptStatus,
    WorkExecutionMode,
    WorkItem,
    WorkItemStatus,
)

from .models import WorkAttemptModel, WorkItemDependencyModel, WorkItemModel


class SqlAlchemyWorkItemRepository(WorkItemRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get(self, work_item_id: int) -> WorkItem | None:
        try:
            model = await self._session.get(WorkItemModel, work_item_id)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _item(model) if model is not None else None

    @override
    async def get_by_idempotency_key(self, idempotency_key: str) -> WorkItem | None:
        try:
            model = await self._session.scalar(
                select(WorkItemModel).where(WorkItemModel.idempotency_key == idempotency_key)
            )
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _item(model) if model is not None else None

    @override
    async def get_or_create(self, create: CreateWorkItem) -> tuple[WorkItem, bool]:
        existing = await self.get_by_idempotency_key(create.idempotency_key)
        if existing is not None:
            return existing, False
        model = WorkItemModel(
            task_type=create.task_type,
            subject_type=create.subject_type,
            subject_id=create.subject_id,
            external_key=create.external_key,
            task_version=create.task_version,
            input_hash=create.input_hash,
            idempotency_key=create.idempotency_key,
            execution_mode=create.execution_mode.value,
            status=WorkItemStatus.PENDING.value,
            priority=create.priority,
            timeout_seconds=create.timeout_seconds,
            input_json=create.input_json,
        )
        if create.available_at is not None:
            model.available_at = create.available_at
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
            await self._session.refresh(model)
        except IntegrityError:
            existing = await self.get_by_idempotency_key(create.idempotency_key)
            if existing is None:
                raise WorkPersistenceError() from None
            return existing, False
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _item(model), True

    @override
    async def list_items(self, query: WorkItemQuery) -> list[WorkItem]:
        statement = select(WorkItemModel)
        if query.task_type is not None:
            statement = statement.where(WorkItemModel.task_type == query.task_type)
        if query.status is not None:
            statement = statement.where(WorkItemModel.status == query.status.value)
        if query.subject_type is not None:
            statement = statement.where(WorkItemModel.subject_type == query.subject_type)
        if query.subject_id is not None:
            statement = statement.where(WorkItemModel.subject_id == query.subject_id)
        if query.cursor is not None:
            statement = statement.where(WorkItemModel.id < query.cursor)
        statement = statement.order_by(WorkItemModel.id.desc()).limit(query.limit)
        try:
            models = list((await self._session.scalars(statement)).all())
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return [_item(model) for model in models]

    @override
    async def find_latest(
        self,
        *,
        task_type: str,
        subject_type: str,
        subject_id: int,
        status: WorkItemStatus | None = None,
    ) -> WorkItem | None:
        statement = select(WorkItemModel).where(
            WorkItemModel.task_type == task_type,
            WorkItemModel.subject_type == subject_type,
            WorkItemModel.subject_id == subject_id,
        )
        if status is not None:
            statement = statement.where(WorkItemModel.status == status.value)
        statement = statement.order_by(WorkItemModel.id.desc()).limit(1)
        try:
            model = await self._session.scalar(statement)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _item(model) if model is not None else None

    @override
    async def list_outcome_due(
        self,
        *,
        task_type: str,
        outcome_code: str,
        completed_before: datetime,
        limit: int,
    ) -> list[WorkItem]:
        statement = (
            select(WorkItemModel)
            .where(
                WorkItemModel.task_type == task_type,
                WorkItemModel.status == WorkItemStatus.SUCCEEDED.value,
                WorkItemModel.outcome_code == outcome_code,
                WorkItemModel.completed_at.is_not(None),
                WorkItemModel.completed_at <= completed_before,
                WorkItemModel.subject_type == "video",
                WorkItemModel.subject_id.is_not(None),
            )
            .order_by(WorkItemModel.completed_at, WorkItemModel.id)
            .limit(limit)
        )
        try:
            models = list((await self._session.scalars(statement)).all())
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return [_item(model) for model in models]

    @override
    async def add_dependency(
        self,
        *,
        work_item_id: int,
        dependency_work_item_id: int,
        requires_successful_output: bool = True,
    ) -> None:
        existing = await self._session.get(
            WorkItemDependencyModel,
            (work_item_id, dependency_work_item_id),
        )
        if existing is not None:
            return
        self._session.add(
            WorkItemDependencyModel(
                work_item_id=work_item_id,
                dependency_work_item_id=dependency_work_item_id,
                requires_successful_output=requires_successful_output,
            )
        )
        try:
            await self._session.flush()
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc

    @override
    async def start_inline(
        self,
        *,
        work_item_id: int,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> WorkItem | None:
        statement = (
            update(WorkItemModel)
            .where(
                WorkItemModel.id == work_item_id,
                WorkItemModel.status == WorkItemStatus.PENDING.value,
                WorkItemModel.execution_mode == WorkExecutionMode.INLINE.value,
            )
            .values(
                status=WorkItemStatus.RUNNING.value,
                lease_owner=worker_id,
                lease_expires_at=lease_expires_at,
                heartbeat_at=now,
                started_at=func.coalesce(WorkItemModel.started_at, now),
                updated_at=now,
            )
            .returning(WorkItemModel.id)
        )
        try:
            started_id = (await self._session.execute(statement)).scalar_one_or_none()
            if started_id is None:
                return None
            model = await self._session.get(WorkItemModel, started_id)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        if model is None:
            raise WorkPersistenceError("Started work item disappeared.")
        return _item(model)

    @override
    async def claim_next(
        self,
        *,
        task_types: tuple[str, ...],
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> WorkItem | None:
        if not task_types:
            return None
        upstream = aliased(WorkItemModel)
        unsatisfied_dependency = exists(
            select(WorkItemDependencyModel.work_item_id)
            .join(
                upstream,
                upstream.id == WorkItemDependencyModel.dependency_work_item_id,
            )
            .where(
                WorkItemDependencyModel.work_item_id == WorkItemModel.id,
                or_(
                    upstream.status != WorkItemStatus.SUCCEEDED.value,
                    and_(
                        WorkItemDependencyModel.requires_successful_output.is_(True),
                        upstream.outcome_code.is_not(None),
                    ),
                ),
            )
        )
        candidate_id = (
            select(WorkItemModel.id)
            .where(
                WorkItemModel.status == WorkItemStatus.PENDING.value,
                WorkItemModel.execution_mode == WorkExecutionMode.WORKER.value,
                WorkItemModel.task_type.in_(task_types),
                WorkItemModel.available_at <= now,
                ~unsatisfied_dependency,
            )
            .order_by(
                WorkItemModel.priority.desc(),
                WorkItemModel.available_at,
                WorkItemModel.id,
            )
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(WorkItemModel)
            .where(
                WorkItemModel.id == candidate_id,
                WorkItemModel.status == WorkItemStatus.PENDING.value,
            )
            .values(
                status=WorkItemStatus.RUNNING.value,
                lease_owner=worker_id,
                lease_expires_at=lease_expires_at,
                heartbeat_at=now,
                started_at=func.coalesce(WorkItemModel.started_at, now),
                updated_at=now,
            )
            .returning(WorkItemModel.id)
        )
        try:
            work_item_id = (await self._session.execute(statement)).scalar_one_or_none()
            if work_item_id is None:
                return None
            model = await self._session.get(WorkItemModel, work_item_id)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        if model is None:
            raise WorkPersistenceError("Claimed work item disappeared.")
        return _item(model)

    @override
    async def heartbeat(
        self,
        *,
        work_item_id: int,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        statement = (
            update(WorkItemModel)
            .where(
                WorkItemModel.id == work_item_id,
                WorkItemModel.status == WorkItemStatus.RUNNING.value,
                WorkItemModel.lease_owner == worker_id,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=lease_expires_at,
                updated_at=now,
            )
            .returning(WorkItemModel.id)
        )
        try:
            updated_id = (await self._session.execute(statement)).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return updated_id is not None

    @override
    async def mark_succeeded(
        self,
        *,
        work_item_id: int,
        now: datetime,
        output_json: JsonObject,
        output_transcript_id: int | None = None,
        outcome_code: str | None = None,
    ) -> WorkItem:
        model = await self._required(work_item_id)
        _require_status(model, {WorkItemStatus.RUNNING}, "complete")
        model.status = WorkItemStatus.SUCCEEDED.value
        model.outcome_code = outcome_code
        model.output_json = output_json
        model.output_transcript_id = output_transcript_id
        _finish(model, now)
        return await self._flush_item(model)

    @override
    async def mark_failed(
        self,
        *,
        work_item_id: int,
        now: datetime,
        error_code: str,
        error_type: str,
        error_message: str,
        timed_out: bool = False,
        output_json: JsonObject | None = None,
    ) -> WorkItem:
        model = await self._required(work_item_id)
        _require_status(model, {WorkItemStatus.RUNNING}, "fail")
        model.status = WorkItemStatus.TIMED_OUT.value if timed_out else WorkItemStatus.FAILED.value
        model.error_code = error_code
        model.error_type = error_type
        model.error_message = error_message
        model.output_json = output_json
        _finish(model, now)
        return await self._flush_item(model)

    @override
    async def reset_for_retry(
        self,
        *,
        work_item_id: int,
        now: datetime,
        allow_succeeded: bool,
    ) -> WorkItem:
        model = await self._required(work_item_id)
        allowed = {
            WorkItemStatus.FAILED,
            WorkItemStatus.TIMED_OUT,
            WorkItemStatus.BLOCKED,
        }
        if allow_succeeded:
            allowed.add(WorkItemStatus.SUCCEEDED)
        _require_status(model, allowed, "retry")
        model.status = WorkItemStatus.PENDING.value
        model.outcome_code = None
        model.output_json = None
        model.output_transcript_id = None
        model.error_code = None
        model.error_type = None
        model.error_message = None
        model.lease_owner = None
        model.lease_expires_at = None
        model.heartbeat_at = None
        model.available_at = now
        model.completed_at = None
        model.updated_at = now
        return await self._flush_item(model)

    @override
    async def cancel(self, *, work_item_id: int, now: datetime, reason: str) -> WorkItem:
        model = await self._required(work_item_id)
        _require_status(
            model,
            {WorkItemStatus.PENDING, WorkItemStatus.RUNNING},
            "cancel",
        )
        model.status = WorkItemStatus.CANCELED.value
        model.outcome_code = "canceled"
        model.error_message = reason
        _finish(model, now)
        return await self._flush_item(model)

    @override
    async def cancel_pending_for_subject(
        self,
        *,
        subject_type: str,
        subject_id: int,
        task_types: tuple[str, ...],
        now: datetime,
        outcome_code: str,
        reason: str,
    ) -> int:
        if not task_types:
            return 0
        statement = (
            update(WorkItemModel)
            .where(
                WorkItemModel.subject_type == subject_type,
                WorkItemModel.subject_id == subject_id,
                WorkItemModel.task_type.in_(task_types),
                WorkItemModel.status == WorkItemStatus.PENDING.value,
            )
            .values(
                status=WorkItemStatus.CANCELED.value,
                outcome_code=outcome_code,
                error_code=f"work.{outcome_code}",
                error_type="VideoNotEmbeddable",
                error_message=reason,
                completed_at=now,
                updated_at=now,
            )
            .returning(WorkItemModel.id)
        )
        try:
            result = await self._session.execute(statement)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return len(result.scalars().all())

    @override
    async def mark_dependency_blocked(self, *, now: datetime) -> int:
        upstream = aliased(WorkItemModel)
        failed_dependency = exists(
            select(WorkItemDependencyModel.work_item_id)
            .join(
                upstream,
                upstream.id == WorkItemDependencyModel.dependency_work_item_id,
            )
            .where(
                WorkItemDependencyModel.work_item_id == WorkItemModel.id,
                or_(
                    upstream.status.in_(
                        (
                            WorkItemStatus.FAILED.value,
                            WorkItemStatus.TIMED_OUT.value,
                            WorkItemStatus.BLOCKED.value,
                            WorkItemStatus.CANCELED.value,
                        )
                    ),
                    and_(
                        WorkItemDependencyModel.requires_successful_output.is_(True),
                        upstream.status == WorkItemStatus.SUCCEEDED.value,
                        upstream.outcome_code.is_not(None),
                    ),
                ),
            )
        )
        statement = (
            update(WorkItemModel)
            .where(
                WorkItemModel.status == WorkItemStatus.PENDING.value,
                failed_dependency,
            )
            .values(
                status=WorkItemStatus.BLOCKED.value,
                outcome_code="dependency_failed",
                error_code="work.dependency_failed",
                error_message="A required work item did not produce a usable result.",
                completed_at=now,
                updated_at=now,
            )
            .returning(WorkItemModel.id)
        )
        try:
            updated_ids = list((await self._session.execute(statement)).scalars())
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return len(updated_ids)

    @override
    async def recover_expired_leases(self, *, now: datetime) -> int:
        expired_ids = list(
            (
                await self._session.scalars(
                    select(WorkItemModel.id).where(
                        WorkItemModel.status == WorkItemStatus.RUNNING.value,
                        WorkItemModel.lease_expires_at.is_not(None),
                        WorkItemModel.lease_expires_at <= now,
                    )
                )
            ).all()
        )
        if not expired_ids:
            return 0
        await self._session.execute(
            update(WorkAttemptModel)
            .where(
                WorkAttemptModel.work_item_id.in_(expired_ids),
                WorkAttemptModel.status == WorkAttemptStatus.RUNNING.value,
            )
            .values(
                status=WorkAttemptStatus.TIMED_OUT.value,
                finished_at=now,
                error_code="work.lease_expired",
                error_type="WorkLeaseExpired",
                error_message="The worker lease expired before completion.",
            )
        )
        await self._session.execute(
            update(WorkItemModel)
            .where(WorkItemModel.id.in_(expired_ids))
            .values(
                status=WorkItemStatus.TIMED_OUT.value,
                error_code="work.lease_expired",
                error_type="WorkLeaseExpired",
                error_message="The worker lease expired before completion.",
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=None,
                completed_at=now,
                updated_at=now,
            )
        )
        return len(expired_ids)

    async def _required(self, work_item_id: int) -> WorkItemModel:
        model = await self._session.get(WorkItemModel, work_item_id)
        if model is None:
            raise WorkItemNotFound(work_item_id)
        return model

    async def _flush_item(self, model: WorkItemModel) -> WorkItem:
        try:
            await self._session.flush()
            await self._session.refresh(model)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _item(model)


class SqlAlchemyWorkAttemptRepository(WorkAttemptRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def list_for_work_item(self, work_item_id: int) -> list[WorkAttempt]:
        statement = (
            select(WorkAttemptModel)
            .where(WorkAttemptModel.work_item_id == work_item_id)
            .order_by(WorkAttemptModel.attempt_no)
        )
        try:
            models = list((await self._session.scalars(statement)).all())
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return [_attempt(model) for model in models]

    @override
    async def create(self, *, work_item_id: int, worker_id: str | None) -> WorkAttempt:
        attempt_no = (
            await self._session.scalar(
                select(func.coalesce(func.max(WorkAttemptModel.attempt_no), 0) + 1).where(
                    WorkAttemptModel.work_item_id == work_item_id
                )
            )
        ) or 1
        model = WorkAttemptModel(
            work_item_id=work_item_id,
            attempt_no=attempt_no,
            status=WorkAttemptStatus.RUNNING.value,
            worker_id=worker_id,
        )
        self._session.add(model)
        return await self._flush_attempt(model)

    @override
    async def mark_succeeded(
        self,
        *,
        attempt_id: int,
        now: datetime,
        output_json: JsonObject,
    ) -> WorkAttempt:
        model = await self._required(attempt_id)
        model.status = WorkAttemptStatus.SUCCEEDED.value
        model.finished_at = now
        model.output_json = output_json
        return await self._flush_attempt(model)

    @override
    async def mark_failed(
        self,
        *,
        attempt_id: int,
        now: datetime,
        error_code: str,
        error_type: str,
        error_message: str,
        timed_out: bool = False,
        output_json: JsonObject | None = None,
    ) -> WorkAttempt:
        model = await self._required(attempt_id)
        model.status = (
            WorkAttemptStatus.TIMED_OUT.value if timed_out else WorkAttemptStatus.FAILED.value
        )
        model.finished_at = now
        model.error_code = error_code
        model.error_type = error_type
        model.error_message = error_message
        model.output_json = output_json
        return await self._flush_attempt(model)

    async def _required(self, attempt_id: int) -> WorkAttemptModel:
        model = await self._session.get(WorkAttemptModel, attempt_id)
        if model is None:
            raise WorkPersistenceError("Work attempt was not found.")
        return model

    async def _flush_attempt(self, model: WorkAttemptModel) -> WorkAttempt:
        try:
            await self._session.flush()
            await self._session.refresh(model)
        except SQLAlchemyError as exc:
            raise WorkPersistenceError() from exc
        return _attempt(model)


def _require_status(
    model: WorkItemModel,
    allowed: set[WorkItemStatus],
    transition: str,
) -> None:
    status = WorkItemStatus(model.status)
    if status not in allowed:
        raise WorkItemTransitionNotAllowed(model.id, status=status.value, transition=transition)


def _finish(model: WorkItemModel, now: datetime) -> None:
    model.lease_owner = None
    model.lease_expires_at = None
    model.heartbeat_at = None
    model.completed_at = now
    model.updated_at = now


def _item(model: WorkItemModel) -> WorkItem:
    return WorkItem(
        id=model.id,
        task_type=model.task_type,
        subject_type=model.subject_type,
        subject_id=model.subject_id,
        external_key=model.external_key,
        task_version=model.task_version,
        input_hash=model.input_hash,
        idempotency_key=model.idempotency_key,
        execution_mode=WorkExecutionMode(model.execution_mode),
        status=WorkItemStatus(model.status),
        outcome_code=model.outcome_code,
        priority=model.priority,
        timeout_seconds=model.timeout_seconds,
        input_json=model.input_json,
        output_json=model.output_json,
        output_transcript_id=model.output_transcript_id,
        error_code=model.error_code,
        error_type=model.error_type,
        error_message=model.error_message,
        lease_owner=model.lease_owner,
        lease_expires_at=model.lease_expires_at,
        heartbeat_at=model.heartbeat_at,
        available_at=model.available_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _attempt(model: WorkAttemptModel) -> WorkAttempt:
    return WorkAttempt(
        id=model.id,
        work_item_id=model.work_item_id,
        attempt_no=model.attempt_no,
        status=WorkAttemptStatus(model.status),
        worker_id=model.worker_id,
        started_at=model.started_at,
        finished_at=model.finished_at,
        output_json=model.output_json,
        error_code=model.error_code,
        error_type=model.error_type,
        error_message=model.error_message,
    )
