from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import PublishConfigurationRepositoryDep
from codex_sdk_cli.api.use_case_dependencies.publication import (
    PublicationConnectionRegistryDep,
)
from codex_sdk_cli.application.publication_config.use_cases import (
    ActivatePublishProfileRevisionUseCase,
    CreateCatalogDestinationUseCase,
    CreateObjectDestinationUseCase,
    CreatePublishProfileRevisionUseCase,
    CreatePublishProfileUseCase,
    GetPublishProfileUseCase,
    ListCatalogDestinationsUseCase,
    ListObjectDestinationsUseCase,
    ListPublishProfilesUseCase,
)


def get_create_object_destination_use_case(
    repository: PublishConfigurationRepositoryDep,
    connections: PublicationConnectionRegistryDep,
) -> CreateObjectDestinationUseCase:
    return CreateObjectDestinationUseCase(repository, connections)


def get_list_object_destinations_use_case(
    repository: PublishConfigurationRepositoryDep,
) -> ListObjectDestinationsUseCase:
    return ListObjectDestinationsUseCase(repository)


def get_create_catalog_destination_use_case(
    repository: PublishConfigurationRepositoryDep,
    connections: PublicationConnectionRegistryDep,
) -> CreateCatalogDestinationUseCase:
    return CreateCatalogDestinationUseCase(repository, connections)


def get_list_catalog_destinations_use_case(
    repository: PublishConfigurationRepositoryDep,
) -> ListCatalogDestinationsUseCase:
    return ListCatalogDestinationsUseCase(repository)


def get_create_publish_profile_use_case(
    repository: PublishConfigurationRepositoryDep,
) -> CreatePublishProfileUseCase:
    return CreatePublishProfileUseCase(repository)


def get_list_publish_profiles_use_case(
    repository: PublishConfigurationRepositoryDep,
) -> ListPublishProfilesUseCase:
    return ListPublishProfilesUseCase(repository)


def get_get_publish_profile_use_case(
    repository: PublishConfigurationRepositoryDep,
) -> GetPublishProfileUseCase:
    return GetPublishProfileUseCase(repository)


def get_create_publish_profile_revision_use_case(
    repository: PublishConfigurationRepositoryDep,
) -> CreatePublishProfileRevisionUseCase:
    return CreatePublishProfileRevisionUseCase(repository)


def get_activate_publish_profile_revision_use_case(
    repository: PublishConfigurationRepositoryDep,
) -> ActivatePublishProfileRevisionUseCase:
    return ActivatePublishProfileRevisionUseCase(repository)


CreateObjectDestinationUseCaseDep = Annotated[
    CreateObjectDestinationUseCase,
    Depends(get_create_object_destination_use_case),
]
ListObjectDestinationsUseCaseDep = Annotated[
    ListObjectDestinationsUseCase,
    Depends(get_list_object_destinations_use_case),
]
CreateCatalogDestinationUseCaseDep = Annotated[
    CreateCatalogDestinationUseCase,
    Depends(get_create_catalog_destination_use_case),
]
ListCatalogDestinationsUseCaseDep = Annotated[
    ListCatalogDestinationsUseCase,
    Depends(get_list_catalog_destinations_use_case),
]
CreatePublishProfileUseCaseDep = Annotated[
    CreatePublishProfileUseCase,
    Depends(get_create_publish_profile_use_case),
]
ListPublishProfilesUseCaseDep = Annotated[
    ListPublishProfilesUseCase,
    Depends(get_list_publish_profiles_use_case),
]
GetPublishProfileUseCaseDep = Annotated[
    GetPublishProfileUseCase,
    Depends(get_get_publish_profile_use_case),
]
CreatePublishProfileRevisionUseCaseDep = Annotated[
    CreatePublishProfileRevisionUseCase,
    Depends(get_create_publish_profile_revision_use_case),
]
ActivatePublishProfileRevisionUseCaseDep = Annotated[
    ActivatePublishProfileRevisionUseCase,
    Depends(get_activate_publish_profile_revision_use_case),
]
