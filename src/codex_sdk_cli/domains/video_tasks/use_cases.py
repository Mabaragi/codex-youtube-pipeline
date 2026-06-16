from __future__ import annotations

import asyncio
import hashlib
import json
from typing import cast

from codex_sdk_cli.domains.channels.exceptions import ChannelNotFound
from codex_sdk_cli.domains.channels.ports import ChannelRecord, ChannelRepositoryPort
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobAttemptRecord,
    PipelineJobCreate,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
)
from codex_sdk_cli.domains.videos.ports import VideoRecord, VideoRepositoryPort
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptRepositoryPort,
)
from codex_sdk_cli.domains.youtube_transcripts.schemas import (
    TranscriptMetadataResponse,
    TranscriptRequest,
)
from codex_sdk_cli.domains.youtube_transcripts.use_cases import (
    FetchYouTubeTranscriptUseCase,
    normalize_languages,
)

from .exceptions import VideoTaskNotFound, VideoTaskRetryNotAllowed
from .ports import (
    JsonObject,
    VideoTaskCreate,
    VideoTaskListQuery,
    VideoTaskListRecord,
    VideoTaskRecord,
    VideoTaskRepositoryPort,
    VideoTaskStatus,
)
from .schemas import (
    CollectChannelTranscriptTasksRequest,
    CollectChannelTranscriptTasksResponse,
    TranscriptCollectItemResponse,
    TranscriptCollectItemStatus,
    VideoTaskResponse,
)

TRANSCRIPT_COLLECT_STEP = "transcript_collect"
TRANSCRIPT_COLLECT_TASK_NAME = "transcript_collect"
TRANSCRIPT_COLLECT_TASK_VERSION = "v1"
TRANSCRIPT_COLLECT_WORKER_ID = "manual-api"


class CollectChannelTranscriptTasksUseCase:
    def __init__(
        self,
        *,
        channels: ChannelRepositoryPort,
        videos: VideoRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
        transcripts: YouTubeTranscriptRepositoryPort,
        fetch_transcript: FetchYouTubeTranscriptUseCase,
        timeout_seconds: int,
        concurrency_limit: int,
    ) -> None:
        self._channels = channels
        self._videos = videos
        self._video_tasks = video_tasks
        self._pipeline_jobs = pipeline_jobs
        self._transcripts = transcripts
        self._fetch_transcript = fetch_transcript
        self._timeout_seconds = timeout_seconds
        self._concurrency_limit = concurrency_limit

    async def execute(
        self,
        channel_id: int,
        request: CollectChannelTranscriptTasksRequest,
    ) -> CollectChannelTranscriptTasksResponse:
        await _get_channel_or_raise(self._channels, channel_id)
        languages = normalize_languages(request.languages)
        videos = (await self._videos.list_videos(channel_id=channel_id))[: request.limit]
        items = [
            await self._process_video(
                video,
                languages=languages,
                preserve_formatting=request.preserve_formatting,
                retry_failed=request.retry_failed,
            )
            for video in videos
        ]
        return _collect_response(channel_id, items)

    async def _process_video(
        self,
        video: VideoRecord,
        *,
        languages: tuple[str, ...],
        preserve_formatting: bool,
        retry_failed: bool,
    ) -> TranscriptCollectItemResponse:
        input_hash = _task_input_hash(
            youtube_video_id=video.youtube_video_id,
            languages=languages,
            preserve_formatting=preserve_formatting,
        )
        task = await self._video_tasks.get_or_create_task(
            VideoTaskCreate(
                video_id=video.id,
                task_name=TRANSCRIPT_COLLECT_TASK_NAME,
                task_version=TRANSCRIPT_COLLECT_TASK_VERSION,
                input_hash=input_hash,
                timeout_seconds=self._timeout_seconds,
            )
        )
        existing_metadata = await self._transcripts.find_transcript_metadata_for_request(
            video_id=video.youtube_video_id,
            requested_languages=languages,
            preserve_formatting=preserve_formatting,
        )
        if existing_metadata is not None and task.status != "running":
            succeeded = await self._video_tasks.mark_task_succeeded(
                task.id,
                output_transcript_id=existing_metadata.id,
                output_json=_existing_transcript_output_json(video, existing_metadata),
            )
            return _item_response(
                video,
                succeeded,
                status="succeeded",
                reason="existing_transcript",
                transcript_id=existing_metadata.id,
            )

        if task.status == "succeeded":
            return _item_response(
                video,
                task,
                status="skipped",
                reason="already_succeeded",
                transcript_id=task.output_transcript_id,
            )
        if task.status == "running":
            return _item_response(video, task, status="skipped", reason="already_running")
        if task.status in {"failed", "timed_out"} and not retry_failed:
            return _item_response(
                video,
                task,
                status="skipped",
                reason=f"previously_{task.status}",
                transcript_id=task.output_transcript_id,
            )
        if task.status in {"skipped", "canceled"}:
            return _item_response(video, task, status="skipped", reason="not_retryable")

        running_count = await self._video_tasks.count_running(
            task_name=TRANSCRIPT_COLLECT_TASK_NAME
        )
        if running_count >= self._concurrency_limit:
            return _item_response(video, task, status="skipped", reason="concurrency_limit")

        return await self._execute_task(
            task,
            video,
            languages=languages,
            preserve_formatting=preserve_formatting,
            input_hash=input_hash,
        )

    async def _execute_task(
        self,
        task: VideoTaskRecord,
        video: VideoRecord,
        *,
        languages: tuple[str, ...],
        preserve_formatting: bool,
        input_hash: str,
    ) -> TranscriptCollectItemResponse:
        input_json: JsonObject = {
            "videoTaskId": task.id,
            "videoId": video.id,
            "youtubeVideoId": video.youtube_video_id,
            "languages": list(languages),
            "preserveFormatting": preserve_formatting,
            "timeoutSeconds": self._timeout_seconds,
            "taskVersion": TRANSCRIPT_COLLECT_TASK_VERSION,
            "inputHash": input_hash,
        }
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step=TRANSCRIPT_COLLECT_STEP,
                status="running",
                subject_type="video",
                subject_id=video.id,
                external_key=video.youtube_video_id,
                input_json=input_json,
                input_hash=input_hash,
            )
        )
        attempt = await self._pipeline_jobs.create_attempt(job_id=job.id)
        task = await self._video_tasks.mark_task_running(
            task.id,
            worker_id=TRANSCRIPT_COLLECT_WORKER_ID,
            timeout_seconds=self._timeout_seconds,
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        return await self.execute_job_attempt(
            job,
            attempt,
            task=task,
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
            languages=languages,
            preserve_formatting=preserve_formatting,
            timeout_seconds=self._timeout_seconds,
        )

    async def execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        *,
        task: VideoTaskRecord,
        video_id: int,
        youtube_video_id: str,
        languages: tuple[str, ...],
        preserve_formatting: bool,
        timeout_seconds: int,
    ) -> TranscriptCollectItemResponse:
        try:
            stored = await asyncio.wait_for(
                self._fetch_transcript.execute_with_metadata(
                    TranscriptRequest(
                        video=youtube_video_id,
                        languages=list(languages),
                        preserveFormatting=preserve_formatting,
                    )
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            message = f"Transcript collection exceeded {timeout_seconds} seconds."
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type="TimeoutError",
                error_message=message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            updated = await self._video_tasks.mark_task_timed_out(
                task.id,
                error_message=message,
                output_json={"jobId": job.id, "jobAttemptId": attempt.id},
            )
            return _retry_item_response(
                video_id=video_id,
                youtube_video_id=youtube_video_id,
                task=updated,
                status="timed_out",
                reason="timeout",
            )
        except Exception as exc:
            error_type = exc.__class__.__name__
            error_message = str(exc) or error_type
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=error_type,
                error_message=error_message,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            updated = await self._video_tasks.mark_task_failed(
                task.id,
                error_type=error_type,
                error_message=error_message,
                output_json={"jobId": job.id, "jobAttemptId": attempt.id},
            )
            return _retry_item_response(
                video_id=video_id,
                youtube_video_id=youtube_video_id,
                task=updated,
                status="failed",
                reason="error",
            )

        output_json = _stored_transcript_output_json(
            video_id=video_id,
            youtube_video_id=youtube_video_id,
            metadata=stored.metadata,
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        updated = await self._video_tasks.mark_task_succeeded(
            task.id,
            output_transcript_id=stored.metadata.id,
            output_json=output_json,
        )
        await self._pipeline_jobs.mark_attempt_succeeded(
            attempt.id,
            output_json=output_json,
        )
        await self._pipeline_jobs.mark_job_succeeded(job.id)
        return _retry_item_response(
            video_id=video_id,
            youtube_video_id=youtube_video_id,
            task=updated,
            status="succeeded",
            reason="collected",
            transcript_id=stored.metadata.id,
        )

    async def execute_retry_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
    ) -> JsonObject:
        task_id = _required_int(job.input_json, "videoTaskId")
        task = await self._video_tasks.get_task(task_id)
        if task is None:
            raise VideoTaskNotFound("Video task not found.")
        if task.status not in {"failed", "timed_out"}:
            raise VideoTaskRetryNotAllowed(
                "Only failed or timed out transcript tasks can be retried."
            )
        video_id = _required_int(job.input_json, "videoId")
        youtube_video_id = _required_str(job.input_json, "youtubeVideoId")
        languages = tuple(_required_str_list(job.input_json, "languages"))
        preserve_formatting = _required_bool(job.input_json, "preserveFormatting")
        timeout_seconds = _required_int(job.input_json, "timeoutSeconds")
        task = await self._video_tasks.mark_task_running(
            task.id,
            worker_id=TRANSCRIPT_COLLECT_WORKER_ID,
            timeout_seconds=timeout_seconds,
            job_id=job.id,
            job_attempt_id=attempt.id,
        )
        result = await self.execute_job_attempt(
            job,
            attempt,
            task=task,
            video_id=video_id,
            youtube_video_id=youtube_video_id,
            languages=languages,
            preserve_formatting=preserve_formatting,
            timeout_seconds=timeout_seconds,
        )
        return result.model_dump(by_alias=True)


class ListChannelVideoTasksUseCase:
    def __init__(
        self,
        *,
        channels: ChannelRepositoryPort,
        video_tasks: VideoTaskRepositoryPort,
    ) -> None:
        self._channels = channels
        self._video_tasks = video_tasks

    async def execute(
        self,
        *,
        channel_id: int,
        task_name: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[VideoTaskResponse]:
        await _get_channel_or_raise(self._channels, channel_id)
        records = await self._video_tasks.list_tasks(
            VideoTaskListQuery(
                channel_id=channel_id,
                task_name=task_name,
                status=_task_status(status),
                limit=limit,
                offset=offset,
            )
        )
        return [_task_response(record) for record in records]


async def _get_channel_or_raise(
    repository: ChannelRepositoryPort,
    channel_id: int,
) -> ChannelRecord:
    channel = await repository.get_channel(channel_id)
    if channel is None:
        raise ChannelNotFound("Channel not found.")
    return channel


def _collect_response(
    channel_id: int,
    items: list[TranscriptCollectItemResponse],
) -> CollectChannelTranscriptTasksResponse:
    return CollectChannelTranscriptTasksResponse(
        channelId=channel_id,
        requestedCount=len(items),
        succeededCount=sum(item.status == "succeeded" for item in items),
        skippedCount=sum(item.status == "skipped" for item in items),
        failedCount=sum(item.status == "failed" for item in items),
        timeoutCount=sum(item.status == "timed_out" for item in items),
        items=items,
    )


def _item_response(
    video: VideoRecord,
    task: VideoTaskRecord,
    *,
    status: TranscriptCollectItemStatus,
    reason: str,
    transcript_id: int | None = None,
) -> TranscriptCollectItemResponse:
    return _retry_item_response(
        video_id=video.id,
        youtube_video_id=video.youtube_video_id,
        task=task,
        status=status,
        reason=reason,
        transcript_id=transcript_id,
    )


def _retry_item_response(
    *,
    video_id: int,
    youtube_video_id: str,
    task: VideoTaskRecord,
    status: TranscriptCollectItemStatus,
    reason: str,
    transcript_id: int | None = None,
) -> TranscriptCollectItemResponse:
    return TranscriptCollectItemResponse(
        videoId=video_id,
        youtubeVideoId=youtube_video_id,
        videoTaskId=task.id,
        status=status,
        reason=reason,
        jobId=task.job_id,
        jobAttemptId=task.job_attempt_id,
        transcriptId=transcript_id if transcript_id is not None else task.output_transcript_id,
        errorType=task.error_type,
        errorMessage=task.error_message,
    )


def _task_response(record: VideoTaskListRecord) -> VideoTaskResponse:
    task = record.task
    return VideoTaskResponse(
        videoTaskId=task.id,
        videoId=task.video_id,
        youtubeVideoId=record.youtube_video_id,
        taskName=task.task_name,
        taskVersion=task.task_version,
        inputHash=task.input_hash,
        status=task.status,
        workerId=task.worker_id,
        timeoutSeconds=task.timeout_seconds,
        jobId=task.job_id,
        jobAttemptId=task.job_attempt_id,
        outputTranscriptId=task.output_transcript_id,
        outputJson=task.output_json,
        errorType=task.error_type,
        errorMessage=task.error_message,
        startedAt=task.started_at,
        completedAt=task.completed_at,
        createdAt=task.created_at,
        updatedAt=task.updated_at,
    )


def _task_input_hash(
    *,
    youtube_video_id: str,
    languages: tuple[str, ...],
    preserve_formatting: bool,
) -> str:
    payload = {
        "languages": list(languages),
        "preserveFormatting": preserve_formatting,
        "taskVersion": TRANSCRIPT_COLLECT_TASK_VERSION,
        "youtubeVideoId": youtube_video_id,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _existing_transcript_output_json(
    video: VideoRecord,
    metadata: YouTubeTranscriptMetadataRecord,
) -> JsonObject:
    return {
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
        "transcriptId": metadata.id,
        "languageCode": metadata.language_code,
        "storageUri": metadata.storage_uri,
        "existingTranscript": True,
    }


def _stored_transcript_output_json(
    *,
    video_id: int,
    youtube_video_id: str,
    metadata: TranscriptMetadataResponse,
    job_id: int,
    job_attempt_id: int,
) -> JsonObject:
    return {
        "videoId": video_id,
        "youtubeVideoId": youtube_video_id,
        "transcriptId": metadata.id,
        "languageCode": metadata.language_code,
        "storageUri": metadata.storage.uri,
        "jobId": job_id,
        "jobAttemptId": job_attempt_id,
    }


def _task_status(value: str | None) -> VideoTaskStatus | None:
    if value is None:
        return None
    allowed = {"pending", "running", "succeeded", "failed", "timed_out", "skipped", "canceled"}
    if value not in allowed:
        raise VideoTaskRetryNotAllowed(f"Unsupported video task status '{value}'.")
    return cast(VideoTaskStatus, value)


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise VideoTaskRetryNotAllowed(f"Pipeline job input is missing integer '{key}'.")
    return value


def _required_str(input_json: JsonObject, key: str) -> str:
    value = input_json.get(key)
    if not isinstance(value, str):
        raise VideoTaskRetryNotAllowed(f"Pipeline job input is missing string '{key}'.")
    return value


def _required_bool(input_json: JsonObject, key: str) -> bool:
    value = input_json.get(key)
    if not isinstance(value, bool):
        raise VideoTaskRetryNotAllowed(f"Pipeline job input is missing boolean '{key}'.")
    return value


def _required_str_list(input_json: JsonObject, key: str) -> list[str]:
    value = input_json.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise VideoTaskRetryNotAllowed(f"Pipeline job input is missing string list '{key}'.")
    return value
