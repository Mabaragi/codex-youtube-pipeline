from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select
from typing_extensions import override

from codex_sdk_cli.domains.video_tasks.exceptions import (
    VideoTaskNotFound,
    VideoTaskPersistenceError,
)
from codex_sdk_cli.domains.video_tasks.ports import (
    JsonObject,
    VideoTaskCreate,
    VideoTaskListQuery,
    VideoTaskListRecord,
    VideoTaskRecord,
    VideoTaskRepositoryPort,
    VideoTaskStatus,
)
from codex_sdk_cli.infra.database.base import Base


class VideoTaskModel(Base):
    __tablename__ = "video_tasks"
    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "task_name",
            "task_version",
            "input_hash",
            name="uq_video_tasks_video_task_version_hash",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', "
            "'timed_out', 'skipped', 'canceled')",
            name="video_tasks_status_allowed",
        ),
        CheckConstraint("timeout_seconds >= 1", name="video_tasks_timeout_seconds_min"),
        Index("ix_video_tasks_task_status", "task_name", "status"),
        Index("ix_video_tasks_video_task", "video_id", "task_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    task_name: Mapped[str] = mapped_column(String(64), nullable=False)
    task_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    job_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_job_attempts.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    output_transcript_id: Mapped[int | None] = mapped_column(
        ForeignKey("youtube_transcripts.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    output_json: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SqlAlchemyVideoTaskRepository(VideoTaskRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get_task(self, task_id: int) -> VideoTaskRecord | None:
        try:
            model = await self._session.get(VideoTaskModel, task_id)
        except SQLAlchemyError as exc:
            raise VideoTaskPersistenceError("Video task persistence failed.") from exc
        return _task_record(model) if model is not None else None

    @override
    async def get_task_for_input(
        self,
        *,
        video_id: int,
        task_name: str,
        task_version: str,
        input_hash: str,
    ) -> VideoTaskRecord | None:
        try:
            model = await self._get_task_model_for_input(
                video_id=video_id,
                task_name=task_name,
                task_version=task_version,
                input_hash=input_hash,
            )
        except SQLAlchemyError as exc:
            raise VideoTaskPersistenceError("Video task persistence failed.") from exc
        return _task_record(model) if model is not None else None

    @override
    async def get_or_create_task(self, task: VideoTaskCreate) -> VideoTaskRecord:
        try:
            existing = await self._get_task_model_for_input(
                video_id=task.video_id,
                task_name=task.task_name,
                task_version=task.task_version,
                input_hash=task.input_hash,
            )
            if existing is not None:
                return _task_record(existing)
            model = VideoTaskModel(
                video_id=task.video_id,
                task_name=task.task_name,
                task_version=task.task_version,
                input_hash=task.input_hash,
                status=task.status,
                timeout_seconds=task.timeout_seconds,
            )
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _task_record(model)
        except IntegrityError:
            await self._session.rollback()
            existing = await self._get_task_model_for_input(
                video_id=task.video_id,
                task_name=task.task_name,
                task_version=task.task_version,
                input_hash=task.input_hash,
            )
            if existing is None:
                raise VideoTaskPersistenceError("Video task persistence failed.") from None
            return _task_record(existing)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise VideoTaskPersistenceError("Video task persistence failed.") from exc

    @override
    async def list_tasks(self, query: VideoTaskListQuery) -> list[VideoTaskListRecord]:
        from codex_sdk_cli.infra.videos.repository import VideoModel

        try:
            statement = (
                select(VideoTaskModel, VideoModel.youtube_video_id)
                .join(VideoModel, VideoTaskModel.video_id == VideoModel.id)
                .where(VideoModel.channel_id == query.channel_id)
                .order_by(VideoTaskModel.id.desc())
                .limit(query.limit)
                .offset(query.offset)
            )
            if query.task_name is not None:
                statement = statement.where(VideoTaskModel.task_name == query.task_name)
            if query.status is not None:
                statement = statement.where(VideoTaskModel.status == query.status)
            rows = (await self._session.execute(statement)).all()
            return [
                VideoTaskListRecord(
                    task=_task_record(task),
                    youtube_video_id=youtube_video_id,
                )
                for task, youtube_video_id in rows
            ]
        except SQLAlchemyError as exc:
            raise VideoTaskPersistenceError("Video task persistence failed.") from exc

    @override
    async def count_running(self, *, task_name: str) -> int:
        try:
            count = await self._session.scalar(
                select(func.count())
                .select_from(VideoTaskModel)
                .where(
                    VideoTaskModel.task_name == task_name,
                    VideoTaskModel.status == "running",
                )
            )
            return count or 0
        except SQLAlchemyError as exc:
            raise VideoTaskPersistenceError("Video task persistence failed.") from exc

    @override
    async def mark_task_running(
        self,
        task_id: int,
        *,
        worker_id: str,
        timeout_seconds: int,
        job_id: int,
        job_attempt_id: int,
    ) -> VideoTaskRecord:
        try:
            model = await self._get_task_model_or_raise(task_id)
            model.status = "running"
            model.worker_id = worker_id
            model.timeout_seconds = timeout_seconds
            model.job_id = job_id
            model.job_attempt_id = job_attempt_id
            model.error_type = None
            model.error_message = None
            model.started_at = datetime.now(UTC)
            model.completed_at = None
            await self._session.commit()
            await self._session.refresh(model)
            return _task_record(model)
        except VideoTaskNotFound:
            await self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise VideoTaskPersistenceError("Video task persistence failed.") from exc

    @override
    async def mark_task_succeeded(
        self,
        task_id: int,
        *,
        output_transcript_id: int | None,
        output_json: JsonObject,
    ) -> VideoTaskRecord:
        return await self._mark_task_finished(
            task_id,
            status="succeeded",
            output_transcript_id=output_transcript_id,
            output_json=output_json,
            error_type=None,
            error_message=None,
        )

    @override
    async def mark_task_failed(
        self,
        task_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        return await self._mark_task_finished(
            task_id,
            status="failed",
            output_transcript_id=None,
            output_json=output_json,
            error_type=error_type,
            error_message=error_message,
        )

    @override
    async def mark_task_timed_out(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        return await self._mark_task_finished(
            task_id,
            status="timed_out",
            output_transcript_id=None,
            output_json=output_json,
            error_type="TimeoutError",
            error_message=error_message,
        )

    async def _get_task_model_for_input(
        self,
        *,
        video_id: int,
        task_name: str,
        task_version: str,
        input_hash: str,
    ) -> VideoTaskModel | None:
        return await self._session.scalar(
            select(VideoTaskModel).where(
                VideoTaskModel.video_id == video_id,
                VideoTaskModel.task_name == task_name,
                VideoTaskModel.task_version == task_version,
                VideoTaskModel.input_hash == input_hash,
            )
        )

    async def _get_task_model_or_raise(self, task_id: int) -> VideoTaskModel:
        model = await self._session.get(VideoTaskModel, task_id)
        if model is None:
            raise VideoTaskNotFound("Video task not found.")
        return model

    async def _mark_task_finished(
        self,
        task_id: int,
        *,
        status: VideoTaskStatus,
        output_transcript_id: int | None,
        output_json: JsonObject | None,
        error_type: str | None,
        error_message: str | None,
    ) -> VideoTaskRecord:
        try:
            model = await self._get_task_model_or_raise(task_id)
            model.status = status
            model.output_transcript_id = output_transcript_id
            model.output_json = output_json
            model.error_type = error_type
            model.error_message = error_message
            model.completed_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(model)
            return _task_record(model)
        except VideoTaskNotFound:
            await self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise VideoTaskPersistenceError("Video task persistence failed.") from exc


def _task_record(model: VideoTaskModel) -> VideoTaskRecord:
    return VideoTaskRecord(
        id=model.id,
        video_id=model.video_id,
        task_name=model.task_name,
        task_version=model.task_version,
        input_hash=model.input_hash,
        status=_task_status(model.status),
        worker_id=model.worker_id,
        timeout_seconds=model.timeout_seconds,
        job_id=model.job_id,
        job_attempt_id=model.job_attempt_id,
        output_transcript_id=model.output_transcript_id,
        output_json=model.output_json,
        error_type=model.error_type,
        error_message=model.error_message,
        started_at=model.started_at,
        completed_at=model.completed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _task_status(value: str) -> VideoTaskStatus:
    if value == "pending":
        return "pending"
    if value == "succeeded":
        return "succeeded"
    if value == "failed":
        return "failed"
    if value == "timed_out":
        return "timed_out"
    if value == "skipped":
        return "skipped"
    if value == "canceled":
        return "canceled"
    return "running"
