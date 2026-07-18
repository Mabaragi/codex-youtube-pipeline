from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import DatabaseSessionDep, SettingsDep
from codex_sdk_cli.application.publication.errors import PublicationStageUnavailable
from codex_sdk_cli.infra.archive_publish.checkpoints import (
    SqlAlchemyArchivePublicationCheckpointRepository,
)
from codex_sdk_cli.infra.archive_publish.repository import (
    SqlAlchemyArchivePublishRepository,
)
from codex_sdk_cli.infra.publication.factory import PublicationConnectionFactory
from codex_sdk_cli.infra.publication.stages import PublicationStageService
from codex_sdk_cli.infra.publication_config.repository import (
    SqlAlchemyPublishConfigurationRepository,
)


async def get_publication_stage_service(
    session: DatabaseSessionDep,
    settings: SettingsDep,
) -> AsyncGenerator[PublicationStageService]:
    path = settings.publish_connections_file
    if path is None or not path.is_file():
        raise PublicationStageUnavailable(
            "Publication connections file is not configured or does not exist."
        )
    factory = PublicationConnectionFactory.from_settings(settings)
    try:
        yield PublicationStageService(
            configuration=SqlAlchemyPublishConfigurationRepository(session),
            checkpoints=SqlAlchemyArchivePublicationCheckpointRepository(session),
            archive=SqlAlchemyArchivePublishRepository(session),
            connections=factory,
            artifact_store_ref=settings.publication_artifact_store_ref,
            staging_store_ref=settings.publication_staging_store_ref,
        )
    finally:
        await factory.aclose()


PublicationStageServiceDep = Annotated[
    PublicationStageService,
    Depends(get_publication_stage_service),
]

__all__ = ["PublicationStageServiceDep", "get_publication_stage_service"]
