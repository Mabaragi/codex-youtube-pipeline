from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import DatabaseSessionDep, SettingsDep
from codex_sdk_cli.application.publication.status import (
    ListPublicationStatusesUseCase,
    PublicationStatusRepositoryPort,
)
from codex_sdk_cli.infra.publication.connections import (
    PublicationConnectionRegistry,
    load_publication_connection_registry,
)
from codex_sdk_cli.infra.publication.status_repository import (
    SqlAlchemyPublicationStatusRepository,
)


def get_publication_connection_registry(
    settings: SettingsDep,
) -> PublicationConnectionRegistry:
    return load_publication_connection_registry(settings.publish_connections_file)


PublicationConnectionRegistryDep = Annotated[
    PublicationConnectionRegistry,
    Depends(get_publication_connection_registry),
]


def get_publication_status_repository(
    session: DatabaseSessionDep,
) -> PublicationStatusRepositoryPort:
    return SqlAlchemyPublicationStatusRepository(session)


def get_list_publication_statuses_use_case(
    repository: Annotated[
        PublicationStatusRepositoryPort,
        Depends(get_publication_status_repository),
    ],
) -> ListPublicationStatusesUseCase:
    return ListPublicationStatusesUseCase(repository)


ListPublicationStatusesUseCaseDep = Annotated[
    ListPublicationStatusesUseCase,
    Depends(get_list_publication_statuses_use_case),
]
