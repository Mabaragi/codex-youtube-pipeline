from __future__ import annotations

import hashlib
import json

from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobAttemptRecord,
    PipelineJobCreate,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
)
from codex_sdk_cli.domains.streamers.exceptions import StreamerNotFound
from codex_sdk_cli.domains.streamers.ports import (
    ChannelCreate,
    ChannelRecord,
    StreamerRepositoryPort,
)

from .exceptions import InvalidYouTubeChannelHandle, YouTubeDataChannelResolutionError
from .ports import YouTubeDataClientPort
from .schemas import ResolveYouTubeChannelRequest, ResolveYouTubeChannelResponse


class ResolveYouTubeChannelUseCase:
    def __init__(
        self,
        client: YouTubeDataClientPort,
        repository: StreamerRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
    ) -> None:
        self._client = client
        self._repository = repository
        self._pipeline_jobs = pipeline_jobs

    async def execute(
        self,
        request: ResolveYouTubeChannelRequest,
    ) -> ResolveYouTubeChannelResponse:
        handle = _normalize_request_handle(request.handle)
        if await self._repository.get_streamer(request.streamer_id) is None:
            raise StreamerNotFound("Streamer not found.")

        input_json: dict[str, object] = {"streamerId": request.streamer_id, "handle": handle}
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step="channel_resolve",
                status="running",
                subject_type="streamer",
                subject_id=request.streamer_id,
                external_key=handle,
                input_json=input_json,
                input_hash=_input_hash(input_json),
            )
        )
        attempt = await self._pipeline_jobs.create_attempt(job_id=job.id)

        normalized_request = ResolveYouTubeChannelRequest(
            streamerId=request.streamer_id,
            handle=handle,
        )
        return await self.execute_job_attempt(job, attempt, normalized_request)

    async def execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        request: ResolveYouTubeChannelRequest,
    ) -> ResolveYouTubeChannelResponse:
        try:
            if await self._repository.get_streamer(request.streamer_id) is None:
                raise StreamerNotFound("Streamer not found.")
            result = await self._client.resolve_youtube_channel_by_handle(
                request.handle,
                pipeline_job_attempt_id=attempt.id,
            )

            record = await self._repository.create_channel(
                ChannelCreate(
                    streamer_id=request.streamer_id,
                    handle=request.handle,
                    name=result.title,
                    youtube_channel_id=result.youtube_channel_id,
                    source_api_call_id=result.source_api_call_id,
                    source_job_id=job.id,
                )
            )
            response = _response(record, job_id=job.id, job_attempt_id=attempt.id)
        except Exception as exc:
            await self._pipeline_jobs.mark_attempt_failed(
                attempt.id,
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
            )
            await self._pipeline_jobs.mark_job_failed(job.id)
            raise
        await self._pipeline_jobs.mark_attempt_succeeded(
            attempt.id,
            output_json=response.model_dump(by_alias=True),
        )
        await self._pipeline_jobs.mark_job_succeeded(job.id)
        return response


def _normalize_request_handle(handle: str) -> str:
    normalized = handle.strip()
    if not normalized.removeprefix("@").strip():
        raise InvalidYouTubeChannelHandle("YouTube channel handle cannot be empty.")
    return normalized


def _input_hash(input_json: dict[str, object]) -> str:
    payload = json.dumps(
        input_json,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _response(
    record: ChannelRecord,
    *,
    job_id: int,
    job_attempt_id: int,
) -> ResolveYouTubeChannelResponse:
    if record.youtube_channel_id is None:
        raise YouTubeDataChannelResolutionError(
            "Created channel row did not include a YouTube channel ID."
        )
    if record.source_api_call_id is None:
        raise YouTubeDataChannelResolutionError(
            "Created channel row did not include a source API call ID."
        )
    return ResolveYouTubeChannelResponse(
        channelId=record.id,
        streamerId=record.streamer_id,
        handle=record.handle,
        name=record.name,
        youtubeChannelId=record.youtube_channel_id,
        sourceApiCallId=record.source_api_call_id,
        jobId=job_id,
        jobAttemptId=job_attempt_id,
    )
