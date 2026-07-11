from __future__ import annotations

from fastapi import APIRouter, status

from codex_sdk_cli.api.schemas.operations import (
    OperationBatchResponse,
    TranscriptCollectOperationRequest,
    TranscriptCueOperationRequest,
    operation_response,
    to_selection,
)
from codex_sdk_cli.api.use_case_dependencies.work import (
    CollectTranscriptsUseCaseDep,
    GenerateTranscriptCuesUseCaseDep,
)
from codex_sdk_cli.application.transcripts.commands import (
    CollectTranscriptsCommand,
    GenerateTranscriptCuesCommand,
)

router = APIRouter()


@router.post(
    "/operations/transcript-collect",
    response_model=OperationBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def collect_transcripts(
    request: TranscriptCollectOperationRequest,
    use_case: CollectTranscriptsUseCaseDep,
) -> OperationBatchResponse:
    result = await use_case.execute(
        CollectTranscriptsCommand(
            selection=to_selection(request.selection),
            languages=request.languages,
            preserve_formatting=request.preserve_formatting,
            retry_failed=request.retry_failed,
            recheck_no_transcript=request.recheck_no_transcript,
            rerun_succeeded=request.rerun_succeeded,
            include_non_embeddable=request.include_non_embeddable,
            timeout_seconds=request.timeout_seconds,
        )
    )
    return operation_response(result)


@router.post(
    "/operations/transcript-cue-generate",
    response_model=OperationBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_transcript_cues(
    request: TranscriptCueOperationRequest,
    use_case: GenerateTranscriptCuesUseCaseDep,
) -> OperationBatchResponse:
    result = await use_case.execute(
        GenerateTranscriptCuesCommand(
            selection=to_selection(request.selection),
            retry_failed=request.retry_failed,
            rerun_succeeded=request.rerun_succeeded,
            include_non_embeddable=request.include_non_embeddable,
            timeout_seconds=request.timeout_seconds,
        )
    )
    return operation_response(result)
