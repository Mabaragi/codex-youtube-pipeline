from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import (
    OperationEventRecorderDep,
    PipelineJobRepositoryDep,
    TranscriptCueRepositoryDep,
    YouTubeTranscriptRepositoryDep,
    YouTubeTranscriptStorageDep,
)
from codex_sdk_cli.domains.transcript_cues.use_cases import (
    GenerateTranscriptCuesUseCase,
    GetTranscriptPromptCuesUseCase,
    ListTranscriptCuesUseCase,
)


def get_generate_transcript_cues_use_case(
    transcripts: YouTubeTranscriptRepositoryDep,
    storage: YouTubeTranscriptStorageDep,
    cues: TranscriptCueRepositoryDep,
    pipeline_jobs: PipelineJobRepositoryDep,
    events: OperationEventRecorderDep,
) -> GenerateTranscriptCuesUseCase:
    return GenerateTranscriptCuesUseCase(
        transcripts=transcripts,
        storage=storage,
        cues=cues,
        pipeline_jobs=pipeline_jobs,
        events=events,
    )


def get_list_transcript_cues_use_case(
    transcripts: YouTubeTranscriptRepositoryDep,
    cues: TranscriptCueRepositoryDep,
) -> ListTranscriptCuesUseCase:
    return ListTranscriptCuesUseCase(transcripts=transcripts, cues=cues)


def get_get_transcript_prompt_cues_use_case(
    transcripts: YouTubeTranscriptRepositoryDep,
    cues: TranscriptCueRepositoryDep,
) -> GetTranscriptPromptCuesUseCase:
    return GetTranscriptPromptCuesUseCase(transcripts=transcripts, cues=cues)


GenerateTranscriptCuesUseCaseDep = Annotated[
    GenerateTranscriptCuesUseCase,
    Depends(get_generate_transcript_cues_use_case),
]
ListTranscriptCuesUseCaseDep = Annotated[
    ListTranscriptCuesUseCase,
    Depends(get_list_transcript_cues_use_case),
]
GetTranscriptPromptCuesUseCaseDep = Annotated[
    GetTranscriptPromptCuesUseCase,
    Depends(get_get_transcript_prompt_cues_use_case),
]
