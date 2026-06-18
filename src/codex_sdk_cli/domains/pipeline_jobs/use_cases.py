from __future__ import annotations

from codex_sdk_cli.domains.channels.schemas import ResolveYouTubeChannelRequest
from codex_sdk_cli.domains.channels.use_cases import ResolveYouTubeChannelUseCase
from codex_sdk_cli.domains.video_tasks.use_cases import (
    CollectChannelTranscriptTasksUseCase,
)
from codex_sdk_cli.domains.videos.use_cases import CollectChannelVideosUseCase

from .exceptions import PipelineJobNotFound, PipelineJobRetryNotAllowed
from .ports import (
    ExternalApiCallSummaryRecord,
    JsonObject,
    PipelineChannelOutputRecord,
    PipelineJobAttemptRecord,
    PipelineJobDetailRecord,
    PipelineJobListQuery,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
    PipelineJobStatus,
    PipelineJobSummaryRecord,
    PipelineTranscriptOutputRecord,
    PipelineVideoOutputRecord,
)
from .schemas import (
    ExternalApiCallSummaryResponse,
    ListPipelineJobsResponse,
    PipelineChannelOutputResponse,
    PipelineJobAttemptResponse,
    PipelineJobDetailResponse,
    PipelineJobSummaryResponse,
    PipelineTranscriptOutputResponse,
    PipelineVideoOutputResponse,
    RetryPipelineJobResponse,
)

CHANNEL_RESOLVE_STEP = "channel_resolve"


class ListPipelineJobsUseCase:
    def __init__(self, pipeline_jobs: PipelineJobRepositoryPort) -> None:
        self._pipeline_jobs = pipeline_jobs

    async def execute(
        self,
        *,
        step: str | None,
        status: PipelineJobStatus | None,
        subject_type: str | None,
        subject_id: int | None,
        external_key: str | None,
        cursor: int | None,
        limit: int,
    ) -> ListPipelineJobsResponse:
        records = await self._pipeline_jobs.list_job_summaries(
            PipelineJobListQuery(
                step=step,
                status=status,
                subject_type=subject_type,
                subject_id=subject_id,
                external_key=external_key,
                cursor=cursor,
                limit=limit + 1,
            )
        )
        visible_records = records[:limit]
        next_cursor = visible_records[-1].job.id if len(records) > limit else None
        return ListPipelineJobsResponse(
            items=[_job_summary_response(record) for record in visible_records],
            nextCursor=next_cursor,
        )


class GetPipelineJobUseCase:
    def __init__(self, pipeline_jobs: PipelineJobRepositoryPort) -> None:
        self._pipeline_jobs = pipeline_jobs

    async def execute(self, job_id: int) -> PipelineJobDetailResponse:
        detail = await self._pipeline_jobs.get_job_detail(job_id)
        if detail is None:
            raise PipelineJobNotFound("Pipeline job not found.")
        return _job_detail_response(detail)


class RetryPipelineJobUseCase:
    def __init__(
        self,
        pipeline_jobs: PipelineJobRepositoryPort,
        executors: dict[str, PipelineRetryExecutor],
    ) -> None:
        self._pipeline_jobs = pipeline_jobs
        self._executors = executors

    async def execute(self, job_id: int) -> RetryPipelineJobResponse:
        job = await self._pipeline_jobs.get_job(job_id)
        if job is None:
            raise PipelineJobNotFound("Pipeline job not found.")
        if job.status != "failed":
            raise PipelineJobRetryNotAllowed("Only failed pipeline jobs can be retried.")
        executor = self._executors.get(job.step)
        if executor is None:
            raise PipelineJobRetryNotAllowed(
                f"Retry is not supported for pipeline step '{job.step}'."
            )

        await self._pipeline_jobs.mark_job_running(job.id)
        attempt = await self._pipeline_jobs.create_attempt(job_id=job.id)
        result = await executor.execute(job, attempt)
        updated_job = await self._pipeline_jobs.get_job(job.id)
        return RetryPipelineJobResponse(
            jobId=job.id,
            jobAttemptId=attempt.id,
            step=job.step,
            status=updated_job.status if updated_job is not None else "succeeded",
            result=result,
        )


class PipelineRetryExecutor:
    async def execute(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        raise NotImplementedError


class ChannelResolveRetryExecutor(PipelineRetryExecutor):
    def __init__(self, use_case: ResolveYouTubeChannelUseCase) -> None:
        self._use_case = use_case

    async def execute(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        streamer_id, request = _channel_resolve_request(job)
        result = await self._use_case.execute_job_attempt(
            job,
            attempt,
            streamer_id=streamer_id,
            request=request,
        )
        return result.model_dump(by_alias=True)


class VideoCollectRetryExecutor(PipelineRetryExecutor):
    def __init__(self, use_case: CollectChannelVideosUseCase) -> None:
        self._use_case = use_case

    async def execute(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        channel_id, youtube_channel_id = _video_collect_request(job)
        result = await self._use_case.execute_job_attempt(
            job,
            attempt,
            channel_id=channel_id,
            youtube_channel_id=youtube_channel_id,
        )
        return result.model_dump(by_alias=True)


class TranscriptCollectRetryExecutor(PipelineRetryExecutor):
    def __init__(self, use_case: CollectChannelTranscriptTasksUseCase) -> None:
        self._use_case = use_case

    async def execute(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        return await self._use_case.execute_retry_job_attempt(job, attempt)


def _channel_resolve_request(job: PipelineJobRecord) -> tuple[int, ResolveYouTubeChannelRequest]:
    input_json = job.input_json
    return (
        _required_int(input_json, "streamerId"),
        ResolveYouTubeChannelRequest(handle=_required_str(input_json, "handle")),
    )


def _video_collect_request(job: PipelineJobRecord) -> tuple[int, str]:
    input_json = job.input_json
    return (
        _required_int(input_json, "channelId"),
        _required_str(input_json, "youtubeChannelId"),
    )


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise PipelineJobRetryNotAllowed(f"Pipeline job input is missing integer '{key}'.")
    return value


def _required_str(input_json: JsonObject, key: str) -> str:
    value = input_json.get(key)
    if not isinstance(value, str):
        raise PipelineJobRetryNotAllowed(f"Pipeline job input is missing string '{key}'.")
    return value


def _job_summary_response(record: PipelineJobSummaryRecord) -> PipelineJobSummaryResponse:
    job = record.job
    return PipelineJobSummaryResponse(
        jobId=job.id,
        step=job.step,
        status=job.status,
        subjectType=job.subject_type,
        subjectId=job.subject_id,
        externalKey=job.external_key,
        createdAt=job.created_at,
        updatedAt=job.updated_at,
        completedAt=job.completed_at,
        latestAttemptId=record.latest_attempt_id,
        latestAttemptStatus=record.latest_attempt_status,
        attemptCount=record.attempt_count,
    )


def _job_detail_response(detail: PipelineJobDetailRecord) -> PipelineJobDetailResponse:
    job = detail.job
    return PipelineJobDetailResponse(
        jobId=job.id,
        step=job.step,
        status=job.status,
        subjectType=job.subject_type,
        subjectId=job.subject_id,
        externalKey=job.external_key,
        inputJson=job.input_json,
        inputHash=job.input_hash,
        parentJobId=job.parent_job_id,
        createdAt=job.created_at,
        updatedAt=job.updated_at,
        completedAt=job.completed_at,
        attempts=[_attempt_response(attempt) for attempt in detail.attempts],
        externalApiCalls=[
            _external_api_call_response(call) for call in detail.external_api_calls
        ],
        channels=[_channel_output_response(channel) for channel in detail.channels],
        videos=[_video_output_response(video) for video in detail.videos],
        transcripts=[
            _transcript_output_response(transcript) for transcript in detail.transcripts
        ],
    )


def _attempt_response(attempt: PipelineJobAttemptRecord) -> PipelineJobAttemptResponse:
    return PipelineJobAttemptResponse(
        jobAttemptId=attempt.id,
        attemptNo=attempt.attempt_no,
        status=attempt.status,
        startedAt=attempt.started_at,
        finishedAt=attempt.finished_at,
        workerId=attempt.worker_id,
        errorType=attempt.error_type,
        errorMessage=attempt.error_message,
        outputJson=attempt.output_json,
    )


def _external_api_call_response(
    call: ExternalApiCallSummaryRecord,
) -> ExternalApiCallSummaryResponse:
    return ExternalApiCallSummaryResponse(
        externalApiCallId=call.id,
        jobAttemptId=call.pipeline_job_attempt_id,
        provider=call.provider,
        operation=call.operation,
        responseStatusCode=call.response_status_code,
        validationStatus=call.validation_status,
        responseStorageUri=call.response_storage_uri,
        durationMs=call.duration_ms,
        quotaCost=call.quota_cost,
        createdAt=call.created_at,
    )


def _channel_output_response(
    channel: PipelineChannelOutputRecord,
) -> PipelineChannelOutputResponse:
    return PipelineChannelOutputResponse(
        channelId=channel.id,
        streamerId=channel.streamer_id,
        handle=channel.handle,
        name=channel.name,
        youtubeChannelId=channel.youtube_channel_id,
        uploadsPlaylistId=channel.uploads_playlist_id,
        sourceApiCallId=channel.source_api_call_id,
        sourceJobId=channel.source_job_id,
    )


def _video_output_response(
    video: PipelineVideoOutputRecord,
) -> PipelineVideoOutputResponse:
    return PipelineVideoOutputResponse(
        videoId=video.id,
        channelId=video.channel_id,
        youtubeVideoId=video.youtube_video_id,
        title=video.title,
        publishedAt=video.published_at,
        sourceListingApiCallId=video.source_listing_api_call_id,
        sourceDetailsApiCallId=video.source_details_api_call_id,
        sourceJobId=video.source_job_id,
    )


def _transcript_output_response(
    transcript: PipelineTranscriptOutputRecord,
) -> PipelineTranscriptOutputResponse:
    return PipelineTranscriptOutputResponse(
        transcriptId=transcript.id,
        videoTaskId=transcript.video_task_id,
        videoId=transcript.video_id,
        youtubeVideoId=transcript.youtube_video_id,
        languageCode=transcript.language_code,
        storageUri=transcript.storage_uri,
    )
