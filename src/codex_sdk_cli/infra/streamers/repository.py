from __future__ import annotations

from sqlalchemy import Integer, String
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


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
    return StreamerRecord(id=model.id, name=model.name)
