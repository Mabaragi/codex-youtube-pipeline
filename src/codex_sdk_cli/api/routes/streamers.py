from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from codex_sdk_cli.api.operator_context import OperatorReason
from codex_sdk_cli.api.use_case_dependencies.operation_events import (
    RecordOperatorMutationUseCaseDep,
)
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
    reason: OperatorReason,
    use_case: CreateStreamerUseCaseDep,
    audit: RecordOperatorMutationUseCaseDep,
) -> StreamerResponse:
    response = await use_case.execute(request)
    await audit.execute(
        mutation="created",
        target_type="streamer",
        target_id=response.id,
        action="create",
        reason=reason,
        metadata={"publishProfileId": response.publish_profile_id},
    )
    return response


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
    reason: OperatorReason,
    use_case: UpdateStreamerUseCaseDep,
    audit: RecordOperatorMutationUseCaseDep,
) -> StreamerResponse:
    response = await use_case.execute(streamer_id, request)
    await audit.execute(
        mutation="updated",
        target_type="streamer",
        target_id=streamer_id,
        action="update",
        reason=reason,
        metadata={
            "publishProfileId": response.publish_profile_id,
            "publishProfileChanged": request.publish_profile_id is not None,
        },
    )
    return response


@router.delete("/streamers/{streamer_id}", response_model=DeleteResponse)
async def delete_streamer(
    streamer_id: Annotated[int, Path(ge=1)],
    reason: OperatorReason,
    use_case: DeleteStreamerUseCaseDep,
    audit: RecordOperatorMutationUseCaseDep,
) -> DeleteResponse:
    response = await use_case.execute(streamer_id)
    await audit.execute(
        mutation="deleted",
        target_type="streamer",
        target_id=streamer_id,
        action="delete",
        reason=reason,
    )
    return response
