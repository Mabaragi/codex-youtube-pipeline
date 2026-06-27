from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from codex_sdk_cli.api.use_case_dependencies.videos import (
    CollectChannelVideosUseCaseDep,
    ListChannelVideosUseCaseDep,
)
from codex_sdk_cli.domains.videos.schemas import CollectChannelVideosResponse, VideoResponse

router = APIRouter()


@router.get("/channels/{channel_id}/videos", response_model=list[VideoResponse])
async def list_channel_videos(
    channel_id: Annotated[int, Path(ge=1)],
    use_case: ListChannelVideosUseCaseDep,
) -> list[VideoResponse]:
    return await use_case.execute(channel_id)


@router.post(
    "/channels/{channel_id}/videos/collect",
    response_model=CollectChannelVideosResponse,
    status_code=status.HTTP_201_CREATED,
)
async def collect_channel_videos(
    channel_id: Annotated[int, Path(ge=1)],
    use_case: CollectChannelVideosUseCaseDep,
) -> CollectChannelVideosResponse:
    return await use_case.execute(channel_id)
