from __future__ import annotations

from codex_sdk_cli.domains.publication_config.connections import (
    PublicationConnectionKind,
    is_safe_connection_ref,
)
from codex_sdk_cli.domains.publication_config.exceptions import (
    PublishConfigurationConflict,
    PublishConfigurationInvalidConnection,
    PublishConfigurationNotFound,
)
from codex_sdk_cli.domains.publication_config.models import (
    PublishCatalogDestination,
    PublishObjectDestination,
    PublishProfile,
    PublishProfileDetail,
    PublishProfileRevision,
)

from .ports import (
    CreateCatalogDestination,
    CreateObjectDestination,
    CreatePublishProfile,
    CreatePublishProfileRevision,
    CreatePublishProfileRoute,
    PublicationConnectionRegistryPort,
    PublishConfigurationRepositoryPort,
)


class CreateObjectDestinationUseCase:
    def __init__(
        self,
        repository: PublishConfigurationRepositoryPort,
        connections: PublicationConnectionRegistryPort,
    ) -> None:
        self._repository = repository
        self._connections = connections

    async def execute(self, create: CreateObjectDestination) -> PublishObjectDestination:
        _validate_destination_connection(
            create.connection_ref,
            registry=self._connections,
            allowed_kinds=frozenset({"s3_compatible_object"}),
            expected="s3_compatible_object",
        )
        return await self._repository.create_object_destination(create)


class ListObjectDestinationsUseCase:
    def __init__(self, repository: PublishConfigurationRepositoryPort) -> None:
        self._repository = repository

    async def execute(self) -> list[PublishObjectDestination]:
        return await self._repository.list_object_destinations()


class CreateCatalogDestinationUseCase:
    def __init__(
        self,
        repository: PublishConfigurationRepositoryPort,
        connections: PublicationConnectionRegistryPort,
    ) -> None:
        self._repository = repository
        self._connections = connections

    async def execute(self, create: CreateCatalogDestination) -> PublishCatalogDestination:
        _validate_destination_connection(
            create.connection_ref,
            registry=self._connections,
            allowed_kinds=frozenset({"sql_catalog", "http_catalog"}),
            expected="sql_catalog or http_catalog",
        )
        return await self._repository.create_catalog_destination(create)


class ListCatalogDestinationsUseCase:
    def __init__(self, repository: PublishConfigurationRepositoryPort) -> None:
        self._repository = repository

    async def execute(self) -> list[PublishCatalogDestination]:
        return await self._repository.list_catalog_destinations()


class CreatePublishProfileUseCase:
    def __init__(self, repository: PublishConfigurationRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, create: CreatePublishProfile) -> PublishProfile:
        return await self._repository.create_profile(create)


class ListPublishProfilesUseCase:
    def __init__(self, repository: PublishConfigurationRepositoryPort) -> None:
        self._repository = repository

    async def execute(self) -> list[PublishProfile]:
        return await self._repository.list_profiles()


class GetPublishProfileUseCase:
    def __init__(self, repository: PublishConfigurationRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, profile_id: int) -> PublishProfileDetail:
        profile = await self._repository.get_profile(profile_id)
        if profile is None:
            raise PublishConfigurationNotFound("Publish profile not found.")
        return profile


class CreatePublishProfileRevisionUseCase:
    def __init__(self, repository: PublishConfigurationRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        create: CreatePublishProfileRevision,
    ) -> PublishProfileRevision:
        _validate_revision(create)
        revision = await self._repository.create_revision(create)
        if revision is None:
            raise PublishConfigurationNotFound("Publish profile not found.")
        return revision


class ActivatePublishProfileRevisionUseCase:
    def __init__(self, repository: PublishConfigurationRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, *, profile_id: int, revision_id: int) -> PublishProfileRevision:
        revision = await self._repository.activate_revision(
            profile_id=profile_id,
            revision_id=revision_id,
        )
        if revision is None:
            raise PublishConfigurationNotFound("Publish profile revision not found.")
        return revision


def _validate_destination_connection(
    connection_ref: str,
    *,
    registry: PublicationConnectionRegistryPort,
    allowed_kinds: frozenset[PublicationConnectionKind],
    expected: str,
) -> None:
    if not is_safe_connection_ref(connection_ref):
        raise PublishConfigurationInvalidConnection(
            "connectionRef must be a safe publication connection registry identifier."
        )
    kind = registry.connection_kind(connection_ref)
    if kind is None:
        raise PublishConfigurationInvalidConnection(
            "connectionRef is not configured in the publication connection registry."
        )
    if kind not in allowed_kinds:
        raise PublishConfigurationInvalidConnection(
            f"connectionRef must reference a {expected} connection."
        )


def _validate_revision(create: CreatePublishProfileRevision) -> None:
    if not create.routes:
        raise PublishConfigurationConflict("A publish profile revision requires routes.")
    route_keys: set[tuple[str, str]] = set()
    for route in create.routes:
        route_key = (route.publish_mode, route.environment)
        if route_key in route_keys:
            raise PublishConfigurationConflict(
                "A revision cannot contain duplicate publish mode and environment routes."
            )
        route_keys.add(route_key)
        _validate_route(route)


def _validate_route(route: CreatePublishProfileRoute) -> None:
    if not route.object_bindings:
        raise PublishConfigurationConflict("A publish route requires object bindings.")
    object_destination_ids = [binding.destination_id for binding in route.object_bindings]
    if len(object_destination_ids) != len(set(object_destination_ids)):
        raise PublishConfigurationConflict(
            "A publish route cannot bind an object destination more than once."
        )
    if sum(binding.is_primary for binding in route.object_bindings) != 1:
        raise PublishConfigurationConflict(
            "A publish route requires exactly one primary object binding."
        )
    if any(not binding.key_prefix.strip("/") for binding in route.object_bindings):
        raise PublishConfigurationConflict(
            "A publish route object binding requires a non-empty key prefix."
        )
    catalog_destination_ids = [binding.destination_id for binding in route.catalog_bindings]
    if len(catalog_destination_ids) != len(set(catalog_destination_ids)):
        raise PublishConfigurationConflict(
            "A publish route cannot bind a catalog destination more than once."
        )
    if any(
        binding.source_object_destination_id not in object_destination_ids
        for binding in route.catalog_bindings
    ):
        raise PublishConfigurationConflict(
            "A catalog binding must reference an object destination in the same route."
        )
