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
    YouTubeDataClientPort,
)

from .schemas import YouTubeChannelsListResponse

YOUTUBE_CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"


class YouTubeDataClient(YouTubeDataClientPort):
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        api_key: str,
        api_call_recorder: ExternalApiCallRecorderPort,
        channels_endpoint: str = YOUTUBE_CHANNELS_ENDPOINT,
    ) -> None:
        self._http_client = http_client
        self._api_key = api_key
        self._api_call_recorder = api_call_recorder
        self._channels_endpoint = channels_endpoint

    @override
    async def resolve_youtube_channel_by_handle(
        self,
        handle: str,
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeChannelResolution:
        request_params: dict[str, str] = {
            "part": "id,snippet",
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
                response_status_code=None,
                response_headers={},
                response_body=None,
                validation_status="invalid",
                validation_error=exc.__class__.__name__,
                duration_ms=_duration_ms(started),
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise YouTubeDataUpstreamError("YouTube Data API request failed.") from exc

        if response.status_code >= 400:
            await self._record_response(
                response=response,
                request_params=request_params,
                validation_status="not_validated",
                validation_error=None,
                duration_ms=_duration_ms(started),
                schema_name=None,
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise YouTubeDataUpstreamError("YouTube Data API request failed upstream.")

        try:
            payload = _channels_list_response(response)
        except YouTubeDataUpstreamError as exc:
            await self._record_response(
                response=response,
                request_params=request_params,
                validation_status="invalid",
                validation_error=str(exc),
                duration_ms=_duration_ms(started),
                schema_name="YouTubeChannelsListResponse",
                pipeline_job_attempt_id=pipeline_job_attempt_id,
            )
            raise

        api_call = await self._record_response(
            response=response,
            request_params=request_params,
            validation_status="valid",
            validation_error=None,
            duration_ms=_duration_ms(started),
            schema_name="YouTubeChannelsListResponse",
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )
        if not payload.items:
            raise YouTubeDataChannelNotFound("YouTube channel was not found for this handle.")

        channel = payload.items[0]

        return YouTubeChannelResolution(
            handle=handle,
            youtube_channel_id=channel.youtube_channel_id,
            title=channel.snippet.title,
            source_api_call_id=api_call.id,
        )

    async def _record_response(
        self,
        *,
        response: httpx.Response,
        request_params: dict[str, str],
        validation_status: ValidationStatus,
        validation_error: str | None,
        duration_ms: int,
        schema_name: str | None,
        pipeline_job_attempt_id: int | None,
    ) -> ExternalApiCallRecord:
        return await self._record_call(
            request_params=request_params,
            response_status_code=response.status_code,
            response_headers=dict(response.headers),
            response_body=response.content,
            validation_status=validation_status,
            validation_error=validation_error,
            duration_ms=duration_ms,
            schema_name=schema_name,
            pipeline_job_attempt_id=pipeline_job_attempt_id,
        )

    async def _record_call(
        self,
        *,
        request_params: dict[str, str],
        response_status_code: int | None,
        response_headers: dict[str, object],
        response_body: bytes | None,
        validation_status: ValidationStatus,
        validation_error: str | None,
        duration_ms: int,
        schema_name: str | None = None,
        pipeline_job_attempt_id: int | None = None,
    ) -> ExternalApiCallRecord:
        return await self._api_call_recorder.record_call(
            ExternalApiCallRecordRequest(
                provider="youtube_data",
                operation="channels.list",
                request_method="GET",
                request_url=self._channels_endpoint,
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
                quota_cost=1,
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


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
