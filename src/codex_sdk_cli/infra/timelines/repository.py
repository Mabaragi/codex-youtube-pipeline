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
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import override

from codex_sdk_cli.domains.timelines.exceptions import (
    TimelineCompositionPersistenceError,
)
from codex_sdk_cli.domains.timelines.ports import (
    CopyStyle,
    JsonObject,
    TimelineBlockCreate,
    TimelineBlockRecord,
    TimelineBlockType,
    TimelineCompositionCreate,
    TimelineCompositionRecord,
    TimelineCompositionRepositoryPort,
    TimelineContentKind,
    TimelineEpisodeCreate,
    TimelineEpisodeRecord,
    TimelineReviewFlagCreate,
    TimelineReviewFlagRecord,
    TimelineReviewFlagType,
    TimelineTopicClusterCreate,
    TimelineTopicClusterRecord,
    TimelineViewerTag,
    TimelineVisibility,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskStatus
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel
from codex_sdk_cli.infra.videos.repository import VideoModel


class TimelineCompositionModel(Base):
    __tablename__ = "timeline_compositions"
    __table_args__ = (
        UniqueConstraint("video_task_id", name="uq_timeline_compositions_video_task"),
        Index("ix_timeline_compositions_video_id", "video_id"),
        Index("ix_timeline_compositions_source_micro_event_task", "source_micro_event_task_id"),
        Index("ix_timeline_compositions_source_job", "source_job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_task_id: Mapped[int] = mapped_column(
        ForeignKey("video_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_micro_event_task_id: Mapped[int] = mapped_column(
        ForeignKey("video_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_micro_event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    copy_style: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    display_title: Mapped[str] = mapped_column(Text, nullable=False)
    display_summary: Mapped[str] = mapped_column(Text, nullable=False)
    main_topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    output_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    validation_warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_job_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_job_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    codex_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    codex_turn_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class TimelineBlockModel(Base):
    __tablename__ = "timeline_blocks"
    __table_args__ = (
        UniqueConstraint("composition_id", "block_id", name="uq_timeline_blocks_key"),
        CheckConstraint("block_index >= 1", name="timeline_blocks_index_min"),
        Index("ix_timeline_blocks_composition", "composition_id", "block_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("timeline_compositions.id", ondelete="CASCADE"),
        nullable=False,
    )
    block_id: Mapped[str] = mapped_column(String(64), nullable=False)
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    display_title: Mapped[str] = mapped_column(Text, nullable=False)
    display_summary: Mapped[str] = mapped_column(Text, nullable=False)
    episode_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
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


class TimelineEpisodeModel(Base):
    __tablename__ = "timeline_episodes"
    __table_args__ = (
        UniqueConstraint("composition_id", "episode_id", name="uq_timeline_episodes_key"),
        CheckConstraint("episode_index >= 1", name="timeline_episodes_index_min"),
        Index("ix_timeline_episodes_composition", "composition_id", "episode_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("timeline_compositions.id", ondelete="CASCADE"),
        nullable=False,
    )
    episode_id: Mapped[str] = mapped_column(String(64), nullable=False)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_block_id: Mapped[str] = mapped_column(String(64), nullable=False)
    start_micro_event_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("micro_event_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    end_micro_event_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("micro_event_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    program_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_content_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    display_title: Mapped[str] = mapped_column(Text, nullable=False)
    display_summary: Mapped[str] = mapped_column(Text, nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    viewer_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    highlight_micro_event_candidate_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
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


class TimelineTopicClusterModel(Base):
    __tablename__ = "timeline_topic_clusters"
    __table_args__ = (
        UniqueConstraint("composition_id", "topic_id", name="uq_timeline_topics_key"),
        CheckConstraint("topic_index >= 1", name="timeline_topics_index_min"),
        Index("ix_timeline_topics_composition", "composition_id", "topic_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("timeline_compositions.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topic_index: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    display_label: Mapped[str] = mapped_column(Text, nullable=False)
    episode_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
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


class TimelineReviewFlagModel(Base):
    __tablename__ = "timeline_review_flags"
    __table_args__ = (
        CheckConstraint("flag_index >= 1", name="timeline_review_flags_index_min"),
        Index("ix_timeline_review_flags_composition", "composition_id", "flag_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("timeline_compositions.id", ondelete="CASCADE"),
        nullable=False,
    )
    flag_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_micro_event_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("micro_event_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    end_micro_event_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("micro_event_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
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


class SqlAlchemyTimelineCompositionRepository(TimelineCompositionRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def delete_composition(self, video_task_id: int) -> None:
        try:
            await self._session.execute(
                delete(TimelineCompositionModel).where(
                    TimelineCompositionModel.video_task_id == video_task_id
                )
            )
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise TimelineCompositionPersistenceError(
                "Timeline composition persistence failed."
            ) from exc

    @override
    async def replace_composition(
        self,
        create: TimelineCompositionCreate,
    ) -> TimelineCompositionRecord | None:
        try:
            model = await self._session.scalar(
                select(TimelineCompositionModel).where(
                    TimelineCompositionModel.video_task_id == create.video_task_id
                )
            )
            if model is None:
                model = TimelineCompositionModel(video_task_id=create.video_task_id)
            else:
                await self._delete_composition_children(model.id)
            _update_composition_model(model, create)
            self._session.add(model)
            await self._session.flush()
            self._session.add_all(_block_model(model.id, item) for item in create.blocks)
            self._session.add_all(_episode_model(model.id, item) for item in create.episodes)
            self._session.add_all(
                _topic_cluster_model(model.id, item) for item in create.topic_clusters
            )
            self._session.add_all(
                _review_flag_model(model.id, item) for item in create.review_flags
            )
            await self._session.commit()
            return await self.get_composition(
                video_id=create.video_id,
                video_task_id=create.video_task_id,
            )
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise TimelineCompositionPersistenceError(
                "Timeline composition persistence failed."
            ) from exc

    async def _delete_composition_children(self, composition_id: int) -> None:
        await self._session.execute(
            delete(TimelineReviewFlagModel).where(
                TimelineReviewFlagModel.composition_id == composition_id
            )
        )
        await self._session.execute(
            delete(TimelineTopicClusterModel).where(
                TimelineTopicClusterModel.composition_id == composition_id
            )
        )
        await self._session.execute(
            delete(TimelineEpisodeModel).where(
                TimelineEpisodeModel.composition_id == composition_id
            )
        )
        await self._session.execute(
            delete(TimelineBlockModel).where(
                TimelineBlockModel.composition_id == composition_id
            )
        )

    @override
    async def get_composition(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> TimelineCompositionRecord | None:
        try:
            model = await self._session.scalar(
                select(TimelineCompositionModel).where(
                    TimelineCompositionModel.video_id == video_id,
                    TimelineCompositionModel.video_task_id == video_task_id,
                )
            )
            if model is None:
                return None
            return await self._composition_record(model)
        except SQLAlchemyError as exc:
            raise TimelineCompositionPersistenceError(
                "Timeline composition persistence failed."
            ) from exc

    @override
    async def get_latest_succeeded_composition(
        self,
        *,
        video_id: int,
    ) -> TimelineCompositionRecord | None:
        try:
            model = await self._session.scalar(
                select(TimelineCompositionModel)
                .join(VideoTaskModel, TimelineCompositionModel.video_task_id == VideoTaskModel.id)
                .where(
                    TimelineCompositionModel.video_id == video_id,
                    VideoTaskModel.status == "succeeded",
                )
                .order_by(TimelineCompositionModel.id.desc())
                .limit(1)
            )
            if model is None:
                return None
            return await self._composition_record(model)
        except SQLAlchemyError as exc:
            raise TimelineCompositionPersistenceError(
                "Timeline composition persistence failed."
            ) from exc

    async def _composition_record(
        self,
        model: TimelineCompositionModel,
    ) -> TimelineCompositionRecord:
        video = await self._session.get(VideoModel, model.video_id)
        task = await self._session.get(VideoTaskModel, model.video_task_id)
        blocks = list(
            (
                await self._session.scalars(
                    select(TimelineBlockModel)
                    .where(TimelineBlockModel.composition_id == model.id)
                    .order_by(TimelineBlockModel.block_index)
                )
            ).all()
        )
        episodes = list(
            (
                await self._session.scalars(
                    select(TimelineEpisodeModel)
                    .where(TimelineEpisodeModel.composition_id == model.id)
                    .order_by(TimelineEpisodeModel.episode_index)
                )
            ).all()
        )
        topics = list(
            (
                await self._session.scalars(
                    select(TimelineTopicClusterModel)
                    .where(TimelineTopicClusterModel.composition_id == model.id)
                    .order_by(TimelineTopicClusterModel.topic_index)
                )
            ).all()
        )
        flags = list(
            (
                await self._session.scalars(
                    select(TimelineReviewFlagModel)
                    .where(TimelineReviewFlagModel.composition_id == model.id)
                    .order_by(TimelineReviewFlagModel.flag_index)
                )
            ).all()
        )
        return TimelineCompositionRecord(
            id=model.id,
            video_task_id=model.video_task_id,
            video_id=model.video_id,
            youtube_video_id=video.youtube_video_id if video is not None else "",
            source_micro_event_task_id=model.source_micro_event_task_id,
            source_micro_event_fingerprint=model.source_micro_event_fingerprint,
            copy_style=cast(CopyStyle, model.copy_style),
            status=cast(VideoTaskStatus, task.status if task is not None else "succeeded"),
            model=model.model,
            reasoning_effort=model.reasoning_effort,
            title=model.title,
            summary=model.summary,
            display_title=model.display_title,
            display_summary=model.display_summary,
            main_topics=model.main_topics,
            output_json=model.output_json,
            validation_warnings=model.validation_warnings,
            source_job_id=model.source_job_id,
            source_job_attempt_id=model.source_job_attempt_id,
            codex_thread_id=model.codex_thread_id,
            codex_turn_id=model.codex_turn_id,
            raw_response_text=model.raw_response_text,
            created_at=model.created_at,
            updated_at=model.updated_at,
            blocks=[_block_record(item) for item in blocks],
            episodes=[_episode_record(item) for item in episodes],
            topic_clusters=[_topic_cluster_record(item) for item in topics],
            review_flags=[_review_flag_record(item) for item in flags],
        )


def _block_model(composition_id: int, item: TimelineBlockCreate) -> TimelineBlockModel:
    return TimelineBlockModel(
        composition_id=composition_id,
        block_id=item.block_id,
        block_index=item.block_index,
        block_type=item.block_type,
        title=item.title,
        summary=item.summary,
        display_title=item.display_title,
        display_summary=item.display_summary,
        episode_ids=item.episode_ids,
    )


def _update_composition_model(
    model: TimelineCompositionModel,
    create: TimelineCompositionCreate,
) -> None:
    model.video_task_id = create.video_task_id
    model.video_id = create.video_id
    model.source_micro_event_task_id = create.source_micro_event_task_id
    model.source_micro_event_fingerprint = create.source_micro_event_fingerprint
    model.copy_style = create.copy_style
    model.model = create.model
    model.reasoning_effort = create.reasoning_effort
    model.title = create.title
    model.summary = create.summary
    model.display_title = create.display_title
    model.display_summary = create.display_summary
    model.main_topics = create.main_topics
    model.output_json = create.output_json
    model.validation_warnings = create.validation_warnings
    model.source_job_id = create.source_job_id
    model.source_job_attempt_id = create.source_job_attempt_id
    model.codex_thread_id = create.codex_thread_id
    model.codex_turn_id = create.codex_turn_id
    model.raw_response_text = create.raw_response_text


def _episode_model(composition_id: int, item: TimelineEpisodeCreate) -> TimelineEpisodeModel:
    return TimelineEpisodeModel(
        composition_id=composition_id,
        episode_id=item.episode_id,
        episode_index=item.episode_index,
        parent_block_id=item.parent_block_id,
        start_micro_event_candidate_id=item.start_micro_event_candidate_id,
        end_micro_event_candidate_id=item.end_micro_event_candidate_id,
        program_mode=item.program_mode,
        primary_content_kind=item.primary_content_kind,
        title=item.title,
        summary=item.summary,
        display_title=item.display_title,
        display_summary=item.display_summary,
        topics=item.topics,
        viewer_tags=item.viewer_tags,
        highlight_micro_event_candidate_ids=item.highlight_micro_event_candidate_ids,
        visibility=item.visibility,
    )


def _topic_cluster_model(
    composition_id: int,
    item: TimelineTopicClusterCreate,
) -> TimelineTopicClusterModel:
    return TimelineTopicClusterModel(
        composition_id=composition_id,
        topic_id=item.topic_id,
        topic_index=item.topic_index,
        label=item.label,
        summary=item.summary,
        display_label=item.display_label,
        episode_ids=item.episode_ids,
    )


def _review_flag_model(
    composition_id: int,
    item: TimelineReviewFlagCreate,
) -> TimelineReviewFlagModel:
    return TimelineReviewFlagModel(
        composition_id=composition_id,
        flag_index=item.flag_index,
        start_micro_event_candidate_id=item.start_micro_event_candidate_id,
        end_micro_event_candidate_id=item.end_micro_event_candidate_id,
        type=item.type,
        reason=item.reason,
    )


def _block_record(model: TimelineBlockModel) -> TimelineBlockRecord:
    return TimelineBlockRecord(
        id=model.id,
        composition_id=model.composition_id,
        block_id=model.block_id,
        block_index=model.block_index,
        block_type=cast(TimelineBlockType, model.block_type),
        title=model.title,
        summary=model.summary,
        display_title=model.display_title,
        display_summary=model.display_summary,
        episode_ids=model.episode_ids,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _episode_record(model: TimelineEpisodeModel) -> TimelineEpisodeRecord:
    return TimelineEpisodeRecord(
        id=model.id,
        composition_id=model.composition_id,
        episode_id=model.episode_id,
        episode_index=model.episode_index,
        parent_block_id=model.parent_block_id,
        start_micro_event_candidate_id=model.start_micro_event_candidate_id,
        end_micro_event_candidate_id=model.end_micro_event_candidate_id,
        program_mode=cast(TimelineBlockType, model.program_mode),
        primary_content_kind=cast(TimelineContentKind, model.primary_content_kind),
        title=model.title,
        summary=model.summary,
        display_title=model.display_title,
        display_summary=model.display_summary,
        topics=model.topics,
        viewer_tags=cast(list[TimelineViewerTag], model.viewer_tags),
        highlight_micro_event_candidate_ids=model.highlight_micro_event_candidate_ids,
        visibility=cast(TimelineVisibility, model.visibility),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _topic_cluster_record(model: TimelineTopicClusterModel) -> TimelineTopicClusterRecord:
    return TimelineTopicClusterRecord(
        id=model.id,
        composition_id=model.composition_id,
        topic_id=model.topic_id,
        topic_index=model.topic_index,
        label=model.label,
        summary=model.summary,
        display_label=model.display_label,
        episode_ids=model.episode_ids,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _review_flag_record(model: TimelineReviewFlagModel) -> TimelineReviewFlagRecord:
    return TimelineReviewFlagRecord(
        id=model.id,
        composition_id=model.composition_id,
        flag_index=model.flag_index,
        start_micro_event_candidate_id=model.start_micro_event_candidate_id,
        end_micro_event_candidate_id=model.end_micro_event_candidate_id,
        type=cast(TimelineReviewFlagType, model.type),
        reason=model.reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
