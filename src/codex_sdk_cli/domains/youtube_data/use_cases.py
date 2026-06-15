from __future__ import annotations

from codex_sdk_cli.domains.streamers.ports import StreamerRepositoryPort

from .exceptions import InvalidYouTubeChannelHandle
from .ports import YouTubeDataClientPort
from .schemas import ResolveYouTubeChannelRequest, ResolveYouTubeChannelResponse


class ResolveYouTubeChannelUseCase:
    def __init__(
        self,
        client: YouTubeDataClientPort,
        repository: StreamerRepositoryPort,
    ) -> None:
        self._client = client
        self._repository = repository

    async def execute(
        self,
        request: ResolveYouTubeChannelRequest,
    ) -> ResolveYouTubeChannelResponse:
        handle = _normalize_request_handle(request.handle)
        result = await self._client.resolve_channel_id_by_handle(handle)
        updated_channels = await self._repository.update_youtube_channel_id_by_handle(
            handle=handle,
            youtube_channel_id=result.youtube_channel_id,
        )
        return ResolveYouTubeChannelResponse(
            handle=handle,
            youtubeChannelId=result.youtube_channel_id,
            updatedChannelIds=sorted(channel.id for channel in updated_channels),
        )


def _normalize_request_handle(handle: str) -> str:
    normalized = handle.strip()
    if not normalized.removeprefix("@").strip():
        raise InvalidYouTubeChannelHandle("YouTube channel handle cannot be empty.")
    return normalized

