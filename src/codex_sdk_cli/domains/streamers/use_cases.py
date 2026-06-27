from __future__ import annotations

from .exceptions import StreamerNotFound
from .ports import StreamerRecord, StreamerRepositoryPort
from .schemas import (
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


def _streamer_response(record: StreamerRecord) -> StreamerResponse:
    return StreamerResponse(id=record.id, name=record.name)
