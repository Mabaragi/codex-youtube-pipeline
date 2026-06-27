from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

JsonObject = dict[str, object]
ValidationStatus = Literal["not_validated", "valid", "invalid"]


@dataclass(frozen=True, slots=True)
class ExternalApiCallStorageLocation:
    bucket: str
    object_name: str
    uri: str


@dataclass(frozen=True, slots=True)
class ExternalApiCallStorageSaveRequest:
    object_name: str
    payload: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class ExternalApiCallCreate:
    provider: str
    operation: str
    request_method: str
    request_url: str
    request_params: JsonObject
    request_body: JsonObject | None
    response_status_code: int | None
    response_headers: JsonObject
    response_storage_bucket: str | None
    response_storage_object_name: str | None
    response_storage_uri: str | None
    response_sha256: str | None
    schema_name: str | None
    schema_version: str | None
    validation_status: ValidationStatus
    validation_error: str | None
    duration_ms: int
    quota_cost: int | None
    pipeline_job_attempt_id: int | None = None


@dataclass(frozen=True, slots=True)
class ExternalApiCallRecord:
    id: int
    provider: str
    operation: str
    request_method: str
    request_url: str
    request_params: JsonObject
    request_body: JsonObject | None
    response_status_code: int | None
    response_headers: JsonObject
    response_storage_bucket: str | None
    response_storage_object_name: str | None
    response_storage_uri: str | None
    response_sha256: str | None
    schema_name: str | None
    schema_version: str | None
    validation_status: ValidationStatus
    validation_error: str | None
    duration_ms: int
    quota_cost: int | None
    created_at: datetime
    pipeline_job_attempt_id: int | None = None


@dataclass(frozen=True, slots=True)
class ExternalApiCallRecordRequest:
    provider: str
    operation: str
    request_method: str
    request_url: str
    request_params: JsonObject
    request_body: JsonObject | None
    response_status_code: int | None
    response_headers: JsonObject
    response_body: bytes | None
    schema_name: str | None
    schema_version: str | None
    validation_status: ValidationStatus
    validation_error: str | None
    duration_ms: int
    quota_cost: int | None
    pipeline_job_attempt_id: int | None = None


class ExternalApiCallStoragePort(Protocol):
    def location_for(self, object_name: str) -> ExternalApiCallStorageLocation:
        """Return the object storage location for a raw response object key."""

    async def save_raw_response(
        self,
        request: ExternalApiCallStorageSaveRequest,
    ) -> ExternalApiCallStorageLocation:
        """Persist one raw external API response payload."""


class ExternalApiCallRepositoryPort(Protocol):
    async def create_external_api_call(
        self,
        record: ExternalApiCallCreate,
    ) -> ExternalApiCallRecord:
        """Persist one external API call metadata row."""


class ExternalApiCallRecorderPort(Protocol):
    async def record_call(self, request: ExternalApiCallRecordRequest) -> ExternalApiCallRecord:
        """Persist raw response object storage and metadata for one external API call."""
