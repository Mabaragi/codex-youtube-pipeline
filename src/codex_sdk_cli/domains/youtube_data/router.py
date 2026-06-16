from __future__ import annotations

from fastapi import APIRouter, status

from .dependencies import ResolveYouTubeChannelUseCaseDep
from .schemas import ResolveYouTubeChannelRequest, ResolveYouTubeChannelResponse

router = APIRouter()


@router.post(
    "/channels/resolve",
    response_model=ResolveYouTubeChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def resolve_youtube_channel(
    request: ResolveYouTubeChannelRequest,
    use_case: ResolveYouTubeChannelUseCaseDep,
) -> ResolveYouTubeChannelResponse:
    return await use_case.execute(request)
