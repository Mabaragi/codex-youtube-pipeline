from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from codex_sdk_cli.domains.codex.ports import CodexRuntimePort
from codex_sdk_cli.domains.streamers.ports import StreamerRepositoryPort
from codex_sdk_cli.domains.youtube_data.exceptions import YouTubeDataConfigurationError
from codex_sdk_cli.domains.youtube_data.ports import YouTubeDataClientPort
from codex_sdk_cli.domains.youtube_transcripts.exceptions import YouTubeTranscriptStorageError
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptPort,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptStoragePort,
)
from codex_sdk_cli.infra.codex.client import CodexRuntimeClient
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository
from codex_sdk_cli.infra.youtube_data.client import YouTubeDataClient
from codex_sdk_cli.infra.youtube_transcripts.client import YouTubeTranscriptClient
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    SqlAlchemyYouTubeTranscriptRepository,
)
from codex_sdk_cli.infra.youtube_transcripts.storage import MinioTranscriptStorage
from codex_sdk_cli.settings import CliSettings


@lru_cache
def get_settings() -> CliSettings:
    return CliSettings()


async def get_codex_runtime(
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> CodexRuntimePort:
    return CodexRuntimeClient(settings)


@lru_cache
def _get_database_engine(database_url: str, echo: bool) -> AsyncEngine:
    return create_database_engine(database_url, echo=echo)


def get_database_engine(settings: Annotated[CliSettings, Depends(get_settings)]) -> AsyncEngine:
    return _get_database_engine(settings.database_url, settings.database_echo)


def get_database_session_factory(
    engine: Annotated[AsyncEngine, Depends(get_database_engine)],
) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


async def get_database_session(
    session_factory: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_database_session_factory),
    ],
) -> AsyncGenerator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def get_youtube_transcript_client(
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> YouTubeTranscriptPort:
    return YouTubeTranscriptClient.from_settings(settings)


async def get_youtube_transcript_repository(
    session: DatabaseSessionDep,
) -> YouTubeTranscriptRepositoryPort:
    return SqlAlchemyYouTubeTranscriptRepository(session)


async def get_streamer_repository(
    session: DatabaseSessionDep,
) -> StreamerRepositoryPort:
    return SqlAlchemyStreamerRepository(session)


async def get_youtube_data_client(
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> AsyncGenerator[YouTubeDataClientPort]:
    api_key = settings.youtube_data_api_key_value()
    if api_key is None:
        raise YouTubeDataConfigurationError("YouTube Data API key is not configured.")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.youtube_data_timeout_seconds),
    ) as http_client:
        yield YouTubeDataClient(http_client, api_key=api_key)


async def get_youtube_transcript_storage(
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> YouTubeTranscriptStoragePort:
    if (
        settings.transcript_minio_endpoint is None
        or settings.transcript_minio_access_key is None
        or settings.transcript_minio_secret_key is None
        or settings.transcript_minio_bucket is None
    ):
        raise YouTubeTranscriptStorageError("Transcript MinIO storage is not configured.")
    return MinioTranscriptStorage.from_settings(settings)


SettingsDep = Annotated[CliSettings, Depends(get_settings)]
CodexRuntimeDep = Annotated[CodexRuntimePort, Depends(get_codex_runtime)]
DatabaseSessionDep = Annotated[AsyncSession, Depends(get_database_session)]
YouTubeTranscriptClientDep = Annotated[
    YouTubeTranscriptPort,
    Depends(get_youtube_transcript_client),
]
YouTubeTranscriptRepositoryDep = Annotated[
    YouTubeTranscriptRepositoryPort,
    Depends(get_youtube_transcript_repository),
]
StreamerRepositoryDep = Annotated[
    StreamerRepositoryPort,
    Depends(get_streamer_repository),
]
YouTubeDataClientDep = Annotated[
    YouTubeDataClientPort,
    Depends(get_youtube_data_client),
]
YouTubeTranscriptStorageDep = Annotated[
    YouTubeTranscriptStoragePort,
    Depends(get_youtube_transcript_storage),
]
