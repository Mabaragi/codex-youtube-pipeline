from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from codex_sdk_cli.domains.archive_publish.ports import ArchivePublicCatalogVideoRow


@dataclass(frozen=True, slots=True)
class PublicationObjectLocation:
    bucket: str
    object_key: str
    public_url: str
    etag: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationObjectStat:
    bucket: str
    object_key: str
    byte_size: int
    etag: str | None
    last_modified: datetime | None


class PublicationObjectStorePort(Protocol):
    def public_url(self, object_key: str) -> str:
        """Return the configured destination URL without performing I/O."""

    async def put_bytes(
        self,
        *,
        object_key: str,
        payload: bytes,
        content_type: str = "application/octet-stream",
        cache_control: str | None = None,
    ) -> PublicationObjectLocation:
        """Write bytes and return their destination-specific public location."""

    async def get_bytes(self, *, object_key: str) -> bytes:
        """Read an immutable object for verification or migration."""

    async def stat_object(self, *, object_key: str) -> PublicationObjectStat | None:
        """Return object metadata, or None when the key does not exist."""


@dataclass(frozen=True, slots=True)
class PublicationCatalogContext:
    profile_key: str
    publish_mode: str


@dataclass(frozen=True, slots=True)
class PublicationCatalogVideoKey:
    video_id: int
    variant: str


class PublicationCatalogPublisherPort(Protocol):
    async def upsert_video(
        self,
        context: PublicationCatalogContext,
        row: ArchivePublicCatalogVideoRow,
    ) -> None:
        """Replace one destination-scoped public catalog projection atomically."""


class PublicationCatalogReconcilerPort(Protocol):
    async def reconcile_videos(
        self,
        context: PublicationCatalogContext,
        *,
        environment: str,
        retained: tuple[PublicationCatalogVideoKey, ...],
    ) -> None:
        """Remove projections outside the complete retained membership snapshot."""


@dataclass(frozen=True, slots=True)
class PublicationCatalogRowVerification:
    exists: bool
    matches: bool
    detail: str | None = None


class PublicationCatalogVerifierPort(Protocol):
    async def verify_video(
        self,
        context: PublicationCatalogContext,
        row: ArchivePublicCatalogVideoRow,
    ) -> PublicationCatalogRowVerification:
        """Verify one destination-scoped video projection and all child rows."""
