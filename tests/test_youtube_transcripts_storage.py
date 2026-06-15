from __future__ import annotations

import asyncio
from typing import BinaryIO

import pytest
from minio.error import MinioException

from codex_sdk_cli.domains.youtube_transcripts.exceptions import YouTubeTranscriptStorageError
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    TranscriptStorageLocation,
    YouTubeTranscriptStorageSaveRequest,
)
from codex_sdk_cli.infra.youtube_transcripts.storage import MinioClientLike, MinioTranscriptStorage


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


def test_minio_storage_creates_bucket_and_uploads_json() -> None:
    client = FakeMinioClient(bucket_exists=False)
    storage = MinioTranscriptStorage(client, "raw")

    location = asyncio.run(
        storage.save_transcript(
            YouTubeTranscriptStorageSaveRequest(
                object_name="youtube/transcripts/2026/06/15/video-hash.json",
                payload=b'{"ok":true}',
            )
        )
    )

    assert client.make_bucket_calls == ["raw"]
    assert client.put_object_calls == [
        {
            "bucket_name": "raw",
            "object_name": "youtube/transcripts/2026/06/15/video-hash.json",
            "payload": b'{"ok":true}',
            "length": 11,
            "content_type": "application/json",
        }
    ]
    assert location == TranscriptStorageLocation(
        bucket="raw",
        object_name="youtube/transcripts/2026/06/15/video-hash.json",
        uri="s3://raw/youtube/transcripts/2026/06/15/video-hash.json",
    )


def test_minio_storage_reuses_existing_bucket() -> None:
    client = FakeMinioClient(bucket_exists=True)
    storage = MinioTranscriptStorage(client, "raw")

    asyncio.run(
        storage.save_transcript(
            YouTubeTranscriptStorageSaveRequest(
                object_name="youtube/transcripts/object.json",
                payload=b"{}",
            )
        )
    )

    assert client.make_bucket_calls == []
    assert len(client.put_object_calls) == 1


def test_minio_storage_maps_sdk_errors_to_domain_error() -> None:
    client = FakeMinioClient(bucket_exists=True)
    client.error = MinioException("boom")
    storage = MinioTranscriptStorage(client, "raw")

    with pytest.raises(YouTubeTranscriptStorageError, match="Transcript storage write failed."):
        asyncio.run(
            storage.save_transcript(
                YouTubeTranscriptStorageSaveRequest(
                    object_name="youtube/transcripts/object.json",
                    payload=b"{}",
                )
            )
        )
