from __future__ import annotations

from fastapi import APIRouter

from .dependencies import ResolveYouTubeChannelUseCaseDep
from .schemas import ResolveYouTubeChannelRequest, ResolveYouTubeChannelResponse

router = APIRouter()


@router.post("/channels/resolve", response_model=ResolveYouTubeChannelResponse)
async def resolve_youtube_channel(
    request: ResolveYouTubeChannelRequest,
    use_case: ResolveYouTubeChannelUseCaseDep,
) -> ResolveYouTubeChannelResponse:
    return await use_case.execute(request)

