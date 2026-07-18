from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codex_sdk_cli.domains.publication_config.connections import PublicationConnectionKind
from codex_sdk_cli.domains.publication_config.models import (
    PublishCatalogDestination,
    PublishMode,
    PublishObjectDestination,
    PublishProfile,
    PublishProfileDetail,
    PublishProfileRevision,
)


class PublicationConnectionRegistryPort(Protocol):
    def connection_kind(
        self,
        connection_ref: str,
    ) -> PublicationConnectionKind | None:
        """Resolve a safe registry identifier without exposing connection material."""


@dataclass(frozen=True, slots=True)
class CreateObjectDestination:
    key: str
    name: str
    connection_ref: str


@dataclass(frozen=True, slots=True)
class CreateCatalogDestination:
    key: str
    name: str
    connection_ref: str


@dataclass(frozen=True, slots=True)
class CreatePublishProfile:
    key: str
    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class CreateRouteObjectBinding:
    destination_id: int
    key_prefix: str
    required: bool
    is_primary: bool


@dataclass(frozen=True, slots=True)
class CreateRouteCatalogBinding:
    destination_id: int
    source_object_destination_id: int
    required: bool


@dataclass(frozen=True, slots=True)
class CreatePublishProfileRoute:
    publish_mode: PublishMode
    environment: str
    object_bindings: tuple[CreateRouteObjectBinding, ...]
    catalog_bindings: tuple[CreateRouteCatalogBinding, ...]


@dataclass(frozen=True, slots=True)
class CreatePublishProfileRevision:
    profile_id: int
    routes: tuple[CreatePublishProfileRoute, ...]


@dataclass(frozen=True, slots=True)
class ResolvedObjectBinding:
    id: int
    destination_id: int
    connection_ref: str
    key_prefix: str
    required: bool
    is_primary: bool


@dataclass(frozen=True, slots=True)
class ResolvedCatalogBinding:
    id: int
    destination_id: int
    connection_ref: str
    source_object_binding_id: int
    required: bool


@dataclass(frozen=True, slots=True)
class ResolvedPublishRoute:
    profile_id: int
    profile_key: str
    profile_revision_id: int
    revision_number: int
    route_id: int
    publish_mode: PublishMode
    environment: str
    object_bindings: tuple[ResolvedObjectBinding, ...]
    catalog_bindings: tuple[ResolvedCatalogBinding, ...]


class PublishConfigurationRepositoryPort(Protocol):
    async def create_object_destination(
        self,
        create: CreateObjectDestination,
    ) -> PublishObjectDestination:
        """Create an immutable physical object destination reference."""

    async def list_object_destinations(self) -> list[PublishObjectDestination]:
        """List object destinations."""

    async def create_catalog_destination(
        self,
        create: CreateCatalogDestination,
    ) -> PublishCatalogDestination:
        """Create an immutable physical catalog destination reference."""

    async def list_catalog_destinations(self) -> list[PublishCatalogDestination]:
        """List catalog destinations."""

    async def create_profile(self, create: CreatePublishProfile) -> PublishProfile:
        """Create a profile without an active revision."""

    async def list_profiles(self) -> list[PublishProfile]:
        """List profile summaries."""

    async def get_profile(self, profile_id: int) -> PublishProfileDetail | None:
        """Return a complete profile and all immutable revisions."""

    async def create_revision(
        self,
        create: CreatePublishProfileRevision,
    ) -> PublishProfileRevision | None:
        """Create a complete immutable draft revision."""

    async def activate_revision(
        self,
        *,
        profile_id: int,
        revision_id: int,
    ) -> PublishProfileRevision | None:
        """Atomically activate a draft revision and retire the previous revision."""

    async def is_profile_active(self, profile_id: int) -> bool:
        """Return whether the profile has an active revision."""

    async def resolve_active_route(
        self,
        *,
        streamer_id: int,
        publish_mode: PublishMode,
        environment: str,
    ) -> ResolvedPublishRoute | None:
        """Resolve the active immutable route snapshot assigned to a streamer."""

    async def resolve_revision_route(
        self,
        *,
        profile_revision_id: int,
        publish_mode: PublishMode,
        environment: str,
    ) -> ResolvedPublishRoute | None:
        """Resolve a route from an explicitly snapshotted immutable revision."""

    async def get_route(self, route_id: int) -> ResolvedPublishRoute | None:
        """Resolve an immutable route snapshot by its persisted route identifier."""
