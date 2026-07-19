from __future__ import annotations

import asyncio
import hashlib
import json
from io import BytesIO
from typing import BinaryIO, Protocol, cast
from urllib.parse import urlparse

from minio import Minio
from minio.error import MinioException, S3Error
from typing_extensions import override

from codex_sdk_cli.domains.evaluation.ports import (
    EvaluationObjectStorePort,
    EvaluationStoredObject,
    JsonObject,
)


class _StatLike(Protocol):
    size: int
    metadata: dict[str, str]


class _VersioningLike(Protocol):
    status: str | None


class _ResponseLike(Protocol):
    def read(self, amt: int | None = None) -> bytes: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class _ClientLike(Protocol):
    def bucket_exists(self, bucket_name: str) -> bool: ...

    def get_bucket_versioning(self, bucket_name: str) -> _VersioningLike: ...

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> object: ...

    def get_object(self, bucket_name: str, object_name: str) -> _ResponseLike: ...

    def stat_object(self, bucket_name: str, object_name: str) -> _StatLike: ...


class S3EvaluationObjectStore(EvaluationObjectStorePort):
    def __init__(self, *, client: _ClientLike, bucket: str) -> None:
        self._client = client
        self._bucket = bucket
        self._available = False

    @classmethod
    def from_values(
        cls,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
        region: str,
    ) -> S3EvaluationObjectStore:
        parsed = urlparse(endpoint)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            endpoint = parsed.netloc
            secure = parsed.scheme == "https"
        return cls(
            client=cast(
                _ClientLike,
                Minio(
                    endpoint,
                    access_key=access_key,
                    secret_key=secret_key,
                    secure=secure,
                    region=region,
                ),
            ),
            bucket=bucket,
        )

    @override
    async def put_json(self, *, key: str, payload: JsonObject) -> EvaluationStoredObject:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        sha256 = hashlib.sha256(body).hexdigest()
        await asyncio.to_thread(self._put, key, body, sha256)
        return EvaluationStoredObject(key=key, sha256=sha256, byte_size=len(body))

    @override
    async def get_json(self, *, key: str) -> JsonObject:
        body = await asyncio.to_thread(self._get, key)
        value = json.loads(body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Evaluation object must contain a JSON object.")
        return cast(JsonObject, value)

    @override
    async def stat(self, *, key: str) -> EvaluationStoredObject | None:
        try:
            result = await asyncio.to_thread(self._client.stat_object, self._bucket, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return None
            raise
        sha256 = result.metadata.get("x-amz-meta-sha256") or result.metadata.get("sha256")
        if not sha256:
            body = await asyncio.to_thread(self._get, key)
            sha256 = hashlib.sha256(body).hexdigest()
        return EvaluationStoredObject(key=key, sha256=sha256, byte_size=result.size)

    def ensure_available(self) -> None:
        if self._available:
            return
        try:
            if not self._client.bucket_exists(self._bucket):
                raise ValueError(f"Evaluation object bucket is unavailable: {self._bucket}")
            if self._client.get_bucket_versioning(self._bucket).status != "Enabled":
                raise ValueError("Evaluation object bucket must have versioning enabled.")
        except MinioException as exc:
            raise ValueError("Evaluation object store is unavailable.") from exc
        self._available = True

    def _put(self, key: str, body: bytes, sha256: str) -> None:
        self.ensure_available()
        self._client.put_object(
            self._bucket,
            key,
            BytesIO(body),
            len(body),
            content_type="application/json; charset=utf-8",
            metadata={"sha256": sha256},
        )

    def _get(self, key: str) -> bytes:
        self.ensure_available()
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
