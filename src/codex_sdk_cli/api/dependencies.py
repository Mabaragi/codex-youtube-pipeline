from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.domains.codex.ports import CodexRuntimePort
from codex_sdk_cli.domains.youtube.exceptions import YouTubeTranscriptStorageError
from codex_sdk_cli.domains.youtube.ports import (
    YouTubeTranscriptPort,
    YouTubeTranscriptStoragePort,
)
from codex_sdk_cli.infra.codex.client import CodexRuntimeClient
from codex_sdk_cli.infra.youtube.client import YouTubeTranscriptClient
from codex_sdk_cli.infra.youtube.storage import MinioTranscriptStorage
from codex_sdk_cli.settings import CliSettings


@lru_cache
def get_settings() -> CliSettings:
    return CliSettings()


async def get_codex_runtime(
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> CodexRuntimePort:
    return CodexRuntimeClient(settings)


async def get_youtube_transcript_client(
    settings: Annotated[CliSettings, Depends(get_settings)],
) -> YouTubeTranscriptPort:
    return YouTubeTranscriptClient.from_settings(settings)


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
YouTubeTranscriptClientDep = Annotated[
    YouTubeTranscriptPort,
    Depends(get_youtube_transcript_client),
]
YouTubeTranscriptStorageDep = Annotated[
    YouTubeTranscriptStoragePort,
    Depends(get_youtube_transcript_storage),
]
