from __future__ import annotations

from .exceptions import ChannelNotFound, StreamerNotFound
from .ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelUpdate,
    StreamerRecord,
    StreamerRepositoryPort,
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


class CreateStreamerUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, request: StreamerCreateRequest) -> StreamerResponse:
        return _streamer_response(await self._repository.create_streamer(name=request.name))


class ListStreamersUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self) -> list[StreamerResponse]:
        return [_streamer_response(record) for record in await self._repository.list_streamers()]


class GetStreamerUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, streamer_id: int) -> StreamerResponse:
        record = await self._repository.get_streamer(streamer_id)
        if record is None:
            raise StreamerNotFound("Streamer not found.")
        return _streamer_response(record)


class UpdateStreamerUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, streamer_id: int, request: StreamerUpdateRequest) -> StreamerResponse:
        assert request.name is not None
        record = await self._repository.update_streamer(streamer_id, name=request.name)
        if record is None:
            raise StreamerNotFound("Streamer not found.")
        return _streamer_response(record)


class DeleteStreamerUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, streamer_id: int) -> DeleteResponse:
        deleted = await self._repository.delete_streamer(streamer_id)
        if not deleted:
            raise StreamerNotFound("Streamer not found.")
        return DeleteResponse(success=True)


class CreateChannelUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, request: ChannelCreateRequest) -> ChannelResponse:
        await _ensure_streamer_exists(self._repository, request.streamer_id)
        record = await self._repository.create_channel(
            ChannelCreate(
                streamer_id=request.streamer_id,
                handle=request.handle,
                name=request.name,
                youtube_channel_id=request.youtube_channel_id,
            )
        )
        return _channel_response(record)


class ListChannelsUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, *, streamer_id: int | None = None) -> list[ChannelResponse]:
        records = await self._repository.list_channels(streamer_id=streamer_id)
        return [_channel_response(record) for record in records]


class GetChannelUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, channel_id: int) -> ChannelResponse:
        record = await self._repository.get_channel(channel_id)
        if record is None:
            raise ChannelNotFound("Channel not found.")
        return _channel_response(record)


class UpdateChannelUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, channel_id: int, request: ChannelUpdateRequest) -> ChannelResponse:
        fields_set = request.model_fields_set
        if request.streamer_id is not None:
            await _ensure_streamer_exists(self._repository, request.streamer_id)
        update = ChannelUpdate(
            streamer_id=request.streamer_id if "streamer_id" in fields_set else None,
            handle=request.handle if "handle" in fields_set else None,
            name=request.name if "name" in fields_set else None,
            youtube_channel_id=request.youtube_channel_id,
            youtube_channel_id_set="youtube_channel_id" in fields_set,
        )
        record = await self._repository.update_channel(channel_id, update)
        if record is None:
            raise ChannelNotFound("Channel not found.")
        return _channel_response(record)


class DeleteChannelUseCase:
    def __init__(self, repository: StreamerRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, channel_id: int) -> DeleteResponse:
        deleted = await self._repository.delete_channel(channel_id)
        if not deleted:
            raise ChannelNotFound("Channel not found.")
        return DeleteResponse(success=True)


async def _ensure_streamer_exists(repository: StreamerRepositoryPort, streamer_id: int) -> None:
    if await repository.get_streamer(streamer_id) is None:
        raise StreamerNotFound("Streamer not found.")


def _streamer_response(record: StreamerRecord) -> StreamerResponse:
    return StreamerResponse(id=record.id, name=record.name)


def _channel_response(record: ChannelRecord) -> ChannelResponse:
    return ChannelResponse(
        id=record.id,
        streamerId=record.streamer_id,
        handle=record.handle,
        name=record.name,
        youtubeChannelId=record.youtube_channel_id,
        sourceApiCallId=record.source_api_call_id,
        sourceJobId=record.source_job_id,
    )
