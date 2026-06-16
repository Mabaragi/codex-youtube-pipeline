from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ChannelRepositoryDep,
    PipelineJobRepositoryDep,
    StreamerRepositoryDep,
    VideoRepositoryDep,
    YouTubeDataClientDep,
)
from codex_sdk_cli.domains.channels.use_cases import ResolveYouTubeChannelUseCase
from codex_sdk_cli.domains.videos.use_cases import (
    VIDEO_COLLECT_STEP,
    CollectChannelVideosUseCase,
)

from .use_cases import (
    CHANNEL_RESOLVE_STEP,
    ChannelResolveRetryExecutor,
    GetPipelineJobUseCase,
    ListPipelineJobsUseCase,
    RetryPipelineJobUseCase,
    VideoCollectRetryExecutor,
)


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
    channels: ChannelRepositoryDep,
    streamers: StreamerRepositoryDep,
    videos: VideoRepositoryDep,
) -> RetryPipelineJobUseCase:
    return RetryPipelineJobUseCase(
        pipeline_jobs,
        {
            CHANNEL_RESOLVE_STEP: ChannelResolveRetryExecutor(
                ResolveYouTubeChannelUseCase(client, channels, streamers, pipeline_jobs)
            ),
            VIDEO_COLLECT_STEP: VideoCollectRetryExecutor(
                CollectChannelVideosUseCase(client, channels, videos, pipeline_jobs)
            ),
        },
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
