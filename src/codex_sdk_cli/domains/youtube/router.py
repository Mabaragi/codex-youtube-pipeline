from __future__ import annotations

from fastapi import APIRouter

from .dependencies import FetchYouTubeTranscriptUseCaseDep
from .schemas import TranscriptRequest, TranscriptResponse

router = APIRouter()


@router.post("/transcripts", response_model=TranscriptResponse)
async def fetch_youtube_transcript(
    request: TranscriptRequest,
    use_case: FetchYouTubeTranscriptUseCaseDep,
) -> TranscriptResponse:
    return await use_case.execute(request)

