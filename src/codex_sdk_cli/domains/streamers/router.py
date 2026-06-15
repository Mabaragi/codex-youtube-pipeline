from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from .dependencies import (
    CreateChannelUseCaseDep,
    CreateStreamerUseCaseDep,
    DeleteChannelUseCaseDep,
    DeleteStreamerUseCaseDep,
    GetChannelUseCaseDep,
    GetStreamerUseCaseDep,
    ListChannelsUseCaseDep,
    ListStreamersUseCaseDep,
    UpdateChannelUseCaseDep,
    UpdateStreamerUseCaseDep,
)
from .schemas import (
    ChannelCreateRequest,
    ChannelResponse,
    ChannelUpdateRequest,
    DeleteResponse,
    StreamerCreateRequest,
    StreamerResponse,
    StreamerUpdateRequest,
)

router = APIRouter()


@router.post(
    "/streamers",
    response_model=StreamerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_streamer(
    request: StreamerCreateRequest,
    use_case: CreateStreamerUseCaseDep,
) -> StreamerResponse:
    return await use_case.execute(request)


@router.get("/streamers", response_model=list[StreamerResponse])
async def list_streamers(use_case: ListStreamersUseCaseDep) -> list[StreamerResponse]:
    return await use_case.execute()


@router.get("/streamers/{streamer_id}", response_model=StreamerResponse)
async def get_streamer(
    streamer_id: Annotated[int, Path(ge=1)],
    use_case: GetStreamerUseCaseDep,
) -> StreamerResponse:
    return await use_case.execute(streamer_id)


@router.patch("/streamers/{streamer_id}", response_model=StreamerResponse)
async def update_streamer(
    streamer_id: Annotated[int, Path(ge=1)],
    request: StreamerUpdateRequest,
    use_case: UpdateStreamerUseCaseDep,
) -> StreamerResponse:
    return await use_case.execute(streamer_id, request)


@router.delete("/streamers/{streamer_id}", response_model=DeleteResponse)
async def delete_streamer(
    streamer_id: Annotated[int, Path(ge=1)],
    use_case: DeleteStreamerUseCaseDep,
) -> DeleteResponse:
    return await use_case.execute(streamer_id)


@router.post(
    "/channels",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    request: ChannelCreateRequest,
    use_case: CreateChannelUseCaseDep,
) -> ChannelResponse:
    return await use_case.execute(request)


@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(
    use_case: ListChannelsUseCaseDep,
    streamer_id: Annotated[int | None, Query(alias="streamerId", ge=1)] = None,
) -> list[ChannelResponse]:
    return await use_case.execute(streamer_id=streamer_id)


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

