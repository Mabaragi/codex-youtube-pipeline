from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    ArchivePublishRepositoryDep,
    DatabaseSessionDep,
    OperationEventRecorderDep,
    PublishConfigurationRepositoryDep,
    StreamerRepositoryDep,
)
from codex_sdk_cli.api.use_case_dependencies.publication_stages import (
    PublicationStageServiceDep,
)
from codex_sdk_cli.application.publication.cutovers import (
    GetPublicationCutoverUseCase,
    ListPublicationCutoversUseCase,
    PublicationCutoverService,
)
from codex_sdk_cli.infra.publication.cutovers import (
    SqlAlchemyPublicationCutoverRepository,
)


def get_publication_cutover_service(
    session: DatabaseSessionDep,
    configuration: PublishConfigurationRepositoryDep,
    archive: ArchivePublishRepositoryDep,
    streamers: StreamerRepositoryDep,
    stages: PublicationStageServiceDep,
    events: OperationEventRecorderDep,
) -> PublicationCutoverService:
    return PublicationCutoverService(
        repository=SqlAlchemyPublicationCutoverRepository(session),
        configuration=configuration,
        archive=archive,
        streamers=streamers,
        stages=stages,
        events=events,
    )


PublicationCutoverServiceDep = Annotated[
    PublicationCutoverService,
    Depends(get_publication_cutover_service),
]


def get_get_publication_cutover_use_case(
    session: DatabaseSessionDep,
) -> GetPublicationCutoverUseCase:
    return GetPublicationCutoverUseCase(SqlAlchemyPublicationCutoverRepository(session))


def get_list_publication_cutovers_use_case(
    session: DatabaseSessionDep,
) -> ListPublicationCutoversUseCase:
    return ListPublicationCutoversUseCase(SqlAlchemyPublicationCutoverRepository(session))


GetPublicationCutoverUseCaseDep = Annotated[
    GetPublicationCutoverUseCase,
    Depends(get_get_publication_cutover_use_case),
]
ListPublicationCutoversUseCaseDep = Annotated[
    ListPublicationCutoversUseCase,
    Depends(get_list_publication_cutovers_use_case),
]
