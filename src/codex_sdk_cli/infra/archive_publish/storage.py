from __future__ import annotations

from io import BytesIO
from typing import BinaryIO, Protocol
from urllib.parse import urlparse

from fastapi.concurrency import run_in_threadpool
from minio import Minio
from minio.error import MinioException
from typing_extensions import override

from codex_sdk_cli.domains.archive_publish.exceptions import ArchivePublishStorageError
from codex_sdk_cli.domains.archive_publish.ports import (
    ArchiveObjectLocation,
    ArchiveObjectSaveRequest,
    ArchivePublishStoragePort,
)


class R2ClientLike(Protocol):
    def bucket_exists(self, bucket_name: str) -> bool:
        """Return whether a bucket exists."""

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, list[str] | str | tuple[str]] | None = None,
    ) -> object:
        """Upload one object."""


class R2ArchivePublishStorage(ArchivePublishStoragePort):
    def __init__(
        self,
        *,
        client: R2ClientLike,
        bucket: str,
        public_base_url: str,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip("/")

    @classmethod
    def from_values(
        cls,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        public_base_url: str,
        secure: bool,
    ) -> R2ArchivePublishStorage:
        endpoint, secure = _endpoint_and_secure(
            endpoint,
            default_secure=secure,
        )
        return cls(
            client=Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
                region="auto",
            ),
            bucket=bucket,
            public_base_url=public_base_url,
        )

    @override
    async def save_json(self, request: ArchiveObjectSaveRequest) -> ArchiveObjectLocation:
        try:
            await run_in_threadpool(self._save_sync, request)
        except MinioException as exc:
            raise ArchivePublishStorageError("Archive publish storage write failed.") from exc
        return ArchiveObjectLocation(
            bucket=self._bucket,
            object_key=request.object_key,
            public_url=f"{self._public_base_url}/{request.object_key.lstrip('/')}",
        )

    def _save_sync(self, request: ArchiveObjectSaveRequest) -> None:
        if not self._client.bucket_exists(self._bucket):
            raise ArchivePublishStorageError("Archive publish R2 bucket is not available.")
        self._client.put_object(
            self._bucket,
            request.object_key,
            BytesIO(request.payload),
            len(request.payload),
            content_type=request.content_type,
            metadata={"Cache-Control": request.cache_control},
        )


def _endpoint_and_secure(endpoint: str, *, default_secure: bool) -> tuple[str, bool]:
    parsed = urlparse(endpoint)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return parsed.netloc, parsed.scheme == "https"
    return endpoint, default_secure
