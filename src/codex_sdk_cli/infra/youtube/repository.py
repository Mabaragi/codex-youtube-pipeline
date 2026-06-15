from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select
from typing_extensions import override

from codex_sdk_cli.domains.youtube.exceptions import YouTubeTranscriptPersistenceError
from codex_sdk_cli.domains.youtube.ports import (
    YouTubeTranscriptRecord,
    YouTubeTranscriptRepositoryPort,
)
from codex_sdk_cli.infra.database.base import Base


class YouTubeTranscriptRecordModel(Base):
    __tablename__ = "youtube_transcripts"
    __table_args__ = (
        CheckConstraint("segment_count >= 0", name="segment_count_non_negative"),
        CheckConstraint("text_length >= 0", name="text_length_non_negative"),
        Index("ix_youtube_transcripts_video_id_language_code", "video_id", "language_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(11), index=True, nullable=False)
    language: Mapped[str] = mapped_column(String(128), nullable=False)
    language_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    is_generated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requested_languages: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    preserve_formatting: Mapped[bool] = mapped_column(Boolean, nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_object_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    response_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    text_length: Mapped[int] = mapped_column(Integer, nullable=False)
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


class SqlAlchemyYouTubeTranscriptRepository(YouTubeTranscriptRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def save_transcript_record(self, record: YouTubeTranscriptRecord) -> None:
        try:
            model = await self._session.scalar(
                select(YouTubeTranscriptRecordModel).where(
                    YouTubeTranscriptRecordModel.storage_object_name == record.storage_object_name
                )
            )
            if model is None:
                model = YouTubeTranscriptRecordModel(storage_object_name=record.storage_object_name)
                self._session.add(model)

            _apply_record(model, record)
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise YouTubeTranscriptPersistenceError(
                "Transcript metadata persistence failed."
            ) from exc


def _apply_record(
    model: YouTubeTranscriptRecordModel,
    record: YouTubeTranscriptRecord,
) -> None:
    model.video_id = record.video_id
    model.language = record.language
    model.language_code = record.language_code
    model.is_generated = record.is_generated
    model.requested_languages = list(record.requested_languages)
    model.preserve_formatting = record.preserve_formatting
    model.storage_bucket = record.storage_bucket
    model.storage_uri = record.storage_uri
    model.response_sha256 = record.response_sha256
    model.segment_count = record.segment_count
    model.text_length = record.text_length
