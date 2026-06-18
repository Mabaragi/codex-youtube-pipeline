"""SQLAlchemy repository for operation events."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import override

from codex_sdk_cli.domains.operation_events.exceptions import (
    OperationEventPersistenceError,
)
from codex_sdk_cli.domains.operation_events.ports import (
    JsonObject,
    OperationEventActorType,
    OperationEventCreate,
    OperationEventListQuery,
    OperationEventRecord,
    OperationEventRepositoryPort,
    OperationEventSeverity,
)
from codex_sdk_cli.infra.database.base import Base


class OperationEventModel(Base):
    __tablename__ = "operation_events"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_operation_events_severity",
        ),
        CheckConstraint(
            "actor_type IN ('manual_api', 'retry_executor', 'system')",
            name="ck_operation_events_actor_type",
        ),
        Index("ix_operation_events_subject", "subject_type", "subject_id"),
        Index("ix_operation_events_occurred_at", "occurred_at"),
        Index("ix_operation_events_event_type", "event_type"),
        Index("ix_operation_events_severity", "severity"),
        Index("ix_operation_events_job_id", "job_id"),
        Index("ix_operation_events_video_task_id", "video_task_id"),
        Index("ix_operation_events_correlation_id", "correlation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)

    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_job_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    video_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_api_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_api_calls.id", ondelete="SET NULL"),
        nullable=True,
    )

    subject_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class SQLAlchemyOperationEventRepository(OperationEventRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_event(self, event: OperationEventCreate) -> OperationEventRecord:
        model = OperationEventModel(
            event_type=event.event_type,
            severity=event.severity,
            message=event.message,
            actor_type=event.actor_type,
            source=event.source,
            metadata_json=event.metadata_json,
            job_id=event.job_id,
            job_attempt_id=event.job_attempt_id,
            video_task_id=event.video_task_id,
            channel_id=event.channel_id,
            video_id=event.video_id,
            external_api_call_id=event.external_api_call_id,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            external_key=event.external_key,
            correlation_id=event.correlation_id,
            error_type=event.error_type,
            error_message=event.error_message,
        )
        self._session.add(model)
        try:
            await self._session.commit()
            await self._session.refresh(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise OperationEventPersistenceError("Failed to create operation event.") from exc
        return _record_from_model(model)

    @override
    async def list_events(self, query: OperationEventListQuery) -> list[OperationEventRecord]:
        statement = select(OperationEventModel)
        if query.severity is not None:
            statement = statement.where(OperationEventModel.severity == query.severity)
        if query.event_type is not None:
            statement = statement.where(OperationEventModel.event_type == query.event_type)
        if query.subject_type is not None:
            statement = statement.where(OperationEventModel.subject_type == query.subject_type)
        if query.subject_id is not None:
            statement = statement.where(OperationEventModel.subject_id == query.subject_id)
        if query.job_id is not None:
            statement = statement.where(OperationEventModel.job_id == query.job_id)
        if query.video_task_id is not None:
            statement = statement.where(OperationEventModel.video_task_id == query.video_task_id)
        if query.channel_id is not None:
            statement = statement.where(OperationEventModel.channel_id == query.channel_id)
        if query.video_id is not None:
            statement = statement.where(OperationEventModel.video_id == query.video_id)
        if query.cursor is not None:
            statement = statement.where(OperationEventModel.id < query.cursor)
        statement = statement.order_by(OperationEventModel.id.desc()).limit(query.limit)
        try:
            result = await self._session.execute(statement)
        except SQLAlchemyError as exc:
            raise OperationEventPersistenceError("Failed to list operation events.") from exc
        return [_record_from_model(model) for model in result.scalars().all()]


def _record_from_model(model: OperationEventModel) -> OperationEventRecord:
    return OperationEventRecord(
        id=model.id,
        occurred_at=model.occurred_at,
        event_type=model.event_type,
        severity=cast(OperationEventSeverity, model.severity),
        message=model.message,
        actor_type=cast(OperationEventActorType, model.actor_type),
        source=model.source,
        metadata_json=model.metadata_json,
        job_id=model.job_id,
        job_attempt_id=model.job_attempt_id,
        video_task_id=model.video_task_id,
        channel_id=model.channel_id,
        video_id=model.video_id,
        external_api_call_id=model.external_api_call_id,
        subject_type=model.subject_type,
        subject_id=model.subject_id,
        external_key=model.external_key,
        correlation_id=model.correlation_id,
        error_type=model.error_type,
        error_message=model.error_message,
    )

