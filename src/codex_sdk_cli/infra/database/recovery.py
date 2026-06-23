from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.infra.pipeline_jobs.repository import (
    PipelineJobAttemptModel,
    PipelineJobModel,
)
from codex_sdk_cli.infra.video_tasks.repository import VideoTaskModel

INTERRUPTED_ERROR_TYPE = "ApiProcessRestarted"
INTERRUPTED_ERROR_MESSAGE = (
    "API process started with unfinished running work; the previous in-request "
    "execution was interrupted."
)
WORKER_TIMEOUT_ERROR_TYPE = "WorkerTaskTimedOut"


@dataclass(frozen=True, slots=True)
class InterruptedWorkRecoveryResult:
    pipeline_jobs: int
    pipeline_job_attempts: int
    video_tasks: int

    @property
    def total(self) -> int:
        return self.pipeline_jobs + self.pipeline_job_attempts + self.video_tasks


async def recover_interrupted_running_work(
    session: AsyncSession,
) -> InterruptedWorkRecoveryResult:
    now = datetime.now(UTC)
    recoverable_attempt_filter = (
        (PipelineJobAttemptModel.status == "running")
        & (
            PipelineJobAttemptModel.worker_id.is_(None)
            | (PipelineJobAttemptModel.worker_id == "manual-api")
        )
    )
    recoverable_job_ids = list(
        (
            await session.scalars(
                select(PipelineJobAttemptModel.job_id).where(recoverable_attempt_filter)
            )
        ).all()
    )

    attempts = await session.execute(
        update(PipelineJobAttemptModel)
        .where(recoverable_attempt_filter)
        .values(
            status="failed",
            finished_at=now,
            error_type=INTERRUPTED_ERROR_TYPE,
            error_message=INTERRUPTED_ERROR_MESSAGE,
        )
    )
    jobs = await session.execute(
        update(PipelineJobModel)
        .where(
            PipelineJobModel.status == "running",
            PipelineJobModel.id.in_(recoverable_job_ids),
        )
        .values(
            status="failed",
            completed_at=now,
            updated_at=now,
        )
    )
    tasks = await session.execute(
        update(VideoTaskModel)
        .where(
            VideoTaskModel.status == "running",
            or_(VideoTaskModel.worker_id.is_(None), VideoTaskModel.worker_id == "manual-api"),
        )
        .values(
            status="failed",
            completed_at=now,
            updated_at=now,
            error_type=INTERRUPTED_ERROR_TYPE,
            error_message=INTERRUPTED_ERROR_MESSAGE,
        )
    )
    await session.commit()
    return InterruptedWorkRecoveryResult(
        pipeline_jobs=_rowcount(jobs),
        pipeline_job_attempts=_rowcount(attempts),
        video_tasks=_rowcount(tasks),
    )


def _rowcount(result: object) -> int:
    rowcount = cast(CursorResult[object], result).rowcount
    return max(rowcount if rowcount is not None else 0, 0)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def recover_timed_out_worker_tasks(
    session: AsyncSession,
    *,
    task_name: str,
    worker_id_prefix: str,
) -> int:
    now = datetime.now(UTC)
    tasks = list(
        (
            await session.scalars(
                select(VideoTaskModel).where(
                    VideoTaskModel.task_name == task_name,
                    VideoTaskModel.status == "running",
                    VideoTaskModel.worker_id.like(f"{worker_id_prefix}%"),
                )
            )
        ).all()
    )
    recovered = 0
    for task in tasks:
        if task.started_at is None:
            continue
        started_at = _as_utc(task.started_at)
        if started_at + timedelta(seconds=task.timeout_seconds) > now:
            continue
        message = f"Worker task exceeded {task.timeout_seconds} seconds."
        task.status = "timed_out"
        task.completed_at = now
        task.updated_at = now
        task.error_type = WORKER_TIMEOUT_ERROR_TYPE
        task.error_message = message
        if task.job_attempt_id is not None:
            await session.execute(
                update(PipelineJobAttemptModel)
                .where(PipelineJobAttemptModel.id == task.job_attempt_id)
                .values(
                    status="failed",
                    finished_at=now,
                    error_type=WORKER_TIMEOUT_ERROR_TYPE,
                    error_message=message,
                )
            )
        if task.job_id is not None:
            await session.execute(
                update(PipelineJobModel)
                .where(PipelineJobModel.id == task.job_id)
                .values(status="failed", completed_at=now, updated_at=now)
            )
        recovered += 1
    if recovered:
        await session.commit()
    return recovered
