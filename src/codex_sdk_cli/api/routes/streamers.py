from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from codex_sdk_cli.api.use_case_dependencies.streamers import (
    CreateStreamerUseCaseDep,
    DeleteStreamerUseCaseDep,
    GetStreamerUseCaseDep,
    ListStreamersUseCaseDep,
    UpdateStreamerUseCaseDep,
)
from codex_sdk_cli.domains.streamers.schemas import (
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
