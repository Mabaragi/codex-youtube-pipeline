from __future__ import annotations

import asyncio
from typing import BinaryIO

import pytest
from minio.error import MinioException

from codex_sdk_cli.domains.external_api_calls.exceptions import ExternalApiCallStorageError
from codex_sdk_cli.domains.external_api_calls.ports import ExternalApiCallStorageSaveRequest
from codex_sdk_cli.infra.external_api_calls.storage import (
    MinioClientLike,
    MinioExternalApiCallStorage,
)


class FakeMinioClient(MinioClientLike):
    def __init__(self, *, bucket_exists: bool = False) -> None:
        self._bucket_exists = bucket_exists
        self.make_bucket_calls: list[str] = []
        self.put_object_calls: list[dict[str, object]] = []
        self.error: MinioException | None = None

    def bucket_exists(self, bucket_name: str) -> bool:
        if self.error is not None:
            raise self.error
        return self._bucket_exists

    def make_bucket(self, bucket_name: str) -> None:
        if self.error is not None:
            raise self.error
        self.make_bucket_calls.append(bucket_name)
        self._bucket_exists = True

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> object:
        if self.error is not None:
            raise self.error
        self.put_object_calls.append(
            {
                "bucket_name": bucket_name,
                "object_name": object_name,
                "payload": data.read(),
                "length": length,
                "content_type": content_type,
            }
        )
        return object()


def test_minio_external_api_call_storage_uploads_raw_response() -> None:
    client = FakeMinioClient(bucket_exists=False)
    storage = MinioExternalApiCallStorage(client, "raw")

    location = asyncio.run(
        storage.save_raw_response(
            ExternalApiCallStorageSaveRequest(
                object_name="external-api-calls/2026/06/16/youtube_data/channels-list-hash.json",
                payload=b'{"items":[]}',
                content_type="application/json",
            )
        )
    )

    assert client.make_bucket_calls == ["raw"]
    assert client.put_object_calls == [
        {
            "bucket_name": "raw",
            "object_name": (
                "external-api-calls/2026/06/16/youtube_data/channels-list-hash.json"
            ),
            "payload": b'{"items":[]}',
            "length": 12,
            "content_type": "application/json",
        }
    ]
    assert location.bucket == "raw"
    assert location.uri.startswith("s3://raw/external-api-calls/")


def test_minio_external_api_call_storage_maps_sdk_errors() -> None:
    client = FakeMinioClient(bucket_exists=True)
    client.error = MinioException("boom")
    storage = MinioExternalApiCallStorage(client, "raw")

    with pytest.raises(ExternalApiCallStorageError, match="raw storage write failed"):
        asyncio.run(
            storage.save_raw_response(
                ExternalApiCallStorageSaveRequest(
                    object_name="external-api-calls/object.json",
                    payload=b"{}",
                    content_type="application/json",
                )
            )
        )
