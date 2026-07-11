from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
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

from codex_sdk_cli.domains.videos.exceptions import VideoAlreadyExists, VideoPersistenceError
from codex_sdk_cli.domains.videos.ports import VideoCreate, VideoRecord, VideoRepositoryPort
from codex_sdk_cli.infra.database.base import Base


class VideoModel(Base):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("youtube_video_id", name="uq_videos_youtube_video_id"),
        Index("ix_videos_channel_published", "channel_id", "published_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    youtube_video_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
    )
    duration: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_embeddable: Mapped[bool | None] = mapped_column(Boolean, index=True, nullable=True)
    embed_status_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_listing_api_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_api_calls.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    source_details_api_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_api_calls.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    source_embed_status_api_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_api_calls.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    source_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    source_work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"),
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


class SqlAlchemyVideoRepository(VideoRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get_video(self, video_id: int) -> VideoRecord | None:
        try:
            row = await self._session.get(VideoModel, video_id)
            return _video_record(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise VideoPersistenceError("Video persistence failed.") from exc

    @override
    async def get_video_by_youtube_video_id(
        self,
        youtube_video_id: str,
    ) -> VideoRecord | None:
        try:
            row = await self._session.scalar(
                select(VideoModel).where(VideoModel.youtube_video_id == youtube_video_id)
            )
            return _video_record(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise VideoPersistenceError("Video persistence failed.") from exc

    @override
    async def list_all_videos(self) -> list[VideoRecord]:
        try:
            rows = await self._session.scalars(
                select(VideoModel).order_by(
                    VideoModel.published_at.desc(),
                    VideoModel.id.desc(),
                )
            )
            return [_video_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise VideoPersistenceError("Video persistence failed.") from exc

    @override
    async def list_videos(self, *, channel_id: int) -> list[VideoRecord]:
        try:
            rows = await self._session.scalars(
                select(VideoModel)
                .where(VideoModel.channel_id == channel_id)
                .order_by(VideoModel.published_at.desc(), VideoModel.id.desc())
            )
            return [_video_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise VideoPersistenceError("Video persistence failed.") from exc

    @override
    async def list_videos_for_embed_status_refresh(
        self,
        *,
        video_ids: tuple[int, ...] | None,
        limit: int,
    ) -> list[VideoRecord]:
        try:
            statement = select(VideoModel).order_by(
                VideoModel.embed_status_checked_at.asc().nullsfirst(),
                VideoModel.published_at.desc(),
                VideoModel.id.desc(),
            )
            if video_ids is not None:
                if not video_ids:
                    return []
                statement = statement.where(VideoModel.id.in_(video_ids))
            rows = await self._session.scalars(statement.limit(limit))
            return [_video_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise VideoPersistenceError("Video persistence failed.") from exc

    @override
    async def find_existing_youtube_video_id(
        self,
        *,
        channel_id: int,
        youtube_video_ids: tuple[str, ...],
    ) -> str | None:
        if not youtube_video_ids:
            return None
        try:
            rows = await self._session.scalars(
                select(VideoModel.youtube_video_id).where(
                    VideoModel.channel_id == channel_id,
                    VideoModel.youtube_video_id.in_(youtube_video_ids),
                )
            )
            existing = set(rows.all())
        except SQLAlchemyError as exc:
            raise VideoPersistenceError("Video persistence failed.") from exc
        return next(
            (
                youtube_video_id
                for youtube_video_id in youtube_video_ids
                if youtube_video_id in existing
            ),
            None,
        )

    @override
    async def create_videos(self, videos: list[VideoCreate]) -> list[VideoRecord]:
        if not videos:
            return []
        try:
            models = [
                VideoModel(
                    channel_id=video.channel_id,
                    youtube_video_id=video.youtube_video_id,
                    title=video.title,
                    description=video.description,
                    published_at=video.published_at,
                    duration=video.duration,
                    is_embeddable=video.is_embeddable,
                    embed_status_checked_at=video.embed_status_checked_at,
                    thumbnail_url=video.thumbnail_url,
                    source_listing_api_call_id=video.source_listing_api_call_id,
                    source_details_api_call_id=video.source_details_api_call_id,
                    source_embed_status_api_call_id=(video.source_embed_status_api_call_id),
                    source_job_id=video.source_job_id,
                )
                for video in videos
            ]
            self._session.add_all(models)
            await self._session.commit()
            for model in models:
                await self._session.refresh(model)
            return [_video_record(model) for model in models]
        except IntegrityError as exc:
            await self._session.rollback()
            raise VideoAlreadyExists("YouTube video already exists.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise VideoPersistenceError("Video persistence failed.") from exc

    @override
    async def update_embed_status(
        self,
        video_id: int,
        *,
        is_embeddable: bool | None,
        checked_at: datetime,
        source_api_call_id: int | None,
    ) -> VideoRecord:
        try:
            model = await self._session.get(VideoModel, video_id)
            if model is None:
                raise VideoPersistenceError("Video not found.")
            model.is_embeddable = is_embeddable
            model.embed_status_checked_at = checked_at
            model.source_embed_status_api_call_id = source_api_call_id
            await self._session.commit()
            await self._session.refresh(model)
            return _video_record(model)
        except VideoPersistenceError:
            await self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise VideoPersistenceError("Video persistence failed.") from exc


def _video_record(model: VideoModel) -> VideoRecord:
    return VideoRecord(
        id=model.id,
        channel_id=model.channel_id,
        youtube_video_id=model.youtube_video_id,
        title=model.title,
        description=model.description,
        published_at=model.published_at,
        duration=model.duration,
        is_embeddable=model.is_embeddable,
        embed_status_checked_at=model.embed_status_checked_at,
        thumbnail_url=model.thumbnail_url,
        source_listing_api_call_id=model.source_listing_api_call_id,
        source_details_api_call_id=model.source_details_api_call_id,
        source_embed_status_api_call_id=model.source_embed_status_api_call_id,
        source_job_id=model.source_job_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
