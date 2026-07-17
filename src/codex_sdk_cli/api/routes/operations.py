from __future__ import annotations

from fastapi import APIRouter, status

from codex_sdk_cli.api.schemas.operations import (
    ArchivePublishOperationRequest,
    ChannelOperationBatchResponse,
    ChannelResolveOperationRequest,
    ChannelResolveOperationResponse,
    MicroEventOperationRequest,
    OperationBatchResponse,
    ProcessToPublishOperationRequest,
    TimelineOperationRequest,
    TranscriptCollectOperationRequest,
    TranscriptCueOperationRequest,
    VideoCollectOperationRequest,
    WorkflowBatchResponse,
    channel_operation_response,
    channel_resolve_response,
    operation_response,
    to_selection,
    workflow_batch_response,
)
from codex_sdk_cli.api.use_case_dependencies.ops import RefreshOpsVideoEmbedStatusUseCaseDep
from codex_sdk_cli.api.use_case_dependencies.work import (
    CollectTranscriptsUseCaseDep,
    CollectVideosUseCaseDep,
    ComposeTimelinesUseCaseDep,
    ExtractMicroEventsUseCaseDep,
    GenerateTranscriptCuesUseCaseDep,
    PublishArchivesUseCaseDep,
    ResolveChannelUseCaseDep,
    StartProcessToPublishUseCaseDep,
)
from codex_sdk_cli.application.channels.commands import ResolveChannelCommand
from codex_sdk_cli.application.processing.commands import (
    ComposeTimelinesCommand,
    ExtractMicroEventsCommand,
)
from codex_sdk_cli.application.transcripts.commands import (
    CollectTranscriptsCommand,
    GenerateTranscriptCuesCommand,
)
from codex_sdk_cli.application.videos.commands import CollectVideosCommand
from codex_sdk_cli.application.workflows.commands import ProcessToPublishCommand
from codex_sdk_cli.application.workflows.publish import PublishArchivesCommand
from codex_sdk_cli.domains.ops.schemas import (
    OpsRefreshVideoEmbedStatusRequest,
    OpsRefreshVideoEmbedStatusResponse,
)

router = APIRouter()


@router.post(
    "/operations/embed-status-refresh",
    response_model=OpsRefreshVideoEmbedStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def refresh_embed_status(
    use_case: RefreshOpsVideoEmbedStatusUseCaseDep,
    request: OpsRefreshVideoEmbedStatusRequest | None = None,
) -> OpsRefreshVideoEmbedStatusResponse:
    return await use_case.execute(request or OpsRefreshVideoEmbedStatusRequest())


@router.post(
    "/operations/channel-resolve",
    response_model=ChannelResolveOperationResponse,
    status_code=status.HTTP_200_OK,
)
async def resolve_channel(
    request: ChannelResolveOperationRequest,
    use_case: ResolveChannelUseCaseDep,
) -> ChannelResolveOperationResponse:
    return channel_resolve_response(
        await use_case.execute(
            ResolveChannelCommand(
                streamer_id=request.streamer_id,
                handle=request.handle,
                retry_failed=request.retry_failed,
                rerun_succeeded=request.rerun_succeeded,
                timeout_seconds=request.timeout_seconds,
            )
        )
    )


@router.post(
    "/operations/archive-publish",
    response_model=OperationBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def publish_archives(
    request: ArchivePublishOperationRequest,
    use_case: PublishArchivesUseCaseDep,
) -> OperationBatchResponse:
    return operation_response(
        await use_case.execute(
            PublishArchivesCommand(
                selection=to_selection(request.selection),
                publish_mode=request.publish_mode,
                environment=request.environment,
                variant=request.variant,
                schema_version=request.schema_version,
                retry_failed=request.retry_failed,
                rerun_succeeded=request.rerun_succeeded,
                include_non_embeddable=request.include_non_embeddable,
                timeout_seconds=request.timeout_seconds,
            )
        )
    )


@router.post(
    "/operations/video-collect",
    response_model=ChannelOperationBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def collect_videos(
    request: VideoCollectOperationRequest,
    use_case: CollectVideosUseCaseDep,
) -> ChannelOperationBatchResponse:
    return channel_operation_response(
        await use_case.execute(
            CollectVideosCommand(
                channel_ids=request.channel_ids,
                retry_failed=request.retry_failed,
                rerun_succeeded=request.rerun_succeeded,
                timeout_seconds=request.timeout_seconds,
            )
        )
    )


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
            micro_prompt_version_id=request.micro_prompt_version_id,
            timeline_model=request.timeline_model,
            timeline_reasoning_effort=request.timeline_reasoning_effort,
            timeline_prompt_version_id=request.timeline_prompt_version_id,
            transcript_fallback_mode=request.transcript_fallback.mode,
            transcript_fallback_grace_seconds=request.transcript_fallback.grace_seconds,
            transcript_recheck_interval_seconds=(
                request.transcript_fallback.recheck_interval_seconds
            ),
            asr_model=request.transcript_fallback.model,
            asr_language=request.transcript_fallback.language,
            asr_device=request.transcript_fallback.device,
            asr_compute_type=request.transcript_fallback.compute_type,
            asr_chunk_minutes=request.transcript_fallback.chunk_minutes,
            asr_overlap_seconds=request.transcript_fallback.overlap_seconds,
            asr_beam_size=request.transcript_fallback.beam_size,
            asr_vad_filter=request.transcript_fallback.vad_filter,
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
