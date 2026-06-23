from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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

from codex_sdk_cli.domains.micro_events.constants import MICRO_EVENT_EXTRACT_TASK_NAME
from codex_sdk_cli.domains.micro_events.exceptions import (
    MicroEventExtractionPersistenceError,
)
from codex_sdk_cli.domains.micro_events.ports import (
    Activity,
    ApplyScope,
    AsrCorrectionCandidateCreate,
    AsrCorrectionCandidateRecord,
    CorrectionType,
    JsonObject,
    MicroEventCandidateCreate,
    MicroEventCandidateRecord,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionRepositoryPort,
    MicroEventExtractionWindowCreate,
    MicroEventExtractionWindowRecord,
    WindowStatus,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskStatus
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel
from codex_sdk_cli.infra.videos.repository import VideoModel


class MicroEventExtractionWindowModel(Base):
    __tablename__ = "micro_event_extraction_windows"
    __table_args__ = (
        UniqueConstraint(
            "video_task_id",
            "window_index",
            name="uq_micro_event_windows_task_index",
        ),
        CheckConstraint("window_index >= 1", name="micro_event_windows_index_min"),
        CheckConstraint("cue_count >= 1", name="micro_event_windows_cue_count_min"),
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="micro_event_windows_status_allowed",
        ),
        Index("ix_micro_event_windows_video_task", "video_task_id", "window_index"),
        Index("ix_micro_event_windows_video_id", "video_id"),
        Index("ix_micro_event_windows_transcript_id", "transcript_id"),
        Index("ix_micro_event_windows_source_job_id", "source_job_id"),
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
    transcript_id: Mapped[int] = mapped_column(
        ForeignKey("youtube_transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_cue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    end_cue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    carry_out_unfinished: Mapped[bool] = mapped_column(Boolean, nullable=False)
    codex_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    codex_turn_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_response_json: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class MicroEventCandidateModel(Base):
    __tablename__ = "micro_event_candidates"
    __table_args__ = (
        UniqueConstraint(
            "window_id",
            "candidate_index",
            name="uq_micro_event_candidates_window_index",
        ),
        CheckConstraint(
            "candidate_index >= 1",
            name="micro_event_candidates_index_min",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="micro_event_candidates_confidence_range",
        ),
        Index("ix_micro_event_candidates_window_id", "window_id"),
        Index("ix_micro_event_candidates_video_task", "video_task_id"),
        Index("ix_micro_event_candidates_transcript_id", "transcript_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    window_id: Mapped[int] = mapped_column(
        ForeignKey("micro_event_extraction_windows.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_task_id: Mapped[int] = mapped_column(
        ForeignKey("video_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    transcript_id: Mapped[int] = mapped_column(
        ForeignKey("youtube_transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    activity: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    start_cue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    end_cue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_cue_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    boundary_before: Mapped[bool] = mapped_column(Boolean, nullable=False)
    boundary_after: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
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


class AsrCorrectionCandidateModel(Base):
    __tablename__ = "asr_correction_candidates"
    __table_args__ = (
        UniqueConstraint(
            "window_id",
            "candidate_index",
            name="uq_asr_correction_candidates_window_index",
        ),
        CheckConstraint(
            "candidate_index >= 1",
            name="asr_correction_candidates_index_min",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="asr_correction_candidates_confidence_range",
        ),
        Index("ix_asr_correction_candidates_window_id", "window_id"),
        Index("ix_asr_correction_candidates_video_task", "video_task_id"),
        Index("ix_asr_correction_candidates_transcript_id", "transcript_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    window_id: Mapped[int] = mapped_column(
        ForeignKey("micro_event_extraction_windows.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_task_id: Mapped[int] = mapped_column(
        ForeignKey("video_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    transcript_id: Mapped[int] = mapped_column(
        ForeignKey("youtube_transcripts.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    original: Mapped[str] = mapped_column(Text, nullable=False)
    suggested: Mapped[str] = mapped_column(Text, nullable=False)
    correction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    apply_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_cue_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
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


class SqlAlchemyMicroEventExtractionRepository(MicroEventExtractionRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def delete_extraction(self, video_task_id: int) -> None:
        try:
            await self._delete_extraction(video_task_id)
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise MicroEventExtractionPersistenceError(
                "Micro-event extraction persistence failed."
            ) from exc

    @override
    async def replace_extraction(
        self,
        video_task_id: int,
        windows: list[MicroEventExtractionWindowCreate],
    ) -> MicroEventExtractionDetailRecord | None:
        try:
            await self._delete_extraction(video_task_id)
            for window in sorted(windows, key=lambda item: item.window_index):
                model = _window_model(window)
                self._session.add(model)
                await self._session.flush()
                self._session.add_all(
                    [
                        _micro_event_model(model.id, window, candidate)
                        for candidate in window.micro_events
                    ]
                )
                self._session.add_all(
                    [
                        _asr_correction_model(model.id, window, candidate)
                        for candidate in window.asr_correction_candidates
                    ]
                )
            await self._session.commit()
            first = windows[0] if windows else None
            if first is None:
                return None
            return await self.get_extraction(
                video_id=first.video_id,
                video_task_id=video_task_id,
            )
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise MicroEventExtractionPersistenceError(
                "Micro-event extraction persistence failed."
            ) from exc

    @override
    async def get_extraction(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> MicroEventExtractionDetailRecord | None:
        try:
            row = (
                await self._session.execute(
                    select(VideoTaskModel, VideoModel)
                    .join(VideoModel, VideoTaskModel.video_id == VideoModel.id)
                    .where(
                        VideoTaskModel.id == video_task_id,
                        VideoTaskModel.video_id == video_id,
                        VideoTaskModel.task_name == MICRO_EVENT_EXTRACT_TASK_NAME,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            task, video = row
            windows = await self._window_records(video_task_id)
            return _detail_record(task, video, windows)
        except SQLAlchemyError as exc:
            raise MicroEventExtractionPersistenceError(
                "Micro-event extraction persistence failed."
            ) from exc

    @override
    async def get_latest_succeeded_extraction(
        self,
        *,
        video_id: int,
    ) -> MicroEventExtractionDetailRecord | None:
        try:
            row = (
                await self._session.execute(
                    select(VideoTaskModel, VideoModel)
                    .join(VideoModel, VideoTaskModel.video_id == VideoModel.id)
                    .where(
                        VideoTaskModel.video_id == video_id,
                        VideoTaskModel.task_name == MICRO_EVENT_EXTRACT_TASK_NAME,
                        VideoTaskModel.status == "succeeded",
                    )
                    .order_by(VideoTaskModel.id.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            task, video = row
            windows = await self._window_records(task.id)
            return _detail_record(task, video, windows)
        except SQLAlchemyError as exc:
            raise MicroEventExtractionPersistenceError(
                "Micro-event extraction persistence failed."
            ) from exc

    async def _delete_extraction(self, video_task_id: int) -> None:
        window_ids = select(MicroEventExtractionWindowModel.id).where(
            MicroEventExtractionWindowModel.video_task_id == video_task_id
        )
        await self._session.execute(
            delete(MicroEventCandidateModel).where(
                MicroEventCandidateModel.window_id.in_(window_ids)
            )
        )
        await self._session.execute(
            delete(AsrCorrectionCandidateModel).where(
                AsrCorrectionCandidateModel.window_id.in_(window_ids)
            )
        )
        await self._session.execute(
            delete(MicroEventExtractionWindowModel).where(
                MicroEventExtractionWindowModel.video_task_id == video_task_id
            )
        )

    async def _window_records(
        self,
        video_task_id: int,
    ) -> list[MicroEventExtractionWindowRecord]:
        windows = list(
            (
                await self._session.scalars(
                    select(MicroEventExtractionWindowModel)
                    .where(MicroEventExtractionWindowModel.video_task_id == video_task_id)
                    .order_by(MicroEventExtractionWindowModel.window_index.asc())
                )
            ).all()
        )
        window_ids = [window.id for window in windows]
        micro_events_by_window: dict[int, list[MicroEventCandidateRecord]] = {
            window.id: [] for window in windows
        }
        asr_by_window: dict[int, list[AsrCorrectionCandidateRecord]] = {
            window.id: [] for window in windows
        }
        if window_ids:
            micro_events = (
                await self._session.scalars(
                    select(MicroEventCandidateModel)
                    .where(MicroEventCandidateModel.window_id.in_(window_ids))
                    .order_by(
                        MicroEventCandidateModel.window_id.asc(),
                        MicroEventCandidateModel.candidate_index.asc(),
                    )
                )
            ).all()
            for candidate in micro_events:
                micro_events_by_window[candidate.window_id].append(
                    _micro_event_record(candidate)
                )
            asr_candidates = (
                await self._session.scalars(
                    select(AsrCorrectionCandidateModel)
                    .where(AsrCorrectionCandidateModel.window_id.in_(window_ids))
                    .order_by(
                        AsrCorrectionCandidateModel.window_id.asc(),
                        AsrCorrectionCandidateModel.candidate_index.asc(),
                    )
                )
            ).all()
            for candidate in asr_candidates:
                asr_by_window[candidate.window_id].append(_asr_record(candidate))
        return [
            _window_record(
                window,
                micro_events=micro_events_by_window[window.id],
                asr_correction_candidates=asr_by_window[window.id],
            )
            for window in windows
        ]


def _window_model(window: MicroEventExtractionWindowCreate) -> MicroEventExtractionWindowModel:
    return MicroEventExtractionWindowModel(
        video_task_id=window.video_task_id,
        video_id=window.video_id,
        transcript_id=window.transcript_id,
        window_index=window.window_index,
        start_cue_id=window.start_cue_id,
        end_cue_id=window.end_cue_id,
        cue_count=window.cue_count,
        status=window.status,
        carry_out_unfinished=window.carry_out_unfinished,
        codex_thread_id=window.codex_thread_id,
        codex_turn_id=window.codex_turn_id,
        raw_response_text=window.raw_response_text,
        parsed_response_json=window.parsed_response_json,
        validation_error=window.validation_error,
        source_job_id=window.source_job_id,
        source_job_attempt_id=window.source_job_attempt_id,
    )


def _micro_event_model(
    window_id: int,
    window: MicroEventExtractionWindowCreate,
    candidate: MicroEventCandidateCreate,
) -> MicroEventCandidateModel:
    return MicroEventCandidateModel(
        window_id=window_id,
        video_task_id=window.video_task_id,
        transcript_id=window.transcript_id,
        candidate_index=candidate.candidate_index,
        activity=candidate.activity,
        event=candidate.event,
        start_cue_id=candidate.start_cue_id,
        end_cue_id=candidate.end_cue_id,
        evidence_cue_ids=candidate.evidence_cue_ids,
        boundary_before=candidate.boundary_before,
        boundary_after=candidate.boundary_after,
        confidence=candidate.confidence,
    )


def _asr_correction_model(
    window_id: int,
    window: MicroEventExtractionWindowCreate,
    candidate: AsrCorrectionCandidateCreate,
) -> AsrCorrectionCandidateModel:
    return AsrCorrectionCandidateModel(
        window_id=window_id,
        video_task_id=window.video_task_id,
        transcript_id=window.transcript_id,
        candidate_index=candidate.candidate_index,
        original=candidate.original,
        suggested=candidate.suggested,
        correction_type=candidate.correction_type,
        apply_scope=candidate.apply_scope,
        evidence_cue_ids=candidate.evidence_cue_ids,
        confidence=candidate.confidence,
    )


def _detail_record(
    task: VideoTaskModel,
    video: VideoModel,
    windows: list[MicroEventExtractionWindowRecord],
) -> MicroEventExtractionDetailRecord:
    return MicroEventExtractionDetailRecord(
        video_task_id=task.id,
        video_id=task.video_id,
        youtube_video_id=video.youtube_video_id,
        transcript_id=task.output_transcript_id,
        status=_task_status(task.status),
        job_id=task.job_id,
        job_attempt_id=task.job_attempt_id,
        output_json=task.output_json,
        error_type=task.error_type,
        error_message=task.error_message,
        started_at=task.started_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        windows=windows,
    )


def _window_record(
    model: MicroEventExtractionWindowModel,
    *,
    micro_events: list[MicroEventCandidateRecord],
    asr_correction_candidates: list[AsrCorrectionCandidateRecord],
) -> MicroEventExtractionWindowRecord:
    return MicroEventExtractionWindowRecord(
        id=model.id,
        video_task_id=model.video_task_id,
        video_id=model.video_id,
        transcript_id=model.transcript_id,
        window_index=model.window_index,
        start_cue_id=model.start_cue_id,
        end_cue_id=model.end_cue_id,
        cue_count=model.cue_count,
        status=_window_status(model.status),
        carry_out_unfinished=model.carry_out_unfinished,
        codex_thread_id=model.codex_thread_id,
        codex_turn_id=model.codex_turn_id,
        raw_response_text=model.raw_response_text,
        parsed_response_json=model.parsed_response_json,
        validation_error=model.validation_error,
        source_job_id=model.source_job_id,
        source_job_attempt_id=model.source_job_attempt_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        micro_events=micro_events,
        asr_correction_candidates=asr_correction_candidates,
    )


def _micro_event_record(model: MicroEventCandidateModel) -> MicroEventCandidateRecord:
    return MicroEventCandidateRecord(
        id=model.id,
        window_id=model.window_id,
        video_task_id=model.video_task_id,
        transcript_id=model.transcript_id,
        candidate_index=model.candidate_index,
        activity=_activity(model.activity),
        event=model.event,
        start_cue_id=model.start_cue_id,
        end_cue_id=model.end_cue_id,
        evidence_cue_ids=model.evidence_cue_ids,
        boundary_before=model.boundary_before,
        boundary_after=model.boundary_after,
        confidence=model.confidence,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _asr_record(model: AsrCorrectionCandidateModel) -> AsrCorrectionCandidateRecord:
    return AsrCorrectionCandidateRecord(
        id=model.id,
        window_id=model.window_id,
        video_task_id=model.video_task_id,
        transcript_id=model.transcript_id,
        candidate_index=model.candidate_index,
        original=model.original,
        suggested=model.suggested,
        correction_type=_correction_type(model.correction_type),
        apply_scope=_apply_scope(model.apply_scope),
        evidence_cue_ids=model.evidence_cue_ids,
        confidence=model.confidence,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _window_status(value: str) -> WindowStatus:
    return "failed" if value == "failed" else "succeeded"


def _task_status(value: str) -> VideoTaskStatus:
    allowed: set[VideoTaskStatus] = {
        "pending",
        "running",
        "succeeded",
        "failed",
        "timed_out",
        "no_transcript",
        "skipped",
        "canceled",
    }
    return cast(VideoTaskStatus, value) if value in allowed else "running"


def _activity(value: str) -> Activity:
    allowed: set[Activity] = {
        "PRE_ROLL",
        "OPENING",
        "JUST_CHATTING",
        "ANNOUNCEMENT",
        "COMMUNITY_REVIEW",
        "MEDIA_REVIEW",
        "GAME_SETUP",
        "GAMEPLAY",
        "BREAK",
        "POST_GAME",
        "CLOSING",
        "UNKNOWN",
    }
    return cast(Activity, value) if value in allowed else "UNKNOWN"


def _correction_type(value: str) -> CorrectionType:
    allowed: set[CorrectionType] = {
        "PROPER_NOUN",
        "GAME_TITLE",
        "CONTENT_TITLE",
        "COMMON_WORD",
        "FOOD",
        "PLACE",
        "STREAM_TERM",
        "CONTEXTUAL_TERM",
        "UNCERTAIN",
    }
    return cast(CorrectionType, value) if value in allowed else "UNCERTAIN"


def _apply_scope(value: str) -> ApplyScope:
    allowed: set[ApplyScope] = {
        "NONE",
        "SEARCH_ONLY",
        "SEARCH_AND_SUMMARY",
        "DISPLAY_ALLOWED",
    }
    return cast(ApplyScope, value) if value in allowed else "NONE"
