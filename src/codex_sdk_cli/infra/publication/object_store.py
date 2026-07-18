from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import BinaryIO, Protocol, cast
from urllib.parse import urlparse

from fastapi.concurrency import run_in_threadpool
from minio import Minio
from minio.error import MinioException, S3Error
from typing_extensions import override

from codex_sdk_cli.domains.publication.exceptions import PublicationObjectStoreError
from codex_sdk_cli.domains.publication.ports import (
    PublicationObjectLocation,
    PublicationObjectStat,
    PublicationObjectStorePort,
)


class ObjectWriteResultLike(Protocol):
    etag: str | None


class ObjectStatLike(Protocol):
    size: int
    etag: str | None
    last_modified: datetime | None


class ObjectReadResponseLike(Protocol):
    def read(self, amt: int | None = None) -> bytes: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class S3CompatibleClient(Protocol):
    def bucket_exists(self, bucket_name: str) -> bool: ...

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, list[str] | str | tuple[str]] | None = None,
    ) -> ObjectWriteResultLike: ...

    def get_object(self, bucket_name: str, object_name: str) -> ObjectReadResponseLike: ...

    def stat_object(self, bucket_name: str, object_name: str) -> ObjectStatLike: ...


class S3CompatiblePublicationObjectStore(PublicationObjectStorePort):
    def __init__(
        self,
        *,
        client: S3CompatibleClient,
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
        region: str = "auto",
    ) -> S3CompatiblePublicationObjectStore:
        endpoint, secure = _endpoint_and_secure(endpoint, default_secure=secure)
        return cls(
            client=cast(
                S3CompatibleClient,
                Minio(
                    endpoint,
                    access_key=access_key,
                    secret_key=secret_key,
                    secure=secure,
                    region=region,
                ),
            ),
            bucket=bucket,
            public_base_url=public_base_url,
        )

    @override
    async def put_bytes(
        self,
        *,
        object_key: str,
        payload: bytes,
        content_type: str = "application/octet-stream",
        cache_control: str | None = None,
    ) -> PublicationObjectLocation:
        try:
            result = await run_in_threadpool(
                self._put_sync,
                object_key,
                payload,
                content_type,
                cache_control,
            )
        except (MinioException, OSError) as exc:
            raise PublicationObjectStoreError("Publication object write failed.") from exc
        return PublicationObjectLocation(
            bucket=self._bucket,
            object_key=object_key,
            public_url=self.public_url(object_key),
            etag=result.etag,
        )

    @override
    async def get_bytes(self, *, object_key: str) -> bytes:
        try:
            return await run_in_threadpool(self._get_sync, object_key)
        except (MinioException, OSError) as exc:
            raise PublicationObjectStoreError("Publication object read failed.") from exc

    @override
    async def stat_object(self, *, object_key: str) -> PublicationObjectStat | None:
        try:
            result = await run_in_threadpool(self._stat_sync, object_key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return None
            raise PublicationObjectStoreError("Publication object stat failed.") from exc
        except (MinioException, OSError) as exc:
            raise PublicationObjectStoreError("Publication object stat failed.") from exc
        return PublicationObjectStat(
            bucket=self._bucket,
            object_key=object_key,
            byte_size=result.size,
            etag=result.etag,
            last_modified=result.last_modified,
        )

    def public_url(self, object_key: str) -> str:
        return f"{self._public_base_url}/{object_key.lstrip('/')}"

    def _put_sync(
        self,
        object_key: str,
        payload: bytes,
        content_type: str,
        cache_control: str | None,
    ) -> ObjectWriteResultLike:
        self._ensure_bucket()
        metadata: dict[str, list[str] | str | tuple[str]] | None = (
            {"Cache-Control": cache_control} if cache_control else None
        )
        return self._client.put_object(
            self._bucket,
            object_key,
            BytesIO(payload),
            len(payload),
            content_type=content_type,
            metadata=metadata,
        )

    def _get_sync(self, object_key: str) -> bytes:
        self._ensure_bucket()
        response = self._client.get_object(self._bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def _stat_sync(self, object_key: str) -> ObjectStatLike:
        self._ensure_bucket()
        return self._client.stat_object(self._bucket, object_key)

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            raise PublicationObjectStoreError("Publication object bucket is unavailable.")


def _endpoint_and_secure(endpoint: str, *, default_secure: bool) -> tuple[str, bool]:
    parsed = urlparse(endpoint)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return parsed.netloc, parsed.scheme == "https"
    return endpoint, default_secure
