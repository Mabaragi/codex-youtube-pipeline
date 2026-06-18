from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select
from typing_extensions import override

from codex_sdk_cli.domains.channels.exceptions import (
    ChannelAlreadyExists,
    ChannelPersistenceError,
)
from codex_sdk_cli.domains.channels.ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelRepositoryPort,
    ChannelUpdate,
)
from codex_sdk_cli.infra.database.base import Base


class ChannelModel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("youtube_channel_id", name="uq_channels_youtube_channel_id"),
        UniqueConstraint("uploads_playlist_id", name="uq_channels_uploads_playlist_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    streamer_id: Mapped[int] = mapped_column(
        ForeignKey("streamers.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_api_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_api_calls.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    source_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )


class SqlAlchemyChannelRepository(ChannelRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        try:
            model = ChannelModel(
                streamer_id=channel.streamer_id,
                handle=channel.handle,
                name=channel.name,
                youtube_channel_id=channel.youtube_channel_id,
                uploads_playlist_id=channel.uploads_playlist_id,
                source_api_call_id=channel.source_api_call_id,
                source_job_id=channel.source_job_id,
            )
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _channel_record(model)
        except IntegrityError as exc:
            await self._session.rollback()
            raise ChannelAlreadyExists("YouTube channel already exists.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise ChannelPersistenceError("Channel persistence failed.") from exc

    @override
    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        try:
            statement = select(ChannelModel).order_by(ChannelModel.id)
            if streamer_id is not None:
                statement = statement.where(ChannelModel.streamer_id == streamer_id)
            rows = await self._session.scalars(statement)
            return [_channel_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise ChannelPersistenceError("Channel persistence failed.") from exc

    @override
    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        try:
            model = await self._session.get(ChannelModel, channel_id)
        except SQLAlchemyError as exc:
            raise ChannelPersistenceError("Channel persistence failed.") from exc
        if model is None:
            return None
        return _channel_record(model)

    @override
    async def get_channel_by_youtube_channel_id(
        self,
        youtube_channel_id: str,
    ) -> ChannelRecord | None:
        try:
            model = await self._session.scalar(
                select(ChannelModel).where(
                    ChannelModel.youtube_channel_id == youtube_channel_id
                )
            )
        except SQLAlchemyError as exc:
            raise ChannelPersistenceError("Channel persistence failed.") from exc
        if model is None:
            return None
        return _channel_record(model)

    @override
    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        try:
            model = await self._session.get(ChannelModel, channel_id)
            if model is None:
                return None
            if update.handle is not None:
                model.handle = update.handle
            if update.name is not None:
                model.name = update.name
            if update.youtube_channel_id_set:
                model.youtube_channel_id = update.youtube_channel_id
            await self._session.commit()
            await self._session.refresh(model)
            return _channel_record(model)
        except IntegrityError as exc:
            await self._session.rollback()
            raise ChannelAlreadyExists("YouTube channel already exists.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise ChannelPersistenceError("Channel persistence failed.") from exc

    @override
    async def update_uploads_playlist_id(
        self,
        channel_id: int,
        uploads_playlist_id: str,
    ) -> ChannelRecord | None:
        try:
            model = await self._session.get(ChannelModel, channel_id)
            if model is None:
                return None
            model.uploads_playlist_id = uploads_playlist_id
            await self._session.commit()
            await self._session.refresh(model)
            return _channel_record(model)
        except IntegrityError as exc:
            await self._session.rollback()
            raise ChannelAlreadyExists("Uploads playlist already exists.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise ChannelPersistenceError("Channel persistence failed.") from exc

    @override
    async def delete_channel(self, channel_id: int) -> bool:
        try:
            model = await self._session.get(ChannelModel, channel_id)
            if model is None:
                return False
            await self._session.delete(model)
            await self._session.commit()
            return True
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise ChannelPersistenceError("Channel persistence failed.") from exc


def _channel_record(model: ChannelModel) -> ChannelRecord:
    return ChannelRecord(
        id=model.id,
        streamer_id=model.streamer_id,
        handle=model.handle,
        name=model.name,
        youtube_channel_id=model.youtube_channel_id,
        uploads_playlist_id=model.uploads_playlist_id,
        source_api_call_id=model.source_api_call_id,
        source_job_id=model.source_job_id,
    )
