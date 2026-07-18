from __future__ import annotations

from .exceptions import (
    StreamerNotFound,
    StreamerPublishProfileCutoverRequired,
    StreamerPublishProfileUnavailable,
)
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
        await _require_active_profile(self._repository, request.publish_profile_id)
        return _streamer_response(
            await self._repository.create_streamer(
                name=request.name,
                publish_profile_id=request.publish_profile_id,
            )
        )


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
        current = await self._repository.get_streamer(streamer_id)
        if current is None:
            raise StreamerNotFound("Streamer not found.")
        if request.publish_profile_id is not None:
            await _require_active_profile(self._repository, request.publish_profile_id)
            if (
                request.publish_profile_id != current.publish_profile_id
                and await self._repository.has_archive_artifacts(streamer_id)
            ):
                raise StreamerPublishProfileCutoverRequired(
                    "Published streamers must change publish profiles through a cutover."
                )
        record = await self._repository.update_streamer(
            streamer_id,
            name=request.name,
            publish_profile_id=request.publish_profile_id,
        )
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
    return StreamerResponse(
        id=record.id,
        name=record.name,
        publishProfileId=record.publish_profile_id,
    )


async def _require_active_profile(
    repository: StreamerRepositoryPort,
    publish_profile_id: int,
) -> None:
    if not await repository.is_publish_profile_active(publish_profile_id):
        raise StreamerPublishProfileUnavailable(
            "Publish profile does not exist or has no active revision."
        )
