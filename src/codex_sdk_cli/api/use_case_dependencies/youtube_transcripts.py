from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    SettingsDep,
    YouTubeTranscriptClientDep,
    YouTubeTranscriptRepositoryDep,
    YouTubeTranscriptStorageDep,
)
from codex_sdk_cli.domains.youtube_transcripts.use_cases import (
    DeleteYouTubeTranscriptMetadataUseCase,
    FetchYouTubeTranscriptUseCase,
    GetYouTubeTranscriptMetadataUseCase,
    ListYouTubeTranscriptMetadataUseCase,
    ReadYouTubeTranscriptContentUseCase,
    UpdateYouTubeTranscriptMetadataUseCase,
)


def get_fetch_youtube_transcript_use_case(
    client: YouTubeTranscriptClientDep,
    storage: YouTubeTranscriptStorageDep,
    repository: YouTubeTranscriptRepositoryDep,
    settings: SettingsDep,
) -> FetchYouTubeTranscriptUseCase:
    return FetchYouTubeTranscriptUseCase(
        client,
        storage,
        repository,
        storage_prefix=settings.transcript_minio_prefix,
    )


def get_list_youtube_transcript_metadata_use_case(
    repository: YouTubeTranscriptRepositoryDep,
) -> ListYouTubeTranscriptMetadataUseCase:
    return ListYouTubeTranscriptMetadataUseCase(repository)


def get_get_youtube_transcript_metadata_use_case(
    repository: YouTubeTranscriptRepositoryDep,
) -> GetYouTubeTranscriptMetadataUseCase:
    return GetYouTubeTranscriptMetadataUseCase(repository)


def get_update_youtube_transcript_metadata_use_case(
    repository: YouTubeTranscriptRepositoryDep,
) -> UpdateYouTubeTranscriptMetadataUseCase:
    return UpdateYouTubeTranscriptMetadataUseCase(repository)


def get_read_youtube_transcript_content_use_case(
    repository: YouTubeTranscriptRepositoryDep,
    storage: YouTubeTranscriptStorageDep,
) -> ReadYouTubeTranscriptContentUseCase:
    return ReadYouTubeTranscriptContentUseCase(
        repository=repository,
        storage=storage,
    )


def get_delete_youtube_transcript_metadata_use_case(
    repository: YouTubeTranscriptRepositoryDep,
) -> DeleteYouTubeTranscriptMetadataUseCase:
    return DeleteYouTubeTranscriptMetadataUseCase(repository)


FetchYouTubeTranscriptUseCaseDep = Annotated[
    FetchYouTubeTranscriptUseCase,
    Depends(get_fetch_youtube_transcript_use_case),
]
ListYouTubeTranscriptMetadataUseCaseDep = Annotated[
    ListYouTubeTranscriptMetadataUseCase,
    Depends(get_list_youtube_transcript_metadata_use_case),
]
GetYouTubeTranscriptMetadataUseCaseDep = Annotated[
    GetYouTubeTranscriptMetadataUseCase,
    Depends(get_get_youtube_transcript_metadata_use_case),
]
ReadYouTubeTranscriptContentUseCaseDep = Annotated[
    ReadYouTubeTranscriptContentUseCase,
    Depends(get_read_youtube_transcript_content_use_case),
]
UpdateYouTubeTranscriptMetadataUseCaseDep = Annotated[
    UpdateYouTubeTranscriptMetadataUseCase,
    Depends(get_update_youtube_transcript_metadata_use_case),
]
DeleteYouTubeTranscriptMetadataUseCaseDep = Annotated[
    DeleteYouTubeTranscriptMetadataUseCase,
    Depends(get_delete_youtube_transcript_metadata_use_case),
]
