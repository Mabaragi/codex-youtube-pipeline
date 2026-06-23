from __future__ import annotations

from fastapi import APIRouter, Query

from .dependencies import ListCodexUsageUseCaseDep
from .schemas import CodexUsageListResponse

router = APIRouter()


@router.get("/codex-usage", response_model=CodexUsageListResponse)
async def list_codex_usage(
    use_case: ListCodexUsageUseCaseDep,
    source: str | None = Query(default=None, min_length=1, max_length=128),
    status: str | None = Query(default=None, min_length=1, max_length=32),
    model: str | None = Query(default=None, min_length=1, max_length=128),
    video_id: int | None = Query(default=None, alias="videoId", ge=1),
    video_task_id: int | None = Query(default=None, alias="videoTaskId", ge=1),
    job_id: int | None = Query(default=None, alias="jobId", ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: int | None = Query(default=None, ge=1),
) -> CodexUsageListResponse:
    return await use_case.execute(
        source=source,
        status=status,
        model=model,
        video_id=video_id,
        video_task_id=video_task_id,
        job_id=job_id,
        limit=limit,
        cursor=cursor,
    )
