from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    or_,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.selectable import Subquery
from typing_extensions import override

from codex_sdk_cli.domains.archive_publish.constants import ARCHIVE_PUBLISH_TASK_NAME
from codex_sdk_cli.domains.archive_publish.exceptions import (
    ArchivePublishPersistenceError,
)
from codex_sdk_cli.domains.archive_publish.ports import (
    ArchiveChannelRecord,
    ArchiveIndexPublicationCreate,
    ArchiveIndexPublicationRecord,
    ArchiveOpsVideoListResult,
    ArchiveOpsVideoQuery,
    ArchiveOpsVideoRecord,
    ArchivePublishCandidateQuery,
    ArchivePublishCandidateRecord,
    ArchivePublishRepositoryPort,
    ArchiveStreamerRecord,
    ArchiveVideoArtifactCreate,
    ArchiveVideoArtifactRecord,
    ArchiveVideoArtifactWithVideoRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord, VideoTaskStatus
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.timelines.repository import (
    SqlAlchemyTimelineCompositionRepository,
    TimelineCompositionModel,
    TimelineEpisodeModel,
)
from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel
from codex_sdk_cli.infra.videos.repository import VideoModel


class ArchiveVideoArtifactModel(Base):
    __tablename__ = "archive_video_artifacts"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="archive_video_artifacts_schema_min"),
        CheckConstraint("byte_size >= 1", name="archive_video_artifacts_byte_size_min"),
        CheckConstraint("block_count >= 0", name="archive_video_artifacts_block_count_min"),
        CheckConstraint("episode_count >= 0", name="archive_video_artifacts_episode_count_min"),
        CheckConstraint(
            "topic_cluster_count >= 0",
            name="archive_video_artifacts_topic_cluster_count_min",
        ),
        CheckConstraint(
            "review_flag_count >= 0",
            name="archive_video_artifacts_review_flag_count_min",
        ),
        CheckConstraint(
            "micro_event_count >= 0",
            name="archive_video_artifacts_micro_event_count_min",
        ),
        Index(
            "ix_archive_video_artifacts_video_env_variant",
            "video_id",
            "environment",
            "variant",
            "created_at",
        ),
        Index(
            "ix_archive_video_artifacts_source_timeline_task",
            "source_timeline_task_id",
        ),
        Index("ix_archive_video_artifacts_publish_task", "publish_task_id"),
        Index("ix_archive_video_artifacts_publish_job", "publish_job_id"),
        Index(
            "ix_archive_video_artifacts_environment_version",
            "environment",
            "schema_version",
            "version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_timeline_composition_id: Mapped[int] = mapped_column(
        ForeignKey("timeline_compositions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_timeline_task_id: Mapped[int] = mapped_column(
        ForeignKey("video_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_micro_event_task_id: Mapped[int] = mapped_column(
        ForeignKey("video_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    publish_task_id: Mapped[int] = mapped_column(
        ForeignKey("video_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    publish_job_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    public_url: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    block_count: Mapped[int] = mapped_column(Integer, nullable=False)
    episode_count: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_cluster_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_flag_count: Mapped[int] = mapped_column(Integer, nullable=False)
    micro_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
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


class ArchiveIndexPublicationModel(Base):
    __tablename__ = "archive_index_publications"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="archive_index_schema_min"),
        CheckConstraint("byte_size >= 1", name="archive_index_byte_size_min"),
        CheckConstraint("video_count >= 0", name="archive_index_video_count_min"),
        Index(
            "ix_archive_index_publications_environment_created",
            "environment",
            "created_at",
            "id",
        ),
        Index(
            "ix_archive_index_publications_environment_version",
            "environment",
            "schema_version",
            "version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    pointer_key: Mapped[str] = mapped_column(Text, nullable=False)
    index_key: Mapped[str] = mapped_column(Text, nullable=False)
    public_url: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    video_count: Mapped[int] = mapped_column(Integer, nullable=False)
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


class SqlAlchemyArchivePublishRepository(ArchivePublishRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._timelines = SqlAlchemyTimelineCompositionRepository(session)

    @override
    async def get_publish_candidate(
        self,
        *,
        video_id: int,
        environment: str,
        variant: str,
        schema_version: int,
    ) -> ArchivePublishCandidateRecord | None:
        try:
            row = (
                await self._session.execute(
                    select(VideoModel, ChannelModel, StreamerModel)
                    .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
                    .join(StreamerModel, ChannelModel.streamer_id == StreamerModel.id)
                    .where(VideoModel.id == video_id)
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            video, channel, streamer = row
            composition = await self._timelines.get_latest_succeeded_composition(video_id=video_id)
            latest_task = await self._latest_archive_task(video_id)
            latest_artifact = await self._latest_artifact_for_video(
                video_id=video_id,
                environment=environment,
                variant=variant,
                schema_version=schema_version,
            )
            return ArchivePublishCandidateRecord(
                video=_video_record(video),
                channel=_channel_record(channel),
                streamer=_streamer_record(streamer),
                composition=composition,
                latest_archive_task=latest_task,
                latest_artifact=latest_artifact,
            )
        except SQLAlchemyError as exc:
            raise ArchivePublishPersistenceError("Archive publish persistence failed.") from exc

    @override
    async def list_publish_candidates(
        self,
        query: ArchivePublishCandidateQuery,
    ) -> list[ArchivePublishCandidateRecord]:
        latest_timeline = _latest_timeline_subquery()
        statement = (
            select(VideoModel.id)
            .join(latest_timeline, latest_timeline.c.video_id == VideoModel.id)
            .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
            .limit(query.limit)
        )
        if query.channel_id is not None:
            statement = statement.where(VideoModel.channel_id == query.channel_id)
        if query.search:
            term = f"%{query.search}%"
            statement = statement.where(
                or_(
                    VideoModel.title.ilike(term),
                    VideoModel.youtube_video_id.ilike(term),
                )
            )
        try:
            video_ids = list((await self._session.scalars(statement)).all())
            candidates: list[ArchivePublishCandidateRecord] = []
            for video_id in video_ids:
                candidate = await self.get_publish_candidate(
                    video_id=video_id,
                    environment=query.environment,
                    variant=query.variant,
                    schema_version=query.schema_version,
                )
                if candidate is not None:
                    candidates.append(candidate)
            return candidates
        except SQLAlchemyError as exc:
            raise ArchivePublishPersistenceError("Archive publish persistence failed.") from exc

    @override
    async def get_artifact_for_source(
        self,
        *,
        video_id: int,
        environment: str,
        variant: str,
        schema_version: int,
        source_timeline_task_id: int,
    ) -> ArchiveVideoArtifactRecord | None:
        try:
            model = await self._session.scalar(
                select(ArchiveVideoArtifactModel)
                .where(
                    ArchiveVideoArtifactModel.video_id == video_id,
                    ArchiveVideoArtifactModel.environment == environment,
                    ArchiveVideoArtifactModel.variant == variant,
                    ArchiveVideoArtifactModel.schema_version == schema_version,
                    ArchiveVideoArtifactModel.source_timeline_task_id == source_timeline_task_id,
                )
                .order_by(ArchiveVideoArtifactModel.id.desc())
                .limit(1)
            )
            return _artifact_record(model) if model is not None else None
        except SQLAlchemyError as exc:
            raise ArchivePublishPersistenceError("Archive publish persistence failed.") from exc

    @override
    async def create_video_artifact(
        self,
        create: ArchiveVideoArtifactCreate,
    ) -> ArchiveVideoArtifactRecord:
        try:
            model = ArchiveVideoArtifactModel(
                video_id=create.video_id,
                source_timeline_composition_id=create.source_timeline_composition_id,
                source_timeline_task_id=create.source_timeline_task_id,
                source_micro_event_task_id=create.source_micro_event_task_id,
                publish_task_id=create.publish_task_id,
                publish_job_id=create.publish_job_id,
                environment=create.environment,
                variant=create.variant,
                schema_version=create.schema_version,
                version=create.version,
                object_key=create.object_key,
                public_url=create.public_url,
                sha256=create.sha256,
                byte_size=create.byte_size,
                block_count=create.block_count,
                episode_count=create.episode_count,
                topic_cluster_count=create.topic_cluster_count,
                review_flag_count=create.review_flag_count,
                micro_event_count=create.micro_event_count,
            )
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _artifact_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise ArchivePublishPersistenceError("Archive publish persistence failed.") from exc

    @override
    async def list_latest_video_artifacts(
        self,
        *,
        environment: str,
        schema_version: int,
    ) -> list[ArchiveVideoArtifactWithVideoRecord]:
        latest_artifact = _latest_artifact_subquery(
            environment=environment,
            schema_version=schema_version,
        )
        statement = (
            select(ArchiveVideoArtifactModel, VideoModel, ChannelModel, StreamerModel)
            .join(latest_artifact, latest_artifact.c.artifact_id == ArchiveVideoArtifactModel.id)
            .join(VideoModel, ArchiveVideoArtifactModel.video_id == VideoModel.id)
            .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
            .join(StreamerModel, ChannelModel.streamer_id == StreamerModel.id)
            .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
        )
        try:
            rows = (await self._session.execute(statement)).all()
            return [
                ArchiveVideoArtifactWithVideoRecord(
                    artifact=_artifact_record(artifact),
                    video=_video_record(video),
                    channel=_channel_record(channel),
                    streamer=_streamer_record(streamer),
                )
                for artifact, video, channel, streamer in rows
            ]
        except SQLAlchemyError as exc:
            raise ArchivePublishPersistenceError("Archive publish persistence failed.") from exc

    @override
    async def create_index_publication(
        self,
        create: ArchiveIndexPublicationCreate,
    ) -> ArchiveIndexPublicationRecord:
        try:
            model = ArchiveIndexPublicationModel(
                environment=create.environment,
                schema_version=create.schema_version,
                version=create.version,
                pointer_key=create.pointer_key,
                index_key=create.index_key,
                public_url=create.public_url,
                sha256=create.sha256,
                byte_size=create.byte_size,
                video_count=create.video_count,
            )
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _index_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise ArchivePublishPersistenceError("Archive publish persistence failed.") from exc

    @override
    async def get_latest_index_publication(
        self,
        *,
        environment: str,
    ) -> ArchiveIndexPublicationRecord | None:
        try:
            model = await self._session.scalar(
                select(ArchiveIndexPublicationModel)
                .where(ArchiveIndexPublicationModel.environment == environment)
                .order_by(ArchiveIndexPublicationModel.id.desc())
                .limit(1)
            )
            return _index_record(model) if model is not None else None
        except SQLAlchemyError as exc:
            raise ArchivePublishPersistenceError("Archive publish persistence failed.") from exc

    @override
    async def list_ops_videos(
        self,
        query: ArchiveOpsVideoQuery,
    ) -> ArchiveOpsVideoListResult:
        latest_timeline = _latest_timeline_subquery()
        latest_artifact = _latest_artifact_per_video_subquery(
            environment=query.environment,
            schema_version=1,
        )
        latest_archive_task = _latest_archive_task_subquery()
        base = (
            select(
                VideoModel,
                ChannelModel.name,
                TimelineCompositionModel.id,
                TimelineCompositionModel.video_task_id,
                func.count().over().label("total"),
            )
            .join(ChannelModel, VideoModel.channel_id == ChannelModel.id)
            .outerjoin(latest_timeline, latest_timeline.c.video_id == VideoModel.id)
            .outerjoin(
                TimelineCompositionModel,
                TimelineCompositionModel.id == latest_timeline.c.composition_id,
            )
            .outerjoin(latest_artifact, latest_artifact.c.video_id == VideoModel.id)
            .outerjoin(latest_archive_task, latest_archive_task.c.video_id == VideoModel.id)
            .outerjoin(
                ArchiveVideoArtifactModel,
                ArchiveVideoArtifactModel.id == latest_artifact.c.artifact_id,
            )
            .outerjoin(VideoTaskModel, VideoTaskModel.id == latest_archive_task.c.task_id)
            .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
            .limit(query.limit)
            .offset(query.offset)
        )
        if query.channel_id is not None:
            base = base.where(VideoModel.channel_id == query.channel_id)
        if query.search:
            term = f"%{query.search}%"
            base = base.where(
                or_(
                    VideoModel.title.ilike(term),
                    VideoModel.youtube_video_id.ilike(term),
                    ChannelModel.name.ilike(term),
                )
            )
        if query.publish_status == "not_ready":
            base = base.where(TimelineCompositionModel.id.is_(None))
        elif query.publish_status == "ready":
            base = base.where(
                TimelineCompositionModel.id.is_not(None),
                ArchiveVideoArtifactModel.id.is_(None),
                or_(
                    VideoTaskModel.id.is_(None),
                    VideoTaskModel.status.not_in(("pending", "running", "failed", "timed_out")),
                ),
            )
        elif query.publish_status == "pending":
            base = base.where(VideoTaskModel.status == "pending")
        elif query.publish_status == "running":
            base = base.where(VideoTaskModel.status == "running")
        elif query.publish_status == "failed":
            base = base.where(VideoTaskModel.status.in_(("failed", "timed_out")))
        elif query.publish_status == "published":
            base = base.where(ArchiveVideoArtifactModel.id.is_not(None))

        try:
            rows = (await self._session.execute(base)).all()
            items: list[ArchiveOpsVideoRecord] = []
            total = rows[0][4] if rows else 0
            for video, channel_name, composition_id, timeline_task_id, _total in rows:
                items.append(
                    ArchiveOpsVideoRecord(
                        video=_video_record(video),
                        channel_name=channel_name,
                        timeline_composition_id=composition_id,
                        timeline_task_id=timeline_task_id,
                        timeline_episode_count=await self._episode_count(composition_id),
                        latest_archive_task=await self._latest_archive_task(video.id),
                        latest_artifact=await self._latest_artifact_for_video(
                            video_id=video.id,
                            environment=query.environment,
                            variant=None,
                            schema_version=1,
                        ),
                    )
                )
            return ArchiveOpsVideoListResult(items=tuple(items), total=total)
        except SQLAlchemyError as exc:
            raise ArchivePublishPersistenceError("Archive publish persistence failed.") from exc

    async def _latest_archive_task(self, video_id: int) -> VideoTaskRecord | None:
        model = await self._session.scalar(
            select(VideoTaskModel)
            .where(
                VideoTaskModel.video_id == video_id,
                VideoTaskModel.task_name == ARCHIVE_PUBLISH_TASK_NAME,
            )
            .order_by(VideoTaskModel.id.desc())
            .limit(1)
        )
        return _task_record(model) if model is not None else None

    async def _latest_artifact_for_video(
        self,
        *,
        video_id: int,
        environment: str,
        variant: str | None,
        schema_version: int,
    ) -> ArchiveVideoArtifactRecord | None:
        statement = (
            select(ArchiveVideoArtifactModel)
            .where(
                ArchiveVideoArtifactModel.video_id == video_id,
                ArchiveVideoArtifactModel.environment == environment,
                ArchiveVideoArtifactModel.schema_version == schema_version,
            )
            .order_by(ArchiveVideoArtifactModel.id.desc())
            .limit(1)
        )
        if variant is not None:
            statement = statement.where(ArchiveVideoArtifactModel.variant == variant)
        model = await self._session.scalar(statement)
        return _artifact_record(model) if model is not None else None

    async def _episode_count(self, composition_id: int | None) -> int:
        if composition_id is None:
            return 0
        return (
            await self._session.scalar(
                select(func.count()).where(TimelineEpisodeModel.composition_id == composition_id)
            )
            or 0
        )


def _latest_timeline_subquery() -> Subquery:
    return (
        select(
            TimelineCompositionModel.video_id.label("video_id"),
            func.max(TimelineCompositionModel.id).label("composition_id"),
        )
        .join(VideoTaskModel, TimelineCompositionModel.video_task_id == VideoTaskModel.id)
        .where(VideoTaskModel.status == "succeeded")
        .group_by(TimelineCompositionModel.video_id)
        .subquery()
    )


def _latest_archive_task_subquery() -> Subquery:
    return (
        select(
            VideoTaskModel.video_id.label("video_id"),
            func.max(VideoTaskModel.id).label("task_id"),
        )
        .where(VideoTaskModel.task_name == ARCHIVE_PUBLISH_TASK_NAME)
        .group_by(VideoTaskModel.video_id)
        .subquery()
    )


def _latest_artifact_subquery(
    *,
    environment: str,
    schema_version: int,
) -> Subquery:
    return (
        select(
            ArchiveVideoArtifactModel.video_id.label("video_id"),
            ArchiveVideoArtifactModel.variant.label("variant"),
            func.max(ArchiveVideoArtifactModel.id).label("artifact_id"),
        )
        .where(
            ArchiveVideoArtifactModel.environment == environment,
            ArchiveVideoArtifactModel.schema_version == schema_version,
        )
        .group_by(ArchiveVideoArtifactModel.video_id, ArchiveVideoArtifactModel.variant)
        .subquery()
    )


def _latest_artifact_per_video_subquery(
    *,
    environment: str,
    schema_version: int,
) -> Subquery:
    return (
        select(
            ArchiveVideoArtifactModel.video_id.label("video_id"),
            func.max(ArchiveVideoArtifactModel.id).label("artifact_id"),
        )
        .where(
            ArchiveVideoArtifactModel.environment == environment,
            ArchiveVideoArtifactModel.schema_version == schema_version,
        )
        .group_by(ArchiveVideoArtifactModel.video_id)
        .subquery()
    )


def _artifact_record(model: ArchiveVideoArtifactModel) -> ArchiveVideoArtifactRecord:
    return ArchiveVideoArtifactRecord(
        id=model.id,
        video_id=model.video_id,
        source_timeline_composition_id=model.source_timeline_composition_id,
        source_timeline_task_id=model.source_timeline_task_id,
        source_micro_event_task_id=model.source_micro_event_task_id,
        publish_task_id=model.publish_task_id,
        publish_job_id=model.publish_job_id,
        environment=model.environment,
        variant=model.variant,
        schema_version=model.schema_version,
        version=model.version,
        object_key=model.object_key,
        public_url=model.public_url,
        sha256=model.sha256,
        byte_size=model.byte_size,
        block_count=model.block_count,
        episode_count=model.episode_count,
        topic_cluster_count=model.topic_cluster_count,
        review_flag_count=model.review_flag_count,
        micro_event_count=model.micro_event_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _index_record(model: ArchiveIndexPublicationModel) -> ArchiveIndexPublicationRecord:
    return ArchiveIndexPublicationRecord(
        id=model.id,
        environment=model.environment,
        schema_version=model.schema_version,
        version=model.version,
        pointer_key=model.pointer_key,
        index_key=model.index_key,
        public_url=model.public_url,
        sha256=model.sha256,
        byte_size=model.byte_size,
        video_count=model.video_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _video_record(model: VideoModel) -> VideoRecord:
    return VideoRecord(
        id=model.id,
        channel_id=model.channel_id,
        youtube_video_id=model.youtube_video_id,
        title=model.title,
        description=model.description,
        published_at=model.published_at,
        duration=model.duration,
        thumbnail_url=model.thumbnail_url,
        source_listing_api_call_id=model.source_listing_api_call_id,
        source_details_api_call_id=model.source_details_api_call_id,
        source_job_id=model.source_job_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _channel_record(model: ChannelModel) -> ArchiveChannelRecord:
    return ArchiveChannelRecord(
        id=model.id,
        name=model.name,
        handle=model.handle,
        youtube_channel_id=model.youtube_channel_id,
    )


def _streamer_record(model: StreamerModel) -> ArchiveStreamerRecord:
    return ArchiveStreamerRecord(id=model.id, name=model.name)


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
        input_json=model.input_json,
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
    allowed: set[VideoTaskStatus] = {
        "pending",
        "running",
        "succeeded",
        "failed",
        "timed_out",
        "no_transcript",
        "skipped",
        "canceled",
    }
    return cast(VideoTaskStatus, value) if value in allowed else "running"
