from __future__ import annotations

from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .models import _ComposerInput, _EnqueueCounters, _TimelineRawResponse
from .ports import TimelineCompositionRecord
from .schemas import (
    TimelineBlockResponse,
    TimelineComposeEnqueueItemResponse,
    TimelineComposeEnqueueRequest,
    TimelineComposeEnqueueResponse,
    TimelineCompositionResponse,
    TimelineEpisodeResponse,
    TimelineReviewFlagResponse,
    TimelineTopicClusterResponse,
)
from .tracing import _raw_response_json, _raw_response_summary


def _enqueue_response(
    request: TimelineComposeEnqueueRequest,
    counters: _EnqueueCounters,
    items: list[TimelineComposeEnqueueItemResponse],
) -> TimelineComposeEnqueueResponse:
    requested_count = (
        min(len(request.video_ids), request.limit)
        if request.target == "selected_videos"
        else request.limit
    )
    return TimelineComposeEnqueueResponse(
        requestedCount=requested_count,
        scannedCount=counters.scanned_count,
        enqueuedCount=counters.enqueued_count,
        alreadyPendingCount=counters.already_pending_count,
        alreadyRunningCount=counters.already_running_count,
        alreadySucceededCount=counters.already_succeeded_count,
        retryQueuedCount=counters.retry_queued_count,
        regeneratedCount=counters.regenerated_count,
        failedSkippedCount=counters.failed_skipped_count,
        ineligibleCount=counters.ineligible_count,
        items=items,
    )


def _enqueue_item(
    *,
    video_id: int,
    youtube_video_id: str | None,
    task: VideoTaskRecord | None,
    status: str,
    reason: str,
    source_task_id: int | None,
    model: str | None,
    reasoning_effort: str | None,
    copy_style: str | None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> TimelineComposeEnqueueItemResponse:
    return TimelineComposeEnqueueItemResponse(
        videoId=video_id,
        youtubeVideoId=youtube_video_id,
        videoTaskId=task.id if task is not None else None,
        status=status,
        reason=reason,
        sourceMicroEventTaskId=source_task_id,
        model=model,
        reasoningEffort=reasoning_effort,
        copyStyle=copy_style,
        errorType=error_type,
        errorMessage=error_message,
    )


def _timeline_response(record: TimelineCompositionRecord) -> TimelineCompositionResponse:
    return TimelineCompositionResponse(
        videoTaskId=record.video_task_id,
        videoId=record.video_id,
        youtubeVideoId=record.youtube_video_id,
        sourceMicroEventTaskId=record.source_micro_event_task_id,
        sourceMicroEventFingerprint=record.source_micro_event_fingerprint,
        copyStyle=record.copy_style,
        status=record.status,
        model=record.model,
        reasoningEffort=record.reasoning_effort,
        title=record.title,
        summary=record.summary,
        displayTitle=record.display_title,
        displaySummary=record.display_summary,
        mainTopics=record.main_topics,
        validationWarnings=record.validation_warnings,
        outputJson=record.output_json,
        blocks=[
            TimelineBlockResponse(
                blockId=item.block_id,
                blockIndex=item.block_index,
                blockType=item.block_type,
                title=item.title,
                summary=item.summary,
                displayTitle=item.display_title,
                displaySummary=item.display_summary,
                episodeIds=item.episode_ids,
            )
            for item in record.blocks
        ],
        episodes=[
            TimelineEpisodeResponse(
                episodeId=item.episode_id,
                episodeIndex=item.episode_index,
                parentBlockId=item.parent_block_id,
                startMicroEventCandidateId=item.start_micro_event_candidate_id,
                endMicroEventCandidateId=item.end_micro_event_candidate_id,
                programMode=item.program_mode,
                primaryContentKind=item.primary_content_kind,
                title=item.title,
                summary=item.summary,
                displayTitle=item.display_title,
                displaySummary=item.display_summary,
                topics=item.topics,
                viewerTags=item.viewer_tags,
                highlightMicroEventCandidateIds=item.highlight_micro_event_candidate_ids,
                visibility=item.visibility,
            )
            for item in record.episodes
        ],
        topicClusters=[
            TimelineTopicClusterResponse(
                topicId=item.topic_id,
                topicIndex=item.topic_index,
                label=item.label,
                summary=item.summary,
                displayLabel=item.display_label,
                episodeIds=item.episode_ids,
            )
            for item in record.topic_clusters
        ],
        reviewFlags=[
            TimelineReviewFlagResponse(
                flagIndex=item.flag_index,
                startMicroEventCandidateId=item.start_micro_event_candidate_id,
                endMicroEventCandidateId=item.end_micro_event_candidate_id,
                type=item.type,
                reason=item.reason,
            )
            for item in record.review_flags
        ],
    )


def _output_json(
    record: TimelineCompositionRecord,
    composer_input: _ComposerInput,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> JsonObject:
    return {
        "videoTaskId": record.video_task_id,
        "videoId": record.video_id,
        "youtubeVideoId": record.youtube_video_id,
        "sourceMicroEventTaskId": composer_input.source_task.id,
        "sourceMicroEventFingerprint": record.source_micro_event_fingerprint,
        "copyStyle": record.copy_style,
        "model": record.model,
        "reasoningEffort": record.reasoning_effort,
        "timelineTitle": record.title,
        "blockCount": len(record.blocks),
        "episodeCount": len(record.episodes),
        "topicClusterCount": len(record.topic_clusters),
        "reviewFlagCount": len(record.review_flags),
        "validationWarnings": record.validation_warnings,
        "jobId": job.id,
        "jobAttemptId": attempt.id,
    }


def _attempt_output_json(
    composer_input: _ComposerInput,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    raw_responses: list[_TimelineRawResponse] | None = None,
) -> JsonObject:
    output: JsonObject = {
        "videoId": composer_input.video.id,
        "youtubeVideoId": composer_input.video.youtube_video_id,
        "sourceMicroEventTaskId": composer_input.source_task.id,
        "copyStyle": composer_input.copy_style,
        "model": composer_input.model,
        "reasoningEffort": composer_input.reasoning_effort,
        "jobId": job.id,
        "jobAttemptId": attempt.id,
    }
    if raw_responses is not None:
        output.update(_raw_response_summary(raw_responses))
    return output


def _failed_attempt_output_json(
    composer_input: _ComposerInput,
    *,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    error_type: str,
    error_message: str,
    stage: str,
    raw_responses: list[_TimelineRawResponse],
) -> JsonObject:
    output = _attempt_output_json(
        composer_input,
        job=job,
        attempt=attempt,
        raw_responses=raw_responses,
    )
    output["failure"] = {
        "errorType": error_type,
        "errorMessage": error_message,
        "stage": stage,
    }
    output["rawResponses"] = [_raw_response_json(item) for item in raw_responses]
    return output
