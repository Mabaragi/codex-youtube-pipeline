from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import override

from codex_sdk_cli.domains.asr.ports import (
    AudioChunkCheckpoint,
    AudioChunkCheckpointPort,
    AudioTranscriptionSegment,
)
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.work.models import WorkItemModel


class AsrChunkCheckpointModel(Base):
    __tablename__ = "asr_chunk_checkpoints"
    __table_args__ = (
        UniqueConstraint("work_item_id", "chunk_index", name="uq_asr_chunk_checkpoint_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    segments_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    device: Mapped[str] = mapped_column(String(32), nullable=False)
    compute_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SqlAlchemyAsrChunkCheckpointRepository(AudioChunkCheckpointPort):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        work_item_id: int,
    ) -> None:
        self._session_factory = session_factory
        self._work_item_id = work_item_id

    @override
    async def load(self, chunk_index: int) -> AudioChunkCheckpoint | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(AsrChunkCheckpointModel).where(
                    AsrChunkCheckpointModel.work_item_id == self._work_item_id,
                    AsrChunkCheckpointModel.chunk_index == chunk_index,
                )
            )
        if model is None:
            return None
        return AudioChunkCheckpoint(
            chunk_index=model.chunk_index,
            segments=tuple(
                AudioTranscriptionSegment(
                    text=str(item["text"]),
                    start_seconds=_float_value(item, "startSeconds"),
                    end_seconds=_float_value(item, "endSeconds"),
                )
                for item in model.segments_json
            ),
            device=model.device,
            compute_type=model.compute_type,
        )

    @override
    async def save(self, checkpoint: AudioChunkCheckpoint) -> None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(AsrChunkCheckpointModel).where(
                    AsrChunkCheckpointModel.work_item_id == self._work_item_id,
                    AsrChunkCheckpointModel.chunk_index == checkpoint.chunk_index,
                )
            )
            if model is None:
                model = AsrChunkCheckpointModel(
                    work_item_id=self._work_item_id,
                    chunk_index=checkpoint.chunk_index,
                    segments_json=[],
                    device=checkpoint.device,
                    compute_type=checkpoint.compute_type,
                )
                session.add(model)
            model.segments_json = [
                {
                    "text": item.text,
                    "startSeconds": item.start_seconds,
                    "endSeconds": item.end_seconds,
                }
                for item in checkpoint.segments
            ]
            model.device = checkpoint.device
            model.compute_type = checkpoint.compute_type
            work_item = await session.get(WorkItemModel, self._work_item_id)
            if work_item is not None:
                previous = work_item.output_json or {}
                work_item.output_json = {
                    **previous,
                    "completedChunkCount": checkpoint.chunk_index + 1,
                    "lastCompletedChunkIndex": checkpoint.chunk_index,
                    "device": checkpoint.device,
                    "computeType": checkpoint.compute_type,
                }
            await session.commit()


def _float_value(values: dict[str, object], key: str) -> float:
    value = values.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise ValueError(f"Checkpoint {key} must be numeric.")
