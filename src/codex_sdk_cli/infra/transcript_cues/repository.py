from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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

from codex_sdk_cli.domains.transcript_cues.exceptions import TranscriptCuePersistenceError
from codex_sdk_cli.domains.transcript_cues.ports import (
    TranscriptCueCreate,
    TranscriptCueRecord,
    TranscriptCueRepositoryPort,
    TranscriptCueSummaryRecord,
)
from codex_sdk_cli.infra.database.base import Base


class TranscriptCueModel(Base):
    __tablename__ = "transcript_cues"
    __table_args__ = (
        UniqueConstraint(
            "transcript_id",
            "cue_index",
            name="uq_transcript_cues_transcript_index",
        ),
        UniqueConstraint("cue_id", name="uq_transcript_cues_cue_id"),
        CheckConstraint("cue_index >= 1", name="transcript_cues_cue_index_min"),
        CheckConstraint("start_ms >= 0", name="transcript_cues_start_ms_non_negative"),
        CheckConstraint("end_ms >= start_ms", name="transcript_cues_end_ms_valid"),
        CheckConstraint("duration_ms >= 0", name="transcript_cues_duration_ms_non_negative"),
        CheckConstraint(
            "source_segment_index >= 0",
            name="transcript_cues_source_segment_index_non_negative",
        ),
        Index("ix_transcript_cues_transcript_index", "transcript_id", "cue_index"),
        Index("ix_transcript_cues_source_job_id", "source_job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transcript_id: Mapped[int] = mapped_column(
        ForeignKey("youtube_transcripts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    cue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cue_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    source_segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_job_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_job_attempts.id", ondelete="SET NULL"),
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


class SqlAlchemyTranscriptCueRepository(TranscriptCueRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def replace_cues(
        self,
        transcript_id: int,
        cues: list[TranscriptCueCreate],
    ) -> list[TranscriptCueRecord]:
        try:
            await self._session.execute(
                delete(TranscriptCueModel).where(
                    TranscriptCueModel.transcript_id == transcript_id
                )
            )
            self._session.add_all([_cue_model(cue) for cue in cues])
            await self._session.commit()
            return await self.list_cues(transcript_id)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise TranscriptCuePersistenceError(
                "Transcript cue persistence failed."
            ) from exc

    @override
    async def list_cues(self, transcript_id: int) -> list[TranscriptCueRecord]:
        try:
            rows = await self._session.scalars(
                select(TranscriptCueModel)
                .where(TranscriptCueModel.transcript_id == transcript_id)
                .order_by(TranscriptCueModel.cue_index.asc())
            )
            return [_cue_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise TranscriptCuePersistenceError(
                "Transcript cue persistence failed."
            ) from exc

    @override
    async def summarize_cues(self, transcript_id: int) -> TranscriptCueSummaryRecord:
        records = await self.list_cues(transcript_id)
        source_job_id = records[0].source_job_id if records else None
        return TranscriptCueSummaryRecord(
            transcript_id=transcript_id,
            cue_count=len(records),
            first_cue_id=records[0].cue_id if records else None,
            last_cue_id=records[-1].cue_id if records else None,
            source_job_id=source_job_id,
        )


def _cue_model(cue: TranscriptCueCreate) -> TranscriptCueModel:
    return TranscriptCueModel(
        transcript_id=cue.transcript_id,
        cue_id=cue.cue_id,
        cue_index=cue.cue_index,
        text=cue.text,
        start_ms=cue.start_ms,
        end_ms=cue.end_ms,
        duration_ms=cue.duration_ms,
        source_segment_index=cue.source_segment_index,
        source_job_id=cue.source_job_id,
        source_job_attempt_id=cue.source_job_attempt_id,
    )


def _cue_record(model: TranscriptCueModel) -> TranscriptCueRecord:
    return TranscriptCueRecord(
        id=model.id,
        transcript_id=model.transcript_id,
        cue_id=model.cue_id,
        cue_index=model.cue_index,
        text=model.text,
        start_ms=model.start_ms,
        end_ms=model.end_ms,
        duration_ms=model.duration_ms,
        source_segment_index=model.source_segment_index,
        source_job_id=model.source_job_id,
        source_job_attempt_id=model.source_job_attempt_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
