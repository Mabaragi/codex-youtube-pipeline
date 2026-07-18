from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select
from typing_extensions import override

from codex_sdk_cli.domains.streamers.exceptions import (
    StreamerHasChannels,
    StreamerPersistenceError,
)
from codex_sdk_cli.domains.streamers.ports import StreamerRecord, StreamerRepositoryPort
from codex_sdk_cli.infra.database.base import Base


class StreamerModel(Base):
    __tablename__ = "streamers"
    __table_args__ = (Index("ix_streamers_publish_profile_id", "publish_profile_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    publish_profile_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )


class SqlAlchemyStreamerRepository(StreamerRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_streamer(
        self,
        *,
        name: str,
        publish_profile_id: int,
    ) -> StreamerRecord:
        try:
            model = StreamerModel(name=name, publish_profile_id=publish_profile_id)
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _streamer_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

    @override
    async def list_streamers(self) -> list[StreamerRecord]:
        try:
            rows = await self._session.scalars(select(StreamerModel).order_by(StreamerModel.id))
            return [_streamer_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

    @override
    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        try:
            model = await self._session.get(StreamerModel, streamer_id)
        except SQLAlchemyError as exc:
            raise StreamerPersistenceError("Streamer persistence failed.") from exc
        if model is None:
            return None
        return _streamer_record(model)

    @override
    async def update_streamer(
        self,
        streamer_id: int,
        *,
        name: str | None = None,
        publish_profile_id: int | None = None,
    ) -> StreamerRecord | None:
        try:
            model = await self._session.get(StreamerModel, streamer_id)
            if model is None:
                return None
            if name is not None:
                model.name = name
            if publish_profile_id is not None:
                model.publish_profile_id = publish_profile_id
            await self._session.commit()
            await self._session.refresh(model)
            return _streamer_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

    @override
    async def is_publish_profile_active(self, publish_profile_id: int) -> bool:
        from codex_sdk_cli.infra.publication_config.repository import (
            PublishProfileModel,
            PublishProfileRevisionModel,
        )

        try:
            profile_id = await self._session.scalar(
                select(PublishProfileModel.id)
                .join(
                    PublishProfileRevisionModel,
                    PublishProfileRevisionModel.id == PublishProfileModel.active_revision_id,
                )
                .where(
                    PublishProfileModel.id == publish_profile_id,
                    PublishProfileRevisionModel.state == "active",
                )
                .limit(1)
            )
            return profile_id is not None
        except SQLAlchemyError as exc:
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

    @override
    async def has_archive_artifacts(self, streamer_id: int) -> bool:
        from codex_sdk_cli.infra.archive_publish.repository import (
            ArchiveVideoArtifactModel,
        )
        from codex_sdk_cli.infra.channels.repository import ChannelModel
        from codex_sdk_cli.infra.videos.repository import VideoModel

        try:
            artifact_id = await self._session.scalar(
                select(ArchiveVideoArtifactModel.id)
                .join(VideoModel, VideoModel.id == ArchiveVideoArtifactModel.video_id)
                .join(ChannelModel, ChannelModel.id == VideoModel.channel_id)
                .where(ChannelModel.streamer_id == streamer_id)
                .limit(1)
            )
            return artifact_id is not None
        except SQLAlchemyError as exc:
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

    @override
    async def delete_streamer(self, streamer_id: int) -> bool:
        try:
            from codex_sdk_cli.infra.channels.repository import ChannelModel

            model = await self._session.get(StreamerModel, streamer_id)
            if model is None:
                return False
            channel_id = await self._session.scalar(
                select(ChannelModel.id).where(ChannelModel.streamer_id == streamer_id).limit(1)
            )
            if channel_id is not None:
                await self._session.rollback()
                raise StreamerHasChannels("Streamer has channels and cannot be deleted.")
            await self._session.delete(model)
            await self._session.commit()
            return True
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise StreamerPersistenceError("Streamer persistence failed.") from exc


def _streamer_record(model: StreamerModel) -> StreamerRecord:
    return StreamerRecord(
        id=model.id,
        name=model.name,
        publish_profile_id=model.publish_profile_id,
    )
