from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from codex_sdk_cli.api.operator_context import OperatorReason
from codex_sdk_cli.api.use_case_dependencies.operation_events import (
    RecordOperatorMutationUseCaseDep,
)
from codex_sdk_cli.api.use_case_dependencies.transcript_cues import (
    GetTranscriptPromptCuesUseCaseDep,
    ListTranscriptCuesUseCaseDep,
)
from codex_sdk_cli.api.use_case_dependencies.youtube_transcripts import (
    DeleteYouTubeTranscriptMetadataUseCaseDep,
    GetYouTubeTranscriptMetadataUseCaseDep,
    ListYouTubeTranscriptMetadataUseCaseDep,
    ReadYouTubeTranscriptContentUseCaseDep,
    UpdateYouTubeTranscriptMetadataUseCaseDep,
)
from codex_sdk_cli.domains.transcript_cues.schemas import (
    TranscriptCueListResponse,
    TranscriptPromptCuesResponse,
)
from codex_sdk_cli.domains.youtube_transcripts.schemas import (
    DeleteResponse,
    TranscriptMetadataResponse,
    TranscriptMetadataUpdateRequest,
    TranscriptResponse,
)

router = APIRouter()


@router.get("", response_model=list[TranscriptMetadataResponse])
async def list_youtube_transcript_metadata(
    use_case: ListYouTubeTranscriptMetadataUseCaseDep,
    video_id: Annotated[str | None, Query(alias="videoId", min_length=1)] = None,
    language_code: Annotated[str | None, Query(alias="languageCode", min_length=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TranscriptMetadataResponse]:
    return await use_case.execute(
        video_id=video_id,
        language_code=language_code,
        limit=limit,
        offset=offset,
    )


@router.get("/{transcript_id}", response_model=TranscriptMetadataResponse)
async def get_youtube_transcript_metadata(
    transcript_id: Annotated[int, Path(ge=1)],
    use_case: GetYouTubeTranscriptMetadataUseCaseDep,
) -> TranscriptMetadataResponse:
    return await use_case.execute(transcript_id)


@router.get("/{transcript_id}/content", response_model=TranscriptResponse)
async def read_youtube_transcript_content(
    transcript_id: Annotated[int, Path(ge=1)],
    use_case: ReadYouTubeTranscriptContentUseCaseDep,
) -> TranscriptResponse:
    return await use_case.execute(transcript_id)


@router.get("/{transcript_id}/cues", response_model=TranscriptCueListResponse)
async def list_youtube_transcript_cues(
    transcript_id: Annotated[int, Path(ge=1)],
    use_case: ListTranscriptCuesUseCaseDep,
) -> TranscriptCueListResponse:
    return await use_case.execute(transcript_id)


@router.get("/{transcript_id}/prompt-cues", response_model=TranscriptPromptCuesResponse)
async def get_youtube_transcript_prompt_cues(
    transcript_id: Annotated[int, Path(ge=1)],
    use_case: GetTranscriptPromptCuesUseCaseDep,
) -> TranscriptPromptCuesResponse:
    return await use_case.execute(transcript_id)


@router.patch("/{transcript_id}", response_model=TranscriptMetadataResponse)
async def update_youtube_transcript_metadata(
    transcript_id: Annotated[int, Path(ge=1)],
    request: TranscriptMetadataUpdateRequest,
    use_case: UpdateYouTubeTranscriptMetadataUseCaseDep,
) -> TranscriptMetadataResponse:
    return await use_case.execute(transcript_id, request)


@router.delete(
    "/{transcript_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_youtube_transcript_metadata(
    transcript_id: Annotated[int, Path(ge=1)],
    reason: OperatorReason,
    use_case: DeleteYouTubeTranscriptMetadataUseCaseDep,
    audit: RecordOperatorMutationUseCaseDep,
) -> DeleteResponse:
    response = await use_case.execute(transcript_id)
    await audit.execute(
        mutation="deleted",
        target_type="transcript",
        target_id=transcript_id,
        action="delete",
        reason=reason,
    )
    return response
