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
    and_,
    exists,
    func,
    or_,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select
from typing_extensions import override

from codex_sdk_cli.domains.pipeline_jobs.exceptions import PipelineJobPersistenceError
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    ExternalApiCallSummaryRecord,
    JsonObject,
    PipelineChannelOutputRecord,
    PipelineJobAttemptRecord,
    PipelineJobAttemptStatus,
    PipelineJobCreate,
    PipelineJobDetailRecord,
    PipelineJobListQuery,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
    PipelineJobStatus,
    PipelineJobSummaryRecord,
    PipelineTranscriptOutputRecord,
    PipelineVideoOutputRecord,
)
from codex_sdk_cli.infra.database.base import Base


class PipelineJobModel(Base):
    __tablename__ = "pipeline_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'canceled')",
            name="pipeline_jobs_status_allowed",
        ),
        Index("ix_pipeline_jobs_step_status", "step", "status"),
        Index("ix_pipeline_jobs_subject", "subject_type", "subject_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    step: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    parent_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PipelineJobAttemptModel(Base):
    __tablename__ = "pipeline_job_attempts"
    __table_args__ = (
        CheckConstraint("attempt_no >= 1", name="pipeline_job_attempts_attempt_no_min"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'canceled')",
            name="pipeline_job_attempts_status_allowed",
        ),
        UniqueConstraint("job_id", "attempt_no", name="uq_pipeline_job_attempts_job_attempt_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)


class SqlAlchemyPipelineJobRepository(PipelineJobRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_job(self, job: PipelineJobCreate) -> PipelineJobRecord:
        try:
            model = PipelineJobModel(
                step=job.step,
                status=job.status,
                subject_type=job.subject_type,
                subject_id=job.subject_id,
                external_key=job.external_key,
                input_json=job.input_json,
                input_hash=job.input_hash,
                parent_job_id=job.parent_job_id,
            )
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _job_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise PipelineJobPersistenceError("Pipeline job persistence failed.") from exc

    @override
    async def get_job(self, job_id: int) -> PipelineJobRecord | None:
        try:
            model = await self._session.get(PipelineJobModel, job_id)
            if model is None:
                return None
            return _job_record(model)
        except SQLAlchemyError as exc:
            raise PipelineJobPersistenceError("Pipeline job persistence failed.") from exc

    @override
    async def list_job_summaries(
        self,
        query: PipelineJobListQuery,
    ) -> list[PipelineJobSummaryRecord]:
        try:
            statement = select(PipelineJobModel)
            if query.step is not None:
                statement = statement.where(PipelineJobModel.step == query.step)
            if query.status is not None:
                statement = statement.where(PipelineJobModel.status == query.status)
            if query.channel_id is not None:
                statement = statement.where(_job_channel_filter(query.channel_id))
            if query.subject_type is not None:
                statement = statement.where(PipelineJobModel.subject_type == query.subject_type)
            if query.subject_id is not None:
                statement = statement.where(PipelineJobModel.subject_id == query.subject_id)
            if query.external_key is not None:
                statement = statement.where(PipelineJobModel.external_key == query.external_key)
            if query.cursor is not None:
                statement = statement.where(PipelineJobModel.id < query.cursor)
            statement = statement.order_by(PipelineJobModel.id.desc()).limit(query.limit)
            models = list((await self._session.scalars(statement)).all())
            return await self._job_summaries(models)
        except SQLAlchemyError as exc:
            raise PipelineJobPersistenceError("Pipeline job persistence failed.") from exc

    @override
    async def get_job_detail(self, job_id: int) -> PipelineJobDetailRecord | None:
        try:
            model = await self._session.get(PipelineJobModel, job_id)
            if model is None:
                return None
            attempts = list(
                (
                    await self._session.scalars(
                        select(PipelineJobAttemptModel)
                        .where(PipelineJobAttemptModel.job_id == job_id)
                        .order_by(PipelineJobAttemptModel.attempt_no.asc())
                    )
                ).all()
            )
            return PipelineJobDetailRecord(
                job=_job_record(model),
                attempts=[_attempt_record(attempt) for attempt in attempts],
                external_api_calls=await self._external_api_call_summaries(attempts),
                channels=await self._channel_outputs(job_id, attempts),
                videos=await self._video_outputs(job_id, attempts),
                transcripts=await self._transcript_outputs(job_id),
            )
        except SQLAlchemyError as exc:
            raise PipelineJobPersistenceError("Pipeline job persistence failed.") from exc

    @override
    async def create_attempt(
        self,
        *,
        job_id: int,
        worker_id: str | None = None,
    ) -> PipelineJobAttemptRecord:
        try:
            attempt_no = await self._next_attempt_no(job_id)
            model = PipelineJobAttemptModel(
                job_id=job_id,
                attempt_no=attempt_no,
                status="running",
                worker_id=worker_id,
            )
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _attempt_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise PipelineJobPersistenceError("Pipeline job persistence failed.") from exc

    @override
    async def mark_attempt_succeeded(
        self,
        attempt_id: int,
        *,
        output_json: JsonObject,
    ) -> PipelineJobAttemptRecord:
        return await self._mark_attempt_finished(
            attempt_id,
            status="succeeded",
            output_json=output_json,
            error_type=None,
            error_message=None,
        )

    @override
    async def mark_attempt_failed(
        self,
        attempt_id: int,
        *,
        error_type: str,
        error_message: str,
    ) -> PipelineJobAttemptRecord:
        return await self._mark_attempt_finished(
            attempt_id,
            status="failed",
            output_json=None,
            error_type=error_type,
            error_message=error_message,
        )

    @override
    async def mark_job_succeeded(self, job_id: int) -> PipelineJobRecord:
        return await self._mark_job_finished(job_id, status="succeeded")

    @override
    async def mark_job_failed(self, job_id: int) -> PipelineJobRecord:
        return await self._mark_job_finished(job_id, status="failed")

    @override
    async def mark_job_running(self, job_id: int) -> PipelineJobRecord:
        try:
            model = await self._session.get(PipelineJobModel, job_id)
            if model is None:
                raise PipelineJobPersistenceError("Pipeline job was not found.")
            model.status = "running"
            model.completed_at = None
            await self._session.commit()
            await self._session.refresh(model)
            return _job_record(model)
        except PipelineJobPersistenceError:
            await self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise PipelineJobPersistenceError("Pipeline job persistence failed.") from exc

    async def _next_attempt_no(self, job_id: int) -> int:
        current = await self._session.scalar(
            select(func.max(PipelineJobAttemptModel.attempt_no)).where(
                PipelineJobAttemptModel.job_id == job_id
            )
        )
        return 1 if current is None else current + 1

    async def _job_summaries(
        self,
        models: list[PipelineJobModel],
    ) -> list[PipelineJobSummaryRecord]:
        job_ids = [model.id for model in models]
        attempts_by_job: dict[int, list[PipelineJobAttemptModel]] = {
            job_id: [] for job_id in job_ids
        }
        if job_ids:
            attempts = (
                await self._session.scalars(
                    select(PipelineJobAttemptModel)
                    .where(PipelineJobAttemptModel.job_id.in_(job_ids))
                    .order_by(
                        PipelineJobAttemptModel.job_id.asc(),
                        PipelineJobAttemptModel.attempt_no.asc(),
                    )
                )
            ).all()
            for attempt in attempts:
                attempts_by_job.setdefault(attempt.job_id, []).append(attempt)

        summaries: list[PipelineJobSummaryRecord] = []
        for model in models:
            attempts = attempts_by_job.get(model.id, [])
            latest = attempts[-1] if attempts else None
            summaries.append(
                PipelineJobSummaryRecord(
                    job=_job_record(model),
                    latest_attempt_id=latest.id if latest is not None else None,
                    latest_attempt_status=(
                        _attempt_status(latest.status) if latest is not None else None
                    ),
                    attempt_count=len(attempts),
                )
            )
        return summaries

    async def _external_api_call_summaries(
        self,
        attempts: list[PipelineJobAttemptModel],
    ) -> list[ExternalApiCallSummaryRecord]:
        from codex_sdk_cli.infra.external_api_calls.repository import ExternalApiCallModel

        attempt_ids = [attempt.id for attempt in attempts]
        if not attempt_ids:
            return []
        calls = (
            await self._session.scalars(
                select(ExternalApiCallModel)
                .where(ExternalApiCallModel.pipeline_job_attempt_id.in_(attempt_ids))
                .order_by(ExternalApiCallModel.created_at.asc(), ExternalApiCallModel.id.asc())
            )
        ).all()
        return [
            ExternalApiCallSummaryRecord(
                id=call.id,
                pipeline_job_attempt_id=call.pipeline_job_attempt_id,
                provider=call.provider,
                operation=call.operation,
                response_status_code=call.response_status_code,
                validation_status=call.validation_status,
                response_storage_uri=call.response_storage_uri,
                duration_ms=call.duration_ms,
                quota_cost=call.quota_cost,
                created_at=call.created_at,
            )
            for call in calls
        ]

    async def _channel_outputs(
        self,
        job_id: int,
        attempts: list[PipelineJobAttemptModel],
    ) -> list[PipelineChannelOutputRecord]:
        from codex_sdk_cli.infra.channels.repository import ChannelModel

        output_channel_ids = [
            channel_id
            for attempt in attempts
            if attempt.output_json is not None
            for channel_id in [_output_channel_id(attempt.output_json)]
            if channel_id is not None
        ]
        filters = [ChannelModel.source_job_id == job_id]
        if output_channel_ids:
            filters.append(ChannelModel.id.in_(output_channel_ids))
        channels = (
            await self._session.scalars(
                select(ChannelModel)
                .where(or_(*filters))
                .order_by(ChannelModel.id.asc())
            )
        ).all()
        return [
            PipelineChannelOutputRecord(
                id=channel.id,
                streamer_id=channel.streamer_id,
                handle=channel.handle,
                name=channel.name,
                youtube_channel_id=channel.youtube_channel_id,
                source_api_call_id=channel.source_api_call_id,
                uploads_playlist_id=channel.uploads_playlist_id,
                source_job_id=channel.source_job_id,
            )
            for channel in channels
        ]

    async def _video_outputs(
        self,
        job_id: int,
        attempts: list[PipelineJobAttemptModel],
    ) -> list[PipelineVideoOutputRecord]:
        from codex_sdk_cli.infra.videos.repository import VideoModel

        output_video_ids = [
            video_id
            for attempt in attempts
            if attempt.output_json is not None
            for video_id in _output_video_ids(attempt.output_json)
        ]
        filters = [VideoModel.source_job_id == job_id]
        if output_video_ids:
            filters.append(VideoModel.id.in_(output_video_ids))
        videos = (
            await self._session.scalars(
                select(VideoModel)
                .where(or_(*filters))
                .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
            )
        ).all()
        return [
            PipelineVideoOutputRecord(
                id=video.id,
                channel_id=video.channel_id,
                youtube_video_id=video.youtube_video_id,
                title=video.title,
                published_at=video.published_at,
                source_listing_api_call_id=video.source_listing_api_call_id,
                source_details_api_call_id=video.source_details_api_call_id,
                source_job_id=video.source_job_id,
            )
            for video in videos
        ]

    async def _transcript_outputs(self, job_id: int) -> list[PipelineTranscriptOutputRecord]:
        from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel
        from codex_sdk_cli.infra.videos.repository import VideoModel
        from codex_sdk_cli.infra.youtube_transcripts.repository import (
            YouTubeTranscriptRecordModel,
        )

        rows = (
            await self._session.execute(
                select(VideoTaskModel, VideoModel, YouTubeTranscriptRecordModel)
                .join(VideoModel, VideoTaskModel.video_id == VideoModel.id)
                .join(
                    YouTubeTranscriptRecordModel,
                    VideoTaskModel.output_transcript_id == YouTubeTranscriptRecordModel.id,
                )
                .where(VideoTaskModel.job_id == job_id)
                .order_by(VideoTaskModel.id.asc())
            )
        ).all()
        return [
            PipelineTranscriptOutputRecord(
                id=transcript.id,
                video_task_id=task.id,
                video_id=task.video_id,
                youtube_video_id=video.youtube_video_id,
                language_code=transcript.language_code,
                storage_uri=transcript.storage_uri,
            )
            for task, video, transcript in rows
        ]

    async def _mark_attempt_finished(
        self,
        attempt_id: int,
        *,
        status: PipelineJobAttemptStatus,
        output_json: JsonObject | None,
        error_type: str | None,
        error_message: str | None,
    ) -> PipelineJobAttemptRecord:
        try:
            model = await self._session.get(PipelineJobAttemptModel, attempt_id)
            if model is None:
                raise PipelineJobPersistenceError("Pipeline job attempt was not found.")
            model.status = status
            model.output_json = output_json
            model.error_type = error_type
            model.error_message = error_message
            model.finished_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(model)
            return _attempt_record(model)
        except PipelineJobPersistenceError:
            await self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise PipelineJobPersistenceError("Pipeline job persistence failed.") from exc

    async def _mark_job_finished(
        self,
        job_id: int,
        *,
        status: PipelineJobStatus,
    ) -> PipelineJobRecord:
        try:
            model = await self._session.get(PipelineJobModel, job_id)
            if model is None:
                raise PipelineJobPersistenceError("Pipeline job was not found.")
            model.status = status
            model.completed_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(model)
            return _job_record(model)
        except PipelineJobPersistenceError:
            await self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise PipelineJobPersistenceError("Pipeline job persistence failed.") from exc


def _job_status(value: str) -> PipelineJobStatus:
    if value == "pending":
        return "pending"
    if value == "succeeded":
        return "succeeded"
    if value == "failed":
        return "failed"
    if value == "skipped":
        return "skipped"
    if value == "canceled":
        return "canceled"
    return "running"


def _attempt_status(value: str) -> PipelineJobAttemptStatus:
    if value == "succeeded":
        return "succeeded"
    if value == "failed":
        return "failed"
    if value == "canceled":
        return "canceled"
    return "running"


def _output_channel_id(output_json: JsonObject) -> int | None:
    value = output_json.get("channelId")
    return value if isinstance(value, int) else None


def _job_channel_filter(channel_id: int):
    from codex_sdk_cli.infra.channels.repository import ChannelModel
    from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel
    from codex_sdk_cli.infra.videos.repository import VideoModel

    return or_(
        and_(
            PipelineJobModel.subject_type == "channel",
            PipelineJobModel.subject_id == channel_id,
        ),
        PipelineJobModel.input_json["channelId"].as_integer() == channel_id,
        exists(
            select(PipelineJobAttemptModel.id).where(
                PipelineJobAttemptModel.job_id == PipelineJobModel.id,
                PipelineJobAttemptModel.output_json["channelId"].as_integer() == channel_id,
            )
        ),
        exists(
            select(ChannelModel.id).where(
                ChannelModel.source_job_id == PipelineJobModel.id,
                ChannelModel.id == channel_id,
            )
        ),
        exists(
            select(VideoModel.id).where(
                VideoModel.source_job_id == PipelineJobModel.id,
                VideoModel.channel_id == channel_id,
            )
        ),
        exists(
            select(VideoTaskModel.id)
            .join(VideoModel, VideoTaskModel.video_id == VideoModel.id)
            .where(
                VideoTaskModel.job_id == PipelineJobModel.id,
                VideoModel.channel_id == channel_id,
            )
        ),
    )


def _output_video_ids(output_json: JsonObject) -> list[int]:
    value = output_json.get("createdVideoIds")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int)]


def _job_record(model: PipelineJobModel) -> PipelineJobRecord:
    return PipelineJobRecord(
        id=model.id,
        step=model.step,
        status=_job_status(model.status),
        subject_type=model.subject_type,
        subject_id=model.subject_id,
        external_key=model.external_key,
        input_json=model.input_json,
        input_hash=model.input_hash,
        parent_job_id=model.parent_job_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def _attempt_record(model: PipelineJobAttemptModel) -> PipelineJobAttemptRecord:
    return PipelineJobAttemptRecord(
        id=model.id,
        job_id=model.job_id,
        attempt_no=model.attempt_no,
        status=_attempt_status(model.status),
        started_at=model.started_at,
        finished_at=model.finished_at,
        worker_id=model.worker_id,
        error_type=model.error_type,
        error_message=model.error_message,
        output_json=model.output_json,
    )
