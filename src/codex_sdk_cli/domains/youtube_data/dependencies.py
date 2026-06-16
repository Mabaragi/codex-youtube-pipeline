from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    PipelineJobRepositoryDep,
    StreamerRepositoryDep,
    YouTubeDataClientDep,
)

from .use_cases import ResolveYouTubeChannelUseCase


def get_resolve_youtube_channel_use_case(
    client: YouTubeDataClientDep,
    repository: StreamerRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
) -> ResolveYouTubeChannelUseCase:
    return ResolveYouTubeChannelUseCase(client, repository, pipeline_jobs)


ResolveYouTubeChannelUseCaseDep = Annotated[
    ResolveYouTubeChannelUseCase,
    Depends(get_resolve_youtube_channel_use_case),
]
