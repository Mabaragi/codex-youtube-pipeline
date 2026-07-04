from __future__ import annotations

from time import perf_counter
from typing import Any

import httpx
from pydantic import ValidationError
from typing_extensions import override

from codex_sdk_cli.domains.external_api_calls.ports import (
    ExternalApiCallRecord,
    ExternalApiCallRecorderPort,
    ExternalApiCallRecordRequest,
    ValidationStatus,
)
from codex_sdk_cli.domains.youtube_data.exceptions import (
    YouTubeDataChannelNotFound,
    YouTubeDataUpstreamError,
)
from codex_sdk_cli.domains.youtube_data.ports import (
    YouTubeChannelResolution,
    YouTubeChannelUploadsPlaylist,
    YouTubeDataClientPort,
    YouTubeVideoDetails,
    YouTubeVideoDetailsBatch,
    YouTubeVideoListing,
    YouTubeVideoListingPage,
)

from .schemas import (
    YouTubeChannelsListResponse,
    YouTubePlaylistItemResource,
    YouTubePlaylistItemsListResponse,
    YouTubeVideoResource,
    YouTubeVideosListResponse,
)

YOUTUBE_CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_PLAYLIST_ITEMS_ENDPOINT = "https://www.googleapis.com/youtube/v3/playlistItems"
YOUTUBE_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeDataClient(YouTubeDataClientPort):
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        api_key: str,
        api_call_recorder: ExternalApiCallRecorderPort,
        channels_endpoint: str = YOUTUBE_CHANNELS_ENDPOINT,
        playlist_items_endpoint: str = YOUTUBE_PLAYLIST_ITEMS_ENDPOINT,
        videos_endpoint: str = YOUTUBE_VIDEOS_ENDPOINT,
    ) -> None:
        self._http_client = http_client
        self._api_key = api_key
        self._api_call_recorder = api_call_recorder
        self._channels_endpoint = channels_endpoint
        self._playlist_items_endpoint = playlist_items_endpoint
        self._videos_endpoint = videos_endpoint

    @override
    async def resolve_youtube_channel_by_handle(
        self,
        handle: str,
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeChannelResolution:
        request_params: dict[str, str] = {
            "part": "id,snippet,contentDetails",
            "forHandle": handle,
        }
        started = perf_counter()
        try:
            response = await self._http_client.get(
                self._channels_endpoint,
                params={**request_params, "key": self._api_key},
            )
        except httpx.RequestError as exc:
            await self._record_call(
                request_params=request_params,
                request_url=self._channels_endpoint,
                operation="channels.list",
                response_status_code=None,
                response_headers={},
                response_body=None,
                validation_status="invalid",
                validation_error=exc.__class__.__name__,
                duration_ms=_duration_ms(started),
                quota_cost=1,
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise YouTubeDataUpstreamError("YouTube Data API request failed.") from exc

        if response.status_code >= 400:
            await self._record_response(
                response=response,
                request_params=request_params,
                request_url=self._channels_endpoint,
                operation="channels.list",
                validation_status="not_validated",
                validation_error=None,
                duration_ms=_duration_ms(started),
                schema_name=None,
                quota_cost=1,
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise YouTubeDataUpstreamError("YouTube Data API request failed upstream.")

        try:
            payload = _channels_list_response(response)
        except YouTubeDataUpstreamError as exc:
            await self._record_response(
                response=response,
                request_params=request_params,
                request_url=self._channels_endpoint,
                operation="channels.list",
                validation_status="invalid",
                validation_error=str(exc),
                duration_ms=_duration_ms(started),
                schema_name="YouTubeChannelsListResponse",
                quota_cost=1,
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise

        api_call = await self._record_response(
            response=response,
            request_params=request_params,
            request_url=self._channels_endpoint,
            operation="channels.list",
            validation_status="valid",
            validation_error=None,
            duration_ms=_duration_ms(started),
            schema_name="YouTubeChannelsListResponse",
            quota_cost=1,
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )
        if not payload.items:
            raise YouTubeDataChannelNotFound("YouTube channel was not found for this handle.")

        channel = payload.items[0]

        return YouTubeChannelResolution(
            handle=handle,
            youtube_channel_id=channel.youtube_channel_id,
            title=channel.snippet.title,
            uploads_playlist_id=channel.content_details.related_playlists.uploads,
            source_api_call_id=api_call.id,
        )

    @override
    async def get_channel_uploads_playlist(
        self,
        youtube_channel_id: str,
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeChannelUploadsPlaylist:
        request_params: dict[str, str] = {
            "part": "id,snippet,contentDetails",
            "id": youtube_channel_id,
        }

        response, duration_ms = await self._get_response(
            request_url=self._channels_endpoint,
            operation="channels.list",
            request_params=request_params,
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )
        try:
            payload = _channels_list_response(response)
        except YouTubeDataUpstreamError as exc:
            await self._record_response(
                response=response,
                request_params=request_params,
                request_url=self._channels_endpoint,
                operation="channels.list",
                validation_status="invalid",
                validation_error=str(exc),
                duration_ms=duration_ms,
                schema_name="YouTubeChannelsListResponse",
                quota_cost=1,
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise

        api_call = await self._record_response(
            response=response,
            request_params=request_params,
            request_url=self._channels_endpoint,
            operation="channels.list",
            validation_status="valid",
            validation_error=None,
            duration_ms=duration_ms,
            schema_name="YouTubeChannelsListResponse",
            quota_cost=1,
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )
        if not payload.items:
            raise YouTubeDataChannelNotFound("YouTube channel was not found for this ID.")
        channel = payload.items[0]
        return YouTubeChannelUploadsPlaylist(
            youtube_channel_id=channel.youtube_channel_id,
            uploads_playlist_id=channel.content_details.related_playlists.uploads,
            source_api_call_id=api_call.id,
        )

    @override
    async def list_upload_playlist_videos(
        self,
        uploads_playlist_id: str,
        *,
        page_token: str | None = None,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoListingPage:
        request_params: dict[str, str] = {
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": "50",
        }
        if page_token is not None:
            request_params["pageToken"] = page_token

        response, duration_ms = await self._get_response(
            request_url=self._playlist_items_endpoint,
            operation="playlistItems.list",
            request_params=request_params,
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )
        try:
            payload = _playlist_items_list_response(response)
        except YouTubeDataUpstreamError as exc:
            await self._record_response(
                response=response,
                request_params=request_params,
                request_url=self._playlist_items_endpoint,
                operation="playlistItems.list",
                validation_status="invalid",
                validation_error=str(exc),
                duration_ms=duration_ms,
                schema_name="YouTubePlaylistItemsListResponse",
                quota_cost=1,
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise

        api_call = await self._record_response(
            response=response,
            request_params=request_params,
            request_url=self._playlist_items_endpoint,
            operation="playlistItems.list",
            validation_status="valid",
            validation_error=None,
            duration_ms=duration_ms,
            schema_name="YouTubePlaylistItemsListResponse",
            quota_cost=1,
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )
        return YouTubeVideoListingPage(
            videos=tuple(
                _video_listing(item, source_api_call_id=api_call.id)
                for item in payload.items
            ),
            next_page_token=payload.next_page_token,
            source_api_call_id=api_call.id,
        )

    @override
    async def get_video_details(
        self,
        youtube_video_ids: tuple[str, ...],
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeVideoDetailsBatch:
        if not youtube_video_ids:
            return YouTubeVideoDetailsBatch(videos=(), source_api_call_id=0)

        request_params: dict[str, str] = {
            "part": "contentDetails,status",
            "id": ",".join(youtube_video_ids),
        }
        response, duration_ms = await self._get_response(
            request_url=self._videos_endpoint,
            operation="videos.list",
            request_params=request_params,
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )
        try:
            payload = _videos_list_response(response)
        except YouTubeDataUpstreamError as exc:
            await self._record_response(
                response=response,
                request_params=request_params,
                request_url=self._videos_endpoint,
                operation="videos.list",
                validation_status="invalid",
                validation_error=str(exc),
                duration_ms=duration_ms,
                schema_name="YouTubeVideosListResponse",
                quota_cost=1,
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise

        api_call = await self._record_response(
            response=response,
            request_params=request_params,
            request_url=self._videos_endpoint,
            operation="videos.list",
            validation_status="valid",
            validation_error=None,
            duration_ms=duration_ms,
            schema_name="YouTubeVideosListResponse",
            quota_cost=1,
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )
        return YouTubeVideoDetailsBatch(
            videos=tuple(
                _video_details(item, source_api_call_id=api_call.id)
                for item in payload.items
            ),
            source_api_call_id=api_call.id,
        )

    async def _get_response(
        self,
        *,
        request_url: str,
        operation: str,
        request_params: dict[str, str],
        pipeline_job_attempt_id: int | None,
    ) -> tuple[httpx.Response, int]:
        started = perf_counter()
        try:
            response = await self._http_client.get(
                request_url,
                params={**request_params, "key": self._api_key},
            )
        except httpx.RequestError as exc:
            duration_ms = _duration_ms(started)
            await self._record_call(
                request_params=request_params,
                request_url=request_url,
                operation=operation,
                response_status_code=None,
                response_headers={},
                response_body=None,
                validation_status="invalid",
                validation_error=exc.__class__.__name__,
                duration_ms=duration_ms,
                quota_cost=_quota_cost(operation),
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise YouTubeDataUpstreamError("YouTube Data API request failed.") from exc

        duration_ms = _duration_ms(started)
        if response.status_code >= 400:
            await self._record_response(
                response=response,
                request_params=request_params,
                request_url=request_url,
                operation=operation,
                validation_status="not_validated",
                validation_error=None,
                duration_ms=duration_ms,
                schema_name=None,
                quota_cost=_quota_cost(operation),
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise YouTubeDataUpstreamError("YouTube Data API request failed upstream.")
        return response, duration_ms

    async def _record_response(
        self,
        *,
        response: httpx.Response,
        request_params: dict[str, str],
        request_url: str,
        operation: str,
        validation_status: ValidationStatus,
        validation_error: str | None,
        duration_ms: int,
        schema_name: str | None,
        quota_cost: int,
        pipeline_job_attempt_id: int | None,
    ) -> ExternalApiCallRecord:
        return await self._record_call(
            request_params=request_params,
            request_url=request_url,
            operation=operation,
            response_status_code=response.status_code,
            response_headers=dict(response.headers),
            response_body=response.content,
            validation_status=validation_status,
            validation_error=validation_error,
            duration_ms=duration_ms,
            schema_name=schema_name,
            quota_cost=quota_cost,
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )

    async def _record_call(
        self,
        *,
        request_params: dict[str, str],
        request_url: str,
        operation: str,
        response_status_code: int | None,
        response_headers: dict[str, object],
        response_body: bytes | None,
        validation_status: ValidationStatus,
        validation_error: str | None,
        duration_ms: int,
        quota_cost: int,
        schema_name: str | None = None,
        pipeline_job_attempt_id: int | None = None,
    ) -> ExternalApiCallRecord:
        return await self._api_call_recorder.record_call(
            ExternalApiCallRecordRequest(
                provider="youtube_data",
                operation=operation,
                request_method="GET",
                request_url=request_url,
                request_params=dict(request_params),
                request_body=None,
                response_status_code=response_status_code,
                response_headers=response_headers,
                response_body=response_body,
                schema_name=schema_name,
                schema_version="v1",
                validation_status=validation_status,
                validation_error=validation_error,
                duration_ms=duration_ms,
                quota_cost=quota_cost,
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
        )


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise YouTubeDataUpstreamError("YouTube Data API response was invalid.") from exc
    if not isinstance(payload, dict):
        raise YouTubeDataUpstreamError("YouTube Data API response was invalid.")
    return payload


def _channels_list_response(response: httpx.Response) -> YouTubeChannelsListResponse:
    try:
        return YouTubeChannelsListResponse.model_validate(_json_object(response))
    except ValidationError as exc:
        raise YouTubeDataUpstreamError("YouTube Data API response was invalid.") from exc


def _playlist_items_list_response(response: httpx.Response) -> YouTubePlaylistItemsListResponse:
    try:
        return YouTubePlaylistItemsListResponse.model_validate(_json_object(response))
    except ValidationError as exc:
        raise YouTubeDataUpstreamError("YouTube Data API response was invalid.") from exc


def _videos_list_response(response: httpx.Response) -> YouTubeVideosListResponse:
    try:
        return YouTubeVideosListResponse.model_validate(_json_object(response))
    except ValidationError as exc:
        raise YouTubeDataUpstreamError("YouTube Data API response was invalid.") from exc


def _video_details(
    video: YouTubeVideoResource,
    *,
    source_api_call_id: int,
) -> YouTubeVideoDetails:
    content_details = video.content_details
    status = video.status
    return YouTubeVideoDetails(
        youtube_video_id=video.youtube_video_id,
        duration=content_details.duration if content_details is not None else None,
        is_embeddable=status.embeddable if status is not None else None,
        source_api_call_id=source_api_call_id,
    )


def _video_listing(
    item: YouTubePlaylistItemResource,
    *,
    source_api_call_id: int,
) -> YouTubeVideoListing:
    return YouTubeVideoListing(
        youtube_video_id=item.content_details.video_id,
        title=item.snippet.title,
        description=item.snippet.description,
        published_at=item.content_details.video_published_at,
        thumbnail_url=_best_thumbnail_url(item),
        source_api_call_id=source_api_call_id,
    )


def _best_thumbnail_url(item: YouTubePlaylistItemResource) -> str | None:
    for key in ("maxres", "standard", "high", "medium", "default"):
        thumbnail = item.snippet.thumbnails.get(key)
        if thumbnail is not None:
            return thumbnail.url
    return None


def _quota_cost(operation: str) -> int:
    return 1


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
