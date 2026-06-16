from __future__ import annotations

from io import BytesIO
from typing import BinaryIO, Protocol

from fastapi.concurrency import run_in_threadpool
from minio import Minio
from minio.error import MinioException, S3Error
from typing_extensions import override

from codex_sdk_cli.domains.external_api_calls.exceptions import (
    ExternalApiCallConfigurationError,
    ExternalApiCallStorageError,
)
from codex_sdk_cli.domains.external_api_calls.ports import (
    ExternalApiCallStorageLocation,
    ExternalApiCallStoragePort,
    ExternalApiCallStorageSaveRequest,
)
from codex_sdk_cli.settings import CliSettings


class MinioClientLike(Protocol):
    def bucket_exists(self, bucket_name: str) -> bool:
        """Return whether a bucket exists."""

    def make_bucket(self, bucket_name: str) -> None:
        """Create a bucket."""

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> object:
        """Upload one object."""


class MinioExternalApiCallStorage(ExternalApiCallStoragePort):
    def __init__(self, client: MinioClientLike, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: CliSettings) -> MinioExternalApiCallStorage:
        if (
            settings.transcript_minio_endpoint is None
            or settings.transcript_minio_access_key is None
            or settings.transcript_minio_secret_key is None
            or settings.transcript_minio_bucket is None
        ):
            raise ExternalApiCallConfigurationError(
                "External API raw storage is not configured."
            )

        return cls(
            Minio(
                settings.transcript_minio_endpoint,
                access_key=settings.transcript_minio_access_key.get_secret_value(),
                secret_key=settings.transcript_minio_secret_key.get_secret_value(),
                secure=settings.transcript_minio_secure,
            ),
            settings.transcript_minio_bucket,
        )

    @override
    def location_for(self, object_name: str) -> ExternalApiCallStorageLocation:
        return ExternalApiCallStorageLocation(
            bucket=self._bucket,
            object_name=object_name,
            uri=f"s3://{self._bucket}/{object_name}",
        )

    @override
    async def save_raw_response(
        self,
        request: ExternalApiCallStorageSaveRequest,
    ) -> ExternalApiCallStorageLocation:
        try:
            await run_in_threadpool(
                self._save_sync,
                request.object_name,
                request.payload,
                request.content_type,
            )
        except MinioException as exc:
            raise ExternalApiCallStorageError("External API raw storage write failed.") from exc
        return self.location_for(request.object_name)

    def _save_sync(self, object_name: str, payload: bytes, content_type: str) -> None:
        if not self._client.bucket_exists(self._bucket):
            try:
                self._client.make_bucket(self._bucket)
            except S3Error as exc:
                if exc.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                    raise

        self._client.put_object(
            self._bucket,
            object_name,
            BytesIO(payload),
            len(payload),
            content_type=content_type,
        )
