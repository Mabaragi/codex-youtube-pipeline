from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from codex_sdk_cli.api.use_case_dependencies.videos import (
    CollectAllChannelsVideosUseCaseDep,
    CollectChannelVideosUseCaseDep,
    ListChannelVideosUseCaseDep,
)
from codex_sdk_cli.domains.videos.schemas import (
    CollectAllChannelsVideosResponse,
    CollectChannelVideosResponse,
    VideoResponse,
)

router = APIRouter()


@router.post(
    "/channels/videos/collect",
    response_model=CollectAllChannelsVideosResponse,
    status_code=status.HTTP_200_OK,
)
async def collect_all_channels_videos(
    use_case: CollectAllChannelsVideosUseCaseDep,
) -> CollectAllChannelsVideosResponse:
    return await use_case.execute()


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
