from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from codex_sdk_cli.api.use_case_dependencies.pipeline_jobs import (
    GetPipelineJobUseCaseDep,
    ListPipelineJobsUseCaseDep,
    RetryPipelineJobUseCaseDep,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobStatus
from codex_sdk_cli.domains.pipeline_jobs.schemas import (
    ListPipelineJobsResponse,
    PipelineJobDetailResponse,
    RetryPipelineJobResponse,
)

router = APIRouter()


@router.get("/jobs", response_model=ListPipelineJobsResponse)
async def list_pipeline_jobs(
    use_case: ListPipelineJobsUseCaseDep,
    step: str | None = None,
    status_filter: Annotated[PipelineJobStatus | None, Query(alias="status")] = None,
    channel_id: Annotated[int | None, Query(alias="channelId", ge=1)] = None,
    subject_type: Annotated[str | None, Query(alias="subjectType")] = None,
    subject_id: Annotated[int | None, Query(alias="subjectId", ge=1)] = None,
    external_key: Annotated[str | None, Query(alias="externalKey")] = None,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ListPipelineJobsResponse:
    return await use_case.execute(
        step=step,
        status=status_filter,
        channel_id=channel_id,
        subject_type=subject_type,
        subject_id=subject_id,
        external_key=external_key,
        cursor=cursor,
        limit=limit,
    )


@router.get("/jobs/{job_id}", response_model=PipelineJobDetailResponse)
async def get_pipeline_job(
    job_id: int,
    use_case: GetPipelineJobUseCaseDep,
) -> PipelineJobDetailResponse:
    return await use_case.execute(job_id)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=RetryPipelineJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def retry_pipeline_job(
    job_id: int,
    use_case: RetryPipelineJobUseCaseDep,
) -> RetryPipelineJobResponse:
    return await use_case.execute(job_id)
