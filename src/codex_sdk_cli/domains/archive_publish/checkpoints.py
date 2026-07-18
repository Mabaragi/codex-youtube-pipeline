from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from .ports import ArchiveVideoArtifactRecord

CheckpointStatus = Literal["pending", "running", "succeeded", "failed", "unavailable"]
PublicationStatus = Literal[
    "building",
    "ready",
    "partially_published",
    "published",
    "failed",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class ObjectDeliveryUpsert:
    artifact_id: int
    profile_revision_id: int
    route_id: int
    object_binding_id: int
    destination_id: int
    required: bool
    object_key: str
    public_url: str
    sha256: str
    byte_size: int
    status: CheckpointStatus
    work_item_id: int | None = None
    work_attempt_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectDeliveryRecord(ObjectDeliveryUpsert):
    id: int = 0
    attempt_count: int = 0
    succeeded_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CatalogDeliveryUpsert:
    artifact_id: int
    profile_revision_id: int
    route_id: int
    catalog_binding_id: int
    destination_id: int
    source_object_delivery_id: int
    required: bool
    status: CheckpointStatus
    work_item_id: int | None = None
    work_attempt_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogDeliveryRecord(CatalogDeliveryUpsert):
    id: int = 0
    attempt_count: int = 0
    succeeded_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ArtifactPublishProfileAssignment:
    artifact_id: int
    streamer_id: int
    publish_profile_id: int


@dataclass(frozen=True, slots=True)
class PublicationUpsert:
    profile_revision_id: int
    route_id: int
    schema_version: int
    version: str
    membership_sha256: str
    identity_key: str
    status: PublicationStatus
    video_count: int
    artifact_count: int
    work_item_id: int | None = None
    work_attempt_id: int | None = None
    legacy_index_publication_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationRecord(PublicationUpsert):
    id: int = 0
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PublicationDeliveryUpsert:
    publication_id: int
    object_binding_id: int
    destination_id: int
    required: bool
    status: PublicationStatus
    index_staging_key: str | None = None
    index_object_key: str | None = None
    index_public_url: str | None = None
    index_sha256: str | None = None
    index_byte_size: int | None = None
    index_succeeded_at: datetime | None = None
    pointer_staging_key: str | None = None
    pointer_object_key: str | None = None
    pointer_public_url: str | None = None
    pointer_sha256: str | None = None
    pointer_byte_size: int | None = None
    pointer_succeeded_at: datetime | None = None
    work_item_id: int | None = None
    work_attempt_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationDeliveryRecord(PublicationDeliveryUpsert):
    id: int = 0
    attempt_count: int = 0
    updated_at: datetime | None = None


class ArchivePublicationCheckpointPort(Protocol):
    async def get_artifacts(
        self, artifact_ids: tuple[int, ...]
    ) -> list[ArchiveVideoArtifactRecord]: ...

    async def get_artifact_publish_profile_assignments(
        self, artifact_ids: tuple[int, ...]
    ) -> tuple[ArtifactPublishProfileAssignment, ...]: ...

    async def set_artifact_canonical(
        self,
        *,
        artifact_id: int,
        build_key: str,
        store_ref: str,
        artifact_key: str,
    ) -> None: ...

    async def set_artifact_unavailable(
        self,
        *,
        artifact_id: int,
        code: str,
        detail: str,
    ) -> None: ...

    async def set_artifact_failed(
        self,
        *,
        artifact_id: int,
        code: str,
        detail: str,
    ) -> None: ...

    async def get_object_delivery(
        self, *, artifact_id: int, object_binding_id: int
    ) -> ObjectDeliveryRecord | None: ...

    async def upsert_object_delivery(
        self, delivery: ObjectDeliveryUpsert
    ) -> ObjectDeliveryRecord: ...

    async def get_catalog_delivery(
        self, *, artifact_id: int, catalog_binding_id: int
    ) -> CatalogDeliveryRecord | None: ...

    async def upsert_catalog_delivery(
        self, delivery: CatalogDeliveryUpsert
    ) -> CatalogDeliveryRecord: ...

    async def create_or_get_publication(
        self,
        publication: PublicationUpsert,
        *,
        artifact_ids: tuple[int, ...],
    ) -> PublicationRecord: ...

    async def list_publication_artifact_ids(self, publication_id: int) -> tuple[int, ...]: ...

    async def get_publication(self, publication_id: int) -> PublicationRecord | None: ...

    async def upsert_publication_delivery(
        self, delivery: PublicationDeliveryUpsert
    ) -> PublicationDeliveryRecord: ...

    async def list_publication_deliveries(
        self, publication_id: int
    ) -> tuple[PublicationDeliveryRecord, ...]: ...

    async def set_publication_status(
        self,
        publication_id: int,
        *,
        status: PublicationStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    async def has_newer_pointer_delivery(
        self,
        *,
        route_id: int,
        schema_version: int,
        object_binding_id: int,
        publication_id: int,
    ) -> bool: ...

    def pointer_lock(
        self,
        *,
        route_id: int,
        schema_version: int,
    ) -> AbstractAsyncContextManager[None]: ...
