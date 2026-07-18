from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PublicationDeliveryStatus:
    id: int
    object_binding_id: int
    destination_id: int
    destination_key: str
    destination_name: str
    required: bool
    status: str
    index_public_url: str | None
    pointer_public_url: str | None
    error_code: str | None
    error_message: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PublicationStatus:
    id: int
    profile_id: int
    profile_key: str
    profile_name: str
    profile_revision_id: int
    route_id: int
    publish_mode: str
    environment: str
    schema_version: int
    version: str
    status: str
    video_count: int
    artifact_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    deliveries: tuple[PublicationDeliveryStatus, ...]


@dataclass(frozen=True, slots=True)
class PublicationStatusQuery:
    streamer_id: int | None = None
    profile_id: int | None = None
    publish_mode: str | None = None
    environment: str | None = None
    status: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class PublicationStatusList:
    items: tuple[PublicationStatus, ...]
    total: int
    limit: int
    offset: int


class PublicationStatusRepositoryPort(Protocol):
    async def list_publications(
        self,
        query: PublicationStatusQuery,
    ) -> PublicationStatusList: ...


class ListPublicationStatusesUseCase:
    def __init__(self, repository: PublicationStatusRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, query: PublicationStatusQuery) -> PublicationStatusList:
        return await self._repository.list_publications(query)
