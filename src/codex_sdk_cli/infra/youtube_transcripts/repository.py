from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select
from typing_extensions import override

from codex_sdk_cli.domains.youtube_transcripts.exceptions import YouTubeTranscriptPersistenceError
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataFilters,
    YouTubeTranscriptMetadataRecord,
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
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    async def save_transcript_record(
        self,
        record: YouTubeTranscriptRecord,
    ) -> YouTubeTranscriptMetadataRecord:
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
            await self._session.refresh(model)
            return _metadata_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise YouTubeTranscriptPersistenceError(
                "Transcript metadata persistence failed."
            ) from exc

    @override
    async def find_transcript_metadata_for_request(
        self,
        *,
        video_id: str,
        requested_languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> YouTubeTranscriptMetadataRecord | None:
        try:
            model = await self._session.scalar(
                select(YouTubeTranscriptRecordModel)
                .where(
                    YouTubeTranscriptRecordModel.video_id == video_id,
                    YouTubeTranscriptRecordModel.requested_languages
                    == list(requested_languages),
                    YouTubeTranscriptRecordModel.preserve_formatting
                    == preserve_formatting,
                )
                .order_by(YouTubeTranscriptRecordModel.id.desc())
            )
        except SQLAlchemyError as exc:
            raise YouTubeTranscriptPersistenceError(
                "Transcript metadata persistence failed."
            ) from exc
        if model is None:
            return None
        return _metadata_record(model)

    @override
    async def list_transcript_metadata(
        self,
        filters: YouTubeTranscriptMetadataFilters,
    ) -> list[YouTubeTranscriptMetadataRecord]:
        try:
            statement = select(YouTubeTranscriptRecordModel).order_by(
                YouTubeTranscriptRecordModel.id
            )
            if filters.video_id is not None:
                statement = statement.where(
                    YouTubeTranscriptRecordModel.video_id == filters.video_id
                )
            if filters.language_code is not None:
                statement = statement.where(
                    YouTubeTranscriptRecordModel.language_code == filters.language_code
                )
            rows = await self._session.scalars(
                statement.limit(filters.limit).offset(filters.offset)
            )
            return [_metadata_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise YouTubeTranscriptPersistenceError(
                "Transcript metadata persistence failed."
            ) from exc

    @override
    async def get_transcript_metadata(
        self,
        transcript_id: int,
    ) -> YouTubeTranscriptMetadataRecord | None:
        try:
            model = await self._session.get(YouTubeTranscriptRecordModel, transcript_id)
        except SQLAlchemyError as exc:
            raise YouTubeTranscriptPersistenceError(
                "Transcript metadata persistence failed."
            ) from exc
        if model is None:
            return None
        return _metadata_record(model)

    @override
    async def update_transcript_notes(
        self,
        transcript_id: int,
        notes: str | None,
    ) -> YouTubeTranscriptMetadataRecord | None:
        try:
            model = await self._session.get(YouTubeTranscriptRecordModel, transcript_id)
            if model is None:
                return None
            model.notes = notes
            await self._session.commit()
            await self._session.refresh(model)
            return _metadata_record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise YouTubeTranscriptPersistenceError(
                "Transcript metadata persistence failed."
            ) from exc

    @override
    async def delete_transcript_metadata(self, transcript_id: int) -> bool:
        try:
            model = await self._session.get(YouTubeTranscriptRecordModel, transcript_id)
            if model is None:
                return False
            await self._session.delete(model)
            await self._session.commit()
            return True
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


def _metadata_record(model: YouTubeTranscriptRecordModel) -> YouTubeTranscriptMetadataRecord:
    return YouTubeTranscriptMetadataRecord(
        id=model.id,
        video_id=model.video_id,
        language=model.language,
        language_code=model.language_code,
        is_generated=model.is_generated,
        requested_languages=tuple(model.requested_languages),
        preserve_formatting=model.preserve_formatting,
        storage_bucket=model.storage_bucket,
        storage_object_name=model.storage_object_name,
        storage_uri=model.storage_uri,
        response_sha256=model.response_sha256,
        segment_count=model.segment_count,
        text_length=model.text_length,
        notes=model.notes,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
