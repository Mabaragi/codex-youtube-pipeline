from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    SettingsDep,
    YouTubeTranscriptClientDep,
    YouTubeTranscriptStorageDep,
)

from .use_cases import FetchYouTubeTranscriptUseCase


def get_fetch_youtube_transcript_use_case(
    client: YouTubeTranscriptClientDep,
    storage: YouTubeTranscriptStorageDep,
    settings: SettingsDep,
) -> FetchYouTubeTranscriptUseCase:
    return FetchYouTubeTranscriptUseCase(
        client,
        storage,
        storage_prefix=settings.transcript_minio_prefix,
    )


FetchYouTubeTranscriptUseCaseDep = Annotated[
    FetchYouTubeTranscriptUseCase,
    Depends(get_fetch_youtube_transcript_use_case),
]
