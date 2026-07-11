from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.infra.work.models import WorkAttemptModel, WorkItemModel

INTERRUPTED_ERROR_TYPE = "ApiProcessRestarted"
INTERRUPTED_ERROR_MESSAGE = (
    "API process started with unfinished inline work; the previous execution "
    "was interrupted."
)


@dataclass(frozen=True, slots=True)
class InterruptedWorkRecoveryResult:
    work_items: int
    work_attempts: int

    @property
    def total(self) -> int:
        return self.work_items + self.work_attempts


async def recover_interrupted_running_work(
    session: AsyncSession,
) -> InterruptedWorkRecoveryResult:
    now = datetime.now(UTC)
    recoverable_attempt_filter = (
        (WorkAttemptModel.status == "running")
        & (
            WorkAttemptModel.worker_id.is_(None)
            | (WorkAttemptModel.worker_id == "manual-api")
            | WorkAttemptModel.worker_id.like("%:manual-api")
        )
    )
    recoverable_work_item_ids = list(
        (
            await session.scalars(
                select(WorkAttemptModel.work_item_id).where(recoverable_attempt_filter)
            )
        ).all()
    )
    attempts = await session.execute(
        update(WorkAttemptModel)
        .where(recoverable_attempt_filter)
        .values(
            status="failed",
            finished_at=now,
            error_code="work.api_process_restarted",
            error_type=INTERRUPTED_ERROR_TYPE,
            error_message=INTERRUPTED_ERROR_MESSAGE,
        )
    )
    items = await session.execute(
        update(WorkItemModel)
        .where(
            WorkItemModel.status == "running",
            WorkItemModel.execution_mode == "inline",
            WorkItemModel.id.in_(recoverable_work_item_ids),
        )
        .values(
            status="failed",
            completed_at=now,
            updated_at=now,
            lease_owner=None,
            lease_expires_at=None,
            error_code="work.api_process_restarted",
            error_type=INTERRUPTED_ERROR_TYPE,
            error_message=INTERRUPTED_ERROR_MESSAGE,
        )
    )
    await session.commit()
    return InterruptedWorkRecoveryResult(
        work_items=_rowcount(items),
        work_attempts=_rowcount(attempts),
    )


def _rowcount(result: object) -> int:
    rowcount = cast(CursorResult[object], result).rowcount
    return max(rowcount if rowcount is not None else 0, 0)
