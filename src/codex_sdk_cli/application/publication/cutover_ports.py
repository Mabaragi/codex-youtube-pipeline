from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

PublicationCutoverStatus = Literal[
    "preparing",
    "prepared",
    "target_pointer_published",
    "streamer_assigned",
    "source_ready",
    "completed",
    "failed",
]
PublicationCutoverStep = Literal[
    "target_prepare",
    "target_pointer",
    "streamer_assignment",
    "source_rebuild",
    "source_pointer",
]


@dataclass(frozen=True, slots=True)
class PublicationCutoverCreate:
    request_key: str
    streamer_id: int
    source_profile_id: int
    target_profile_id: int
    source_profile_revision_id: int
    target_profile_revision_id: int
    source_route_id: int
    target_route_id: int
    publish_mode: str
    environment: str
    schema_version: int
    artifact_ids: tuple[int, ...]
    operator_reason: str


@dataclass(frozen=True, slots=True)
class PublicationCutoverRecord(PublicationCutoverCreate):
    id: int
    status: PublicationCutoverStatus
    last_completed_step: PublicationCutoverStep | None
    target_publication_id: int | None
    source_publication_id: int | None
    target_pointer_published_at: datetime | None
    streamer_assigned_at: datetime | None
    source_pointer_published_at: datetime | None
    last_error_step: PublicationCutoverStep | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PublicationCutoverAdvance:
    status: PublicationCutoverStatus
    last_completed_step: PublicationCutoverStep | None = None
    target_publication_id: int | None = None
    source_publication_id: int | None = None
    target_pointer_published_at: datetime | None = None
    streamer_assigned_at: datetime | None = None
    source_pointer_published_at: datetime | None = None
    clear_error: bool = True


class PublicationCutoverRepositoryPort(Protocol):
    async def create_or_get(
        self,
        create: PublicationCutoverCreate,
    ) -> PublicationCutoverRecord: ...

    async def get(self, cutover_id: int) -> PublicationCutoverRecord | None: ...

    async def list(self, *, limit: int = 100) -> list[PublicationCutoverRecord]: ...

    async def find_open(
        self,
        *,
        streamer_id: int,
        publish_mode: str,
        environment: str,
    ) -> PublicationCutoverRecord | None: ...

    async def advance(
        self,
        cutover_id: int,
        advance: PublicationCutoverAdvance,
    ) -> PublicationCutoverRecord: ...

    async def mark_failed(
        self,
        cutover_id: int,
        *,
        step: PublicationCutoverStep,
        error_code: str,
        error_message: str,
    ) -> PublicationCutoverRecord: ...
