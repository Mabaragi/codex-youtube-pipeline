from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from codex_sdk_cli.api.use_case_dependencies.channels import (
    CreateChannelUseCaseDep,
    DeleteChannelUseCaseDep,
    ListStreamerChannelsUseCaseDep,
    UpdateChannelUseCaseDep,
)
from codex_sdk_cli.domains.channels.schemas import (
    ChannelCreateRequest,
    ChannelResponse,
    ChannelUpdateRequest,
    DeleteResponse,
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
