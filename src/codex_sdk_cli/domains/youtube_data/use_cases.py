from __future__ import annotations

from codex_sdk_cli.domains.streamers.exceptions import StreamerNotFound
from codex_sdk_cli.domains.streamers.ports import (
    ChannelCreate,
    ChannelRecord,
    StreamerRepositoryPort,
)

from .exceptions import InvalidYouTubeChannelHandle, YouTubeDataChannelIdentityMismatch
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
        if await self._repository.get_streamer(request.streamer_id) is None:
            raise StreamerNotFound("Streamer not found.")

        result = await self._client.resolve_youtube_channel_by_handle(handle)
        if (
            request.youtube_channel_id is not None
            and request.youtube_channel_id != result.youtube_channel_id
        ):
            raise YouTubeDataChannelIdentityMismatch(
                "Resolved YouTube channel ID did not match the request."
            )

        record = await self._repository.create_channel(
            ChannelCreate(
                streamer_id=request.streamer_id,
                handle=handle,
                name=result.title,
                youtube_channel_id=result.youtube_channel_id,
                source_api_call_id=result.source_api_call_id,
            )
        )
        return _response(record)


def _normalize_request_handle(handle: str) -> str:
    normalized = handle.strip()
    if not normalized.removeprefix("@").strip():
        raise InvalidYouTubeChannelHandle("YouTube channel handle cannot be empty.")
    return normalized


def _response(record: ChannelRecord) -> ResolveYouTubeChannelResponse:
    if record.youtube_channel_id is None:
        raise YouTubeDataChannelIdentityMismatch(
            "Created channel row did not include a YouTube channel ID."
        )
    if record.source_api_call_id is None:
        raise YouTubeDataChannelIdentityMismatch(
            "Created channel row did not include a source API call ID."
        )
    return ResolveYouTubeChannelResponse(
        channelId=record.id,
        streamerId=record.streamer_id,
        handle=record.handle,
        name=record.name,
        youtubeChannelId=record.youtube_channel_id,
        sourceApiCallId=record.source_api_call_id,
    )
