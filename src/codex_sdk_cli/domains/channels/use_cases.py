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
from codex_sdk_cli.domains.streamers.ports import StreamerRepositoryPort
from codex_sdk_cli.domains.youtube_data.exceptions import (
    InvalidYouTubeChannelHandle,
    YouTubeDataChannelResolutionError,
)
from codex_sdk_cli.domains.youtube_data.ports import YouTubeDataClientPort

from .exceptions import ChannelAlreadyExists, ChannelNotFound
from .ports import ChannelCreate, ChannelRecord, ChannelRepositoryPort, ChannelUpdate
from .schemas import (
    ChannelCreateRequest,
    ChannelResponse,
    ChannelUpdateRequest,
    DeleteResponse,
    ResolveYouTubeChannelRequest,
    ResolveYouTubeChannelResponse,
)


class CreateChannelUseCase:
    def __init__(
        self,
        channels: ChannelRepositoryPort,
        streamers: StreamerRepositoryPort,
    ) -> None:
        self._channels = channels
        self._streamers = streamers

    async def execute(self, streamer_id: int, request: ChannelCreateRequest) -> ChannelResponse:
        await _ensure_streamer_exists(self._streamers, streamer_id)
        if request.youtube_channel_id is not None:
            existing = await self._channels.get_channel_by_youtube_channel_id(
                request.youtube_channel_id
            )
            if existing is not None:
                _ensure_channel_belongs_to_streamer(existing, streamer_id)
                return _channel_response(existing)

        record = await self._channels.create_channel(
            ChannelCreate(
                streamer_id=streamer_id,
                handle=request.handle,
                name=request.name,
                youtube_channel_id=request.youtube_channel_id,
                uploads_playlist_id=None,
            )
        )
        return _channel_response(record)


class ListChannelsUseCase:
    def __init__(self, channels: ChannelRepositoryPort) -> None:
        self._channels = channels

    async def execute(self) -> list[ChannelResponse]:
        records = await self._channels.list_channels()
        return [_channel_response(record) for record in records]


class ListStreamerChannelsUseCase:
    def __init__(
        self,
        channels: ChannelRepositoryPort,
        streamers: StreamerRepositoryPort,
    ) -> None:
        self._channels = channels
        self._streamers = streamers

    async def execute(self, streamer_id: int) -> list[ChannelResponse]:
        await _ensure_streamer_exists(self._streamers, streamer_id)
        records = await self._channels.list_channels(streamer_id=streamer_id)
        return [_channel_response(record) for record in records]


class GetChannelUseCase:
    def __init__(self, channels: ChannelRepositoryPort) -> None:
        self._channels = channels

    async def execute(self, channel_id: int) -> ChannelResponse:
        record = await self._channels.get_channel(channel_id)
        if record is None:
            raise ChannelNotFound("Channel not found.")
        return _channel_response(record)


class UpdateChannelUseCase:
    def __init__(self, channels: ChannelRepositoryPort) -> None:
        self._channels = channels

    async def execute(self, channel_id: int, request: ChannelUpdateRequest) -> ChannelResponse:
        fields_set = request.model_fields_set
        if request.youtube_channel_id is not None:
            existing = await self._channels.get_channel_by_youtube_channel_id(
                request.youtube_channel_id
            )
            if existing is not None and existing.id != channel_id:
                raise ChannelAlreadyExists("YouTube channel already exists.")

        update = ChannelUpdate(
            handle=request.handle if "handle" in fields_set else None,
            name=request.name if "name" in fields_set else None,
            youtube_channel_id=request.youtube_channel_id,
            youtube_channel_id_set="youtube_channel_id" in fields_set,
        )
        record = await self._channels.update_channel(channel_id, update)
        if record is None:
            raise ChannelNotFound("Channel not found.")
        return _channel_response(record)


class DeleteChannelUseCase:
    def __init__(self, channels: ChannelRepositoryPort) -> None:
        self._channels = channels

    async def execute(self, channel_id: int) -> DeleteResponse:
        deleted = await self._channels.delete_channel(channel_id)
        if not deleted:
            raise ChannelNotFound("Channel not found.")
        return DeleteResponse(success=True)


class ResolveYouTubeChannelUseCase:
    def __init__(
        self,
        client: YouTubeDataClientPort,
        channels: ChannelRepositoryPort,
        streamers: StreamerRepositoryPort,
        pipeline_jobs: PipelineJobRepositoryPort,
    ) -> None:
        self._client = client
        self._channels = channels
        self._streamers = streamers
        self._pipeline_jobs = pipeline_jobs

    async def execute(
        self,
        streamer_id: int,
        request: ResolveYouTubeChannelRequest,
    ) -> ResolveYouTubeChannelResponse:
        handle = _normalize_request_handle(request.handle)
        await _ensure_streamer_exists(self._streamers, streamer_id)

        input_json: dict[str, object] = {"streamerId": streamer_id, "handle": handle}
        job = await self._pipeline_jobs.create_job(
            PipelineJobCreate(
                step="channel_resolve",
                status="running",
                subject_type="streamer",
                subject_id=streamer_id,
                external_key=handle,
                input_json=input_json,
                input_hash=_input_hash(input_json),
            )
        )
        attempt = await self._pipeline_jobs.create_attempt(job_id=job.id)

        normalized_request = ResolveYouTubeChannelRequest(handle=handle)
        return await self.execute_job_attempt(
            job,
            attempt,
            streamer_id=streamer_id,
            request=normalized_request,
        )

    async def execute_job_attempt(
        self,
        job: PipelineJobRecord,
        attempt: PipelineJobAttemptRecord,
        *,
        streamer_id: int,
        request: ResolveYouTubeChannelRequest,
    ) -> ResolveYouTubeChannelResponse:
        try:
            await _ensure_streamer_exists(self._streamers, streamer_id)
            result = await self._client.resolve_youtube_channel_by_handle(
                request.handle,
                pipeline_job_attempt_id=attempt.id,
            )

            existing = await self._channels.get_channel_by_youtube_channel_id(
                result.youtube_channel_id
            )
            if existing is not None:
                _ensure_channel_belongs_to_streamer(existing, streamer_id)
                record = await _update_uploads_playlist_if_needed(
                    self._channels,
                    existing,
                    result.uploads_playlist_id,
                )
            else:
                record = await self._channels.create_channel(
                    ChannelCreate(
                        streamer_id=streamer_id,
                        handle=request.handle,
                        name=result.title,
                        youtube_channel_id=result.youtube_channel_id,
                        uploads_playlist_id=result.uploads_playlist_id,
                        source_api_call_id=result.source_api_call_id,
                        source_job_id=job.id,
                    )
                )
            response = _resolve_response(
                record,
                job_id=job.id,
                job_attempt_id=attempt.id,
                source_api_call_id=result.source_api_call_id,
            )
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


async def _ensure_streamer_exists(repository: StreamerRepositoryPort, streamer_id: int) -> None:
    if await repository.get_streamer(streamer_id) is None:
        raise StreamerNotFound("Streamer not found.")


def _ensure_channel_belongs_to_streamer(record: ChannelRecord, streamer_id: int) -> None:
    if record.streamer_id != streamer_id:
        raise ChannelAlreadyExists("YouTube channel already belongs to another streamer.")


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


def _channel_response(record: ChannelRecord) -> ChannelResponse:
    return ChannelResponse(
        id=record.id,
        streamerId=record.streamer_id,
        handle=record.handle,
        name=record.name,
        youtubeChannelId=record.youtube_channel_id,
        uploadsPlaylistId=record.uploads_playlist_id,
        sourceApiCallId=record.source_api_call_id,
        sourceJobId=record.source_job_id,
    )


def _resolve_response(
    record: ChannelRecord,
    *,
    job_id: int,
    job_attempt_id: int,
    source_api_call_id: int,
) -> ResolveYouTubeChannelResponse:
    if record.youtube_channel_id is None:
        raise YouTubeDataChannelResolutionError(
            "Resolved channel row did not include a YouTube channel ID."
        )
    if record.uploads_playlist_id is None:
        raise YouTubeDataChannelResolutionError(
            "Resolved channel row did not include an uploads playlist ID."
        )
    return ResolveYouTubeChannelResponse(
        channelId=record.id,
        streamerId=record.streamer_id,
        handle=record.handle,
        name=record.name,
        youtubeChannelId=record.youtube_channel_id,
        uploadsPlaylistId=record.uploads_playlist_id,
        sourceApiCallId=source_api_call_id,
        jobId=job_id,
        jobAttemptId=job_attempt_id,
    )


async def _update_uploads_playlist_if_needed(
    repository: ChannelRepositoryPort,
    record: ChannelRecord,
    uploads_playlist_id: str,
) -> ChannelRecord:
    if record.uploads_playlist_id == uploads_playlist_id:
        return record
    updated = await repository.update_uploads_playlist_id(record.id, uploads_playlist_id)
    if updated is None:
        raise ChannelNotFound("Channel not found.")
    return updated
