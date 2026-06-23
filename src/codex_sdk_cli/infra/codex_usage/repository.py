from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import override

from codex_sdk_cli.domains.codex_usage.ports import (
    CodexUsageCreate,
    CodexUsageListQuery,
    CodexUsageListResult,
    CodexUsageRecord,
    CodexUsageRepositoryPort,
    CodexUsageStatus,
    CodexUsageSummaryRecord,
    JsonObject,
)
from codex_sdk_cli.infra.database.base import Base


class CodexUsagePersistenceError(Exception):
    """Raised when Codex usage persistence fails."""


class CodexRunUsageModel(Base):
    __tablename__ = "codex_run_usages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="codex_run_usages_status_allowed",
        ),
        CheckConstraint("duration_ms >= 0", name="codex_run_usages_duration_min"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="codex_run_usages_input_tokens_min",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="codex_run_usages_output_tokens_min",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="codex_run_usages_total_tokens_min",
        ),
        CheckConstraint(
            "cached_input_tokens IS NULL OR cached_input_tokens >= 0",
            name="codex_run_usages_cached_input_tokens_min",
        ),
        CheckConstraint(
            "reasoning_output_tokens IS NULL OR reasoning_output_tokens >= 0",
            name="codex_run_usages_reasoning_output_tokens_min",
        ),
        Index("ix_codex_run_usages_created_at", "created_at", "id"),
        Index("ix_codex_run_usages_source", "source"),
        Index("ix_codex_run_usages_model", "model"),
        Index("ix_codex_run_usages_status", "status"),
        Index("ix_codex_run_usages_video_task_id", "video_task_id"),
        Index("ix_codex_run_usages_job_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    turn_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    usage_json: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"),
        nullable=True,
    )
    video_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_job_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    transcript_id: Mapped[int | None] = mapped_column(
        ForeignKey("youtube_transcripts.id", ondelete="SET NULL"),
        nullable=True,
    )
    window_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SqlAlchemyCodexUsageRepository(CodexUsageRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_usage(self, usage: CodexUsageCreate) -> CodexUsageRecord:
        try:
            model = CodexRunUsageModel(
                source=usage.source,
                operation=usage.operation,
                model=usage.model,
                status=usage.status,
                thread_id=usage.thread_id,
                turn_id=usage.turn_id,
                usage_json=usage.usage_json,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                reasoning_output_tokens=usage.reasoning_output_tokens,
                duration_ms=usage.duration_ms,
                error_type=usage.error_type,
                error_message=usage.error_message,
                video_id=usage.video_id,
                video_task_id=usage.video_task_id,
                job_id=usage.job_id,
                job_attempt_id=usage.job_attempt_id,
                transcript_id=usage.transcript_id,
                window_index=usage.window_index,
            )
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise CodexUsagePersistenceError("Codex usage persistence failed.") from exc

    @override
    async def list_usages(self, query: CodexUsageListQuery) -> CodexUsageListResult:
        conditions = _conditions(query, include_cursor=False)
        page_conditions = _conditions(query, include_cursor=True)
        try:
            rows = list(
                (
                    await self._session.scalars(
                        select(CodexRunUsageModel)
                        .where(*page_conditions)
                        .order_by(
                            CodexRunUsageModel.created_at.desc(),
                            CodexRunUsageModel.id.desc(),
                        )
                        .limit(query.limit + 1)
                    )
                ).all()
            )
            summary_row = (
                await self._session.execute(
                    select(
                        func.count(CodexRunUsageModel.id),
                        func.coalesce(func.sum(CodexRunUsageModel.input_tokens), 0),
                        func.coalesce(func.sum(CodexRunUsageModel.output_tokens), 0),
                        func.coalesce(func.sum(CodexRunUsageModel.total_tokens), 0),
                        func.coalesce(func.sum(CodexRunUsageModel.cached_input_tokens), 0),
                        func.coalesce(
                            func.sum(CodexRunUsageModel.reasoning_output_tokens),
                            0,
                        ),
                    ).where(*conditions)
                )
            ).one()
        except SQLAlchemyError as exc:
            raise CodexUsagePersistenceError("Codex usage persistence failed.") from exc

        items = rows[: query.limit]
        next_cursor = rows[query.limit].id if len(rows) > query.limit else None
        return CodexUsageListResult(
            items=[_record(row) for row in items],
            next_cursor=next_cursor,
            summary=CodexUsageSummaryRecord(
                run_count=_summary_int(summary_row[0]),
                input_tokens=_summary_int(summary_row[1]),
                output_tokens=_summary_int(summary_row[2]),
                total_tokens=_summary_int(summary_row[3]),
                cached_input_tokens=_summary_int(summary_row[4]),
                reasoning_output_tokens=_summary_int(summary_row[5]),
            ),
        )


class SessionFactoryCodexUsageRepository(CodexUsageRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @override
    async def create_usage(self, usage: CodexUsageCreate) -> CodexUsageRecord:
        async with self._session_factory() as session:
            return await SqlAlchemyCodexUsageRepository(session).create_usage(usage)

    @override
    async def list_usages(self, query: CodexUsageListQuery) -> CodexUsageListResult:
        async with self._session_factory() as session:
            return await SqlAlchemyCodexUsageRepository(session).list_usages(query)


def _conditions(
    query: CodexUsageListQuery,
    *,
    include_cursor: bool,
):
    conditions = []
    if query.source is not None:
        conditions.append(CodexRunUsageModel.source == query.source)
    if query.status is not None:
        conditions.append(CodexRunUsageModel.status == query.status)
    if query.model is not None:
        conditions.append(CodexRunUsageModel.model == query.model)
    if query.video_id is not None:
        conditions.append(CodexRunUsageModel.video_id == query.video_id)
    if query.video_task_id is not None:
        conditions.append(CodexRunUsageModel.video_task_id == query.video_task_id)
    if query.job_id is not None:
        conditions.append(CodexRunUsageModel.job_id == query.job_id)
    if include_cursor and query.cursor is not None:
        conditions.append(CodexRunUsageModel.id < query.cursor)
    return conditions


def _status(value: str) -> CodexUsageStatus:
    return "failed" if value == "failed" else "succeeded"


def _summary_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _record(model: CodexRunUsageModel) -> CodexUsageRecord:
    return CodexUsageRecord(
        id=model.id,
        source=model.source,
        operation=model.operation,
        model=model.model,
        status=_status(model.status),
        thread_id=model.thread_id,
        turn_id=model.turn_id,
        usage_json=model.usage_json,
        input_tokens=model.input_tokens,
        output_tokens=model.output_tokens,
        total_tokens=model.total_tokens,
        cached_input_tokens=model.cached_input_tokens,
        reasoning_output_tokens=model.reasoning_output_tokens,
        duration_ms=model.duration_ms,
        error_type=model.error_type,
        error_message=model.error_message,
        video_id=model.video_id,
        video_task_id=model.video_task_id,
        job_id=model.job_id,
        job_attempt_id=model.job_attempt_id,
        transcript_id=model.transcript_id,
        window_index=model.window_index,
        created_at=model.created_at,
    )
