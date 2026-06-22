from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import update
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

    attempts = await session.execute(
        update(PipelineJobAttemptModel)
        .where(PipelineJobAttemptModel.status == "running")
        .values(
            status="failed",
            finished_at=now,
            error_type=INTERRUPTED_ERROR_TYPE,
            error_message=INTERRUPTED_ERROR_MESSAGE,
        )
    )
    jobs = await session.execute(
        update(PipelineJobModel)
        .where(PipelineJobModel.status == "running")
        .values(
            status="failed",
            completed_at=now,
            updated_at=now,
        )
    )
    tasks = await session.execute(
        update(VideoTaskModel)
        .where(VideoTaskModel.status == "running")
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
