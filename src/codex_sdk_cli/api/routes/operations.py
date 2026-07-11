from __future__ import annotations

from fastapi import APIRouter, status

from codex_sdk_cli.api.schemas.operations import (
    MicroEventOperationRequest,
    OperationBatchResponse,
    ProcessToPublishOperationRequest,
    TimelineOperationRequest,
    TranscriptCollectOperationRequest,
    TranscriptCueOperationRequest,
    WorkflowBatchResponse,
    operation_response,
    to_selection,
    workflow_batch_response,
)
from codex_sdk_cli.api.use_case_dependencies.work import (
    CollectTranscriptsUseCaseDep,
    ComposeTimelinesUseCaseDep,
    ExtractMicroEventsUseCaseDep,
    GenerateTranscriptCuesUseCaseDep,
    StartProcessToPublishUseCaseDep,
)
from codex_sdk_cli.application.processing.commands import (
    ComposeTimelinesCommand,
    ExtractMicroEventsCommand,
)
from codex_sdk_cli.application.transcripts.commands import (
    CollectTranscriptsCommand,
    GenerateTranscriptCuesCommand,
)
from codex_sdk_cli.application.workflows.commands import ProcessToPublishCommand

router = APIRouter()


@router.post(
    "/workflows/process-to-publish",
    response_model=WorkflowBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_to_publish(
    request: ProcessToPublishOperationRequest,
    use_case: StartProcessToPublishUseCaseDep,
) -> WorkflowBatchResponse:
    result = await use_case.execute(
        ProcessToPublishCommand(
            selection=to_selection(request.selection),
            languages=request.languages,
            preserve_formatting=request.preserve_formatting,
            micro_window_minutes=request.micro_window_minutes,
            micro_overlap_minutes=request.micro_overlap_minutes,
            micro_model=request.micro_model,
            micro_reasoning_effort=request.micro_reasoning_effort,
            timeline_model=request.timeline_model,
            timeline_reasoning_effort=request.timeline_reasoning_effort,
            publish_mode=request.publish_mode,
            environment=request.environment,
            variant=request.variant,
            schema_version=request.schema_version,
            retry_failed=request.retry_failed,
            include_non_embeddable=request.include_non_embeddable,
        )
    )
    return workflow_batch_response(result)


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


@router.post(
    "/operations/micro-event-extract",
    response_model=OperationBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def extract_micro_events(
    request: MicroEventOperationRequest,
    use_case: ExtractMicroEventsUseCaseDep,
) -> OperationBatchResponse:
    result = await use_case.execute(
        ExtractMicroEventsCommand(
            selection=to_selection(request.selection),
            window_minutes=request.window_minutes,
            overlap_minutes=request.overlap_minutes,
            model=request.model,
            reasoning_effort=request.reasoning_effort,
            prompt_version_id=request.prompt_version_id,
            retry_failed=request.retry_failed,
            rerun_succeeded=request.rerun_succeeded,
            include_non_embeddable=request.include_non_embeddable,
            timeout_seconds=request.timeout_seconds,
        )
    )
    return operation_response(result)


@router.post(
    "/operations/timeline-compose",
    response_model=OperationBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def compose_timelines(
    request: TimelineOperationRequest,
    use_case: ComposeTimelinesUseCaseDep,
) -> OperationBatchResponse:
    result = await use_case.execute(
        ComposeTimelinesCommand(
            selection=to_selection(request.selection),
            model=request.model,
            reasoning_effort=request.reasoning_effort,
            copy_style=request.copy_style,
            prompt_version_id=request.prompt_version_id,
            retry_failed=request.retry_failed,
            rerun_succeeded=request.rerun_succeeded,
            include_non_embeddable=request.include_non_embeddable,
            timeout_seconds=request.timeout_seconds,
        )
    )
    return operation_response(result)
