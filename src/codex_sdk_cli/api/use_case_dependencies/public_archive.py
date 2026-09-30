from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from codex_sdk_cli.api.dependencies import SettingsDep
from codex_sdk_cli.application.public_archive.queries import (
    GetPublicArchiveCatalogVersionUseCase,
    GetPublicArchiveVideoUseCase,
    ListPublicArchiveStreamersUseCase,
    ListPublicArchiveVideosUseCase,
    PublicArchiveRepositoryPort,
    PublicArchiveScope,
)
from codex_sdk_cli.domains.publication.exceptions import PublicationConnectionTypeError
from codex_sdk_cli.infra.publication.catalog_database.session import (
    create_catalog_engine,
    create_catalog_session_factory,
)
from codex_sdk_cli.infra.publication.connections import (
    SqlCatalogConnection,
    load_publication_connection_registry,
)
from codex_sdk_cli.infra.publication.public_archive_repository import (
    SqlAlchemyPublicArchiveRepository,
)


@lru_cache
def _catalog_engine(database_url: str, echo: bool) -> AsyncEngine:
    return create_catalog_engine(database_url, echo=echo)


def get_public_archive_session_factory(
    settings: SettingsDep,
) -> async_sessionmaker[AsyncSession]:
    registry = load_publication_connection_registry(settings.publish_connections_file)
    connection = registry.connection(settings.public_archive_catalog_connection_ref)
    if not isinstance(connection, SqlCatalogConnection):
        raise PublicationConnectionTypeError(
            "The public archive catalog connection must be a SQL catalog."
        )
    engine = _catalog_engine(
        connection.database_url.get_secret_value(),
        connection.echo,
    )
    return create_catalog_session_factory(engine)


async def get_public_archive_session(
    session_factory: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_public_archive_session_factory),
    ],
) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            await session.execute(text("SET TRANSACTION READ ONLY"))
        yield session
        await session.rollback()


PublicArchiveSessionDep = Annotated[AsyncSession, Depends(get_public_archive_session)]


def get_public_archive_repository(
    session: PublicArchiveSessionDep,
) -> PublicArchiveRepositoryPort:
    return SqlAlchemyPublicArchiveRepository(session)


PublicArchiveRepositoryDep = Annotated[
    PublicArchiveRepositoryPort,
    Depends(get_public_archive_repository),
]


def get_public_archive_scope(
    settings: SettingsDep,
    environment: str = "prod",
) -> PublicArchiveScope:
    return PublicArchiveScope(
        profile_key=settings.public_archive_profile_key,
        publish_mode=settings.public_archive_publish_mode,
        environment=environment,
        additional_profile_keys=settings.public_archive_additional_profile_keys,
    )


PublicArchiveScopeDep = Annotated[PublicArchiveScope, Depends(get_public_archive_scope)]


def get_list_public_archive_videos_use_case(
    repository: PublicArchiveRepositoryDep,
) -> ListPublicArchiveVideosUseCase:
    return ListPublicArchiveVideosUseCase(repository)


def get_public_archive_video_use_case(
    repository: PublicArchiveRepositoryDep,
) -> GetPublicArchiveVideoUseCase:
    return GetPublicArchiveVideoUseCase(repository)


def get_list_public_archive_streamers_use_case(
    repository: PublicArchiveRepositoryDep,
) -> ListPublicArchiveStreamersUseCase:
    return ListPublicArchiveStreamersUseCase(repository)


def get_public_archive_catalog_version_use_case(
    repository: PublicArchiveRepositoryDep,
) -> GetPublicArchiveCatalogVersionUseCase:
    return GetPublicArchiveCatalogVersionUseCase(repository)


ListPublicArchiveVideosUseCaseDep = Annotated[
    ListPublicArchiveVideosUseCase,
    Depends(get_list_public_archive_videos_use_case),
]
GetPublicArchiveVideoUseCaseDep = Annotated[
    GetPublicArchiveVideoUseCase,
    Depends(get_public_archive_video_use_case),
]
ListPublicArchiveStreamersUseCaseDep = Annotated[
    ListPublicArchiveStreamersUseCase,
    Depends(get_list_public_archive_streamers_use_case),
]
GetPublicArchiveCatalogVersionUseCaseDep = Annotated[
    GetPublicArchiveCatalogVersionUseCase,
    Depends(get_public_archive_catalog_version_use_case),
]
