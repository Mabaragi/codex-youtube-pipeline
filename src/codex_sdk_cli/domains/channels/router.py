from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from .dependencies import (
    CreateChannelUseCaseDep,
    DeleteChannelUseCaseDep,
    GetChannelUseCaseDep,
    ListChannelsUseCaseDep,
    ListStreamerChannelsUseCaseDep,
    ResolveYouTubeChannelUseCaseDep,
    UpdateChannelUseCaseDep,
)
from .schemas import (
    ChannelCreateRequest,
    ChannelResponse,
    ChannelUpdateRequest,
    DeleteResponse,
    ResolveYouTubeChannelRequest,
    ResolveYouTubeChannelResponse,
)

router = APIRouter()


@router.post(
    "/streamers/{streamer_id}/channels",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_streamer_channel(
    streamer_id: Annotated[int, Path(ge=1)],
    request: ChannelCreateRequest,
    use_case: CreateChannelUseCaseDep,
) -> ChannelResponse:
    return await use_case.execute(streamer_id, request)


@router.get("/streamers/{streamer_id}/channels", response_model=list[ChannelResponse])
async def list_streamer_channels(
    streamer_id: Annotated[int, Path(ge=1)],
    use_case: ListStreamerChannelsUseCaseDep,
) -> list[ChannelResponse]:
    return await use_case.execute(streamer_id)


@router.post(
    "/streamers/{streamer_id}/channels/resolve",
    response_model=ResolveYouTubeChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def resolve_streamer_channel(
    streamer_id: Annotated[int, Path(ge=1)],
    request: ResolveYouTubeChannelRequest,
    use_case: ResolveYouTubeChannelUseCaseDep,
) -> ResolveYouTubeChannelResponse:
    return await use_case.execute(streamer_id, request)


@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(use_case: ListChannelsUseCaseDep) -> list[ChannelResponse]:
    return await use_case.execute()


@router.get("/channels/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: Annotated[int, Path(ge=1)],
    use_case: GetChannelUseCaseDep,
) -> ChannelResponse:
    return await use_case.execute(channel_id)


@router.patch("/channels/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: Annotated[int, Path(ge=1)],
    request: ChannelUpdateRequest,
    use_case: UpdateChannelUseCaseDep,
) -> ChannelResponse:
    return await use_case.execute(channel_id, request)


@router.delete("/channels/{channel_id}", response_model=DeleteResponse)
async def delete_channel(
    channel_id: Annotated[int, Path(ge=1)],
    use_case: DeleteChannelUseCaseDep,
) -> DeleteResponse:
    return await use_case.execute(channel_id)
