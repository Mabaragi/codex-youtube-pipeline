from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import YouTubeTranscriptClientDep

from .use_cases import FetchYouTubeTranscriptUseCase


def get_fetch_youtube_transcript_use_case(
    client: YouTubeTranscriptClientDep,
) -> FetchYouTubeTranscriptUseCase:
    return FetchYouTubeTranscriptUseCase(client)


FetchYouTubeTranscriptUseCaseDep = Annotated[
    FetchYouTubeTranscriptUseCase,
    Depends(get_fetch_youtube_transcript_use_case),
]

