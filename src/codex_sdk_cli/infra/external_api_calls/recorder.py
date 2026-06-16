from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from typing_extensions import override

from codex_sdk_cli.domains.external_api_calls.ports import (
    ExternalApiCallCreate,
    ExternalApiCallRecord,
    ExternalApiCallRecorderPort,
    ExternalApiCallRecordRequest,
    ExternalApiCallRepositoryPort,
    ExternalApiCallStoragePort,
    ExternalApiCallStorageSaveRequest,
)


class ExternalApiCallRecorder(ExternalApiCallRecorderPort):
    def __init__(
        self,
        repository: ExternalApiCallRepositoryPort,
        storage: ExternalApiCallStoragePort,
        *,
        storage_prefix: str,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._storage_prefix = storage_prefix.strip("/")

    @override
    async def record_call(self, request: ExternalApiCallRecordRequest) -> ExternalApiCallRecord:
        response_sha256: str | None = None
        location = None
        if request.response_body is not None:
            response_sha256 = hashlib.sha256(request.response_body).hexdigest()
            object_name = self._object_name(
                provider=request.provider,
                operation=request.operation,
                response_sha256=response_sha256,
            )
            content_type = _content_type(request.response_headers)
            location = await self._storage.save_raw_response(
                ExternalApiCallStorageSaveRequest(
                    object_name=object_name,
                    payload=request.response_body,
                    content_type=content_type,
                )
            )

        return await self._repository.create_external_api_call(
            ExternalApiCallCreate(
                provider=request.provider,
                operation=request.operation,
                request_method=request.request_method,
                request_url=request.request_url,
                request_params=request.request_params,
                request_body=request.request_body,
                response_status_code=request.response_status_code,
                response_headers=request.response_headers,
                response_storage_bucket=location.bucket if location is not None else None,
                response_storage_object_name=location.object_name if location is not None else None,
                response_storage_uri=location.uri if location is not None else None,
                response_sha256=response_sha256,
                schema_name=request.schema_name,
                schema_version=request.schema_version,
                validation_status=request.validation_status,
                validation_error=request.validation_error,
                duration_ms=request.duration_ms,
                quota_cost=request.quota_cost,
                pipeline_job_attempt_id=request.pipeline_job_attempt_id,
            )
        )

    def _object_name(self, *, provider: str, operation: str, response_sha256: str) -> str:
        now = datetime.now(UTC)
        prefix = f"{self._storage_prefix}/" if self._storage_prefix else ""
        provider_slug = _slug(provider)
        operation_slug = _slug(operation)
        return (
            f"{prefix}{now:%Y/%m/%d}/{provider_slug}/"
            f"{operation_slug}-{response_sha256}.json"
        )


def _content_type(headers: dict[str, object]) -> str:
    value = headers.get("content-type")
    if isinstance(value, str) and value:
        return value.split(";", 1)[0]
    return "application/octet-stream"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or "unknown"
