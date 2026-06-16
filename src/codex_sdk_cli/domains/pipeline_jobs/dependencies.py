from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    PipelineJobRepositoryDep,
    StreamerRepositoryDep,
    YouTubeDataClientDep,
)
from codex_sdk_cli.domains.youtube_data.use_cases import ResolveYouTubeChannelUseCase

from .use_cases import GetPipelineJobUseCase, ListPipelineJobsUseCase, RetryPipelineJobUseCase


def get_list_pipeline_jobs_use_case(
    pipeline_jobs: PipelineJobRepositoryDep,
) -> ListPipelineJobsUseCase:
    return ListPipelineJobsUseCase(pipeline_jobs)


def get_pipeline_job_use_case(
    pipeline_jobs: PipelineJobRepositoryDep,
) -> GetPipelineJobUseCase:
    return GetPipelineJobUseCase(pipeline_jobs)


def get_retry_pipeline_job_use_case(
    pipeline_jobs: PipelineJobRepositoryDep,
    client: YouTubeDataClientDep,
    streamers: StreamerRepositoryDep,
) -> RetryPipelineJobUseCase:
    return RetryPipelineJobUseCase(
        pipeline_jobs,
        ResolveYouTubeChannelUseCase(client, streamers, pipeline_jobs),
    )


RetryPipelineJobUseCaseDep = Annotated[
    RetryPipelineJobUseCase,
    Depends(get_retry_pipeline_job_use_case),
]
ListPipelineJobsUseCaseDep = Annotated[
    ListPipelineJobsUseCase,
    Depends(get_list_pipeline_jobs_use_case),
]
GetPipelineJobUseCaseDep = Annotated[
    GetPipelineJobUseCase,
    Depends(get_pipeline_job_use_case),
]
