from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select
from typing_extensions import override

from codex_sdk_cli.domains.streamers.exceptions import (
    StreamerHasChannels,
    StreamerPersistenceError,
)
from codex_sdk_cli.domains.streamers.ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelUpdate,
    StreamerRecord,
    StreamerRepositoryPort,
)
from codex_sdk_cli.infra.database.base import Base


class StreamerModel(Base):
    __tablename__ = "streamers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class ChannelModel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    streamer_id: Mapped[int] = mapped_column(
        ForeignKey("streamers.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    handle: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SqlAlchemyStreamerRepository(StreamerRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_streamer(self, *, name: str) -> StreamerRecord:
        try:
            model = StreamerModel(name=name)
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
    async def update_streamer(self, streamer_id: int, *, name: str) -> StreamerRecord | None:
        try:
            model = await self._session.get(StreamerModel, streamer_id)
            if model is None:
                return None
            model.name = name
            await self._session.commit()
            await self._session.refresh(model)
            return _streamer_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

    @override
    async def delete_streamer(self, streamer_id: int) -> bool:
        try:
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

    @override
    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        try:
            model = ChannelModel(
                streamer_id=channel.streamer_id,
                handle=channel.handle,
                name=channel.name,
                youtube_channel_id=channel.youtube_channel_id,
            )
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _channel_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

    @override
    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        try:
            statement = select(ChannelModel).order_by(ChannelModel.id)
            if streamer_id is not None:
                statement = statement.where(ChannelModel.streamer_id == streamer_id)
            rows = await self._session.scalars(statement)
            return [_channel_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

    @override
    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        try:
            model = await self._session.get(ChannelModel, channel_id)
        except SQLAlchemyError as exc:
            raise StreamerPersistenceError("Streamer persistence failed.") from exc
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
            if update.streamer_id is not None:
                model.streamer_id = update.streamer_id
            if update.handle is not None:
                model.handle = update.handle
            if update.name is not None:
                model.name = update.name
            if update.youtube_channel_id_set:
                model.youtube_channel_id = update.youtube_channel_id
            await self._session.commit()
            await self._session.refresh(model)
            return _channel_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

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
            raise StreamerPersistenceError("Streamer persistence failed.") from exc

    @override
    async def update_youtube_channel_id_by_handle(
        self,
        *,
        handle: str,
        youtube_channel_id: str,
    ) -> list[ChannelRecord]:
        try:
            match_values = _handle_match_values(handle)
            if not match_values:
                return []
            rows = list(
                await self._session.scalars(
                    select(ChannelModel)
                    .where(func.lower(func.trim(ChannelModel.handle)).in_(match_values))
                    .order_by(ChannelModel.id)
                )
            )
            if not rows:
                return []
            for row in rows:
                row.youtube_channel_id = youtube_channel_id
            await self._session.commit()
            for row in rows:
                await self._session.refresh(row)
            return [_channel_record(row) for row in rows]
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise StreamerPersistenceError("Streamer persistence failed.") from exc


def _streamer_record(model: StreamerModel) -> StreamerRecord:
    return StreamerRecord(id=model.id, name=model.name)


def _channel_record(model: ChannelModel) -> ChannelRecord:
    return ChannelRecord(
        id=model.id,
        streamer_id=model.streamer_id,
        handle=model.handle,
        name=model.name,
        youtube_channel_id=model.youtube_channel_id,
    )


def _handle_match_values(handle: str) -> set[str]:
    normalized = handle.strip().lower()
    if normalized.startswith("@"):
        normalized = normalized[1:].strip()
    if not normalized:
        return set()
    return {normalized, f"@{normalized}"}
