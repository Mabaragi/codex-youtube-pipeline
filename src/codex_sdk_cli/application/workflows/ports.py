from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codex_sdk_cli.application.work.execution import WorkRunResult


@dataclass(frozen=True, slots=True)
class PublishedArchive:
    video_id: int
    artifact_id: int
    public_url: str


@dataclass(frozen=True, slots=True)
class TranscriptArtifact:
    transcript_id: int
    response_sha256: str


class TranscriptArtifactReaderPort(Protocol):
    async def find_latest(self, *, youtube_video_id: str) -> TranscriptArtifact | None: ...


class ArchivePublisherPort(Protocol):
    async def publish(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        video_id: int,
        source_timeline_work_item_id: int,
        publish_mode: str,
        environment: str,
        variant: str,
        schema_version: int,
    ) -> PublishedArchive: ...


class InlineWorkRunnerPort(Protocol):
    async def run(self, work_item_id: int) -> WorkRunResult: ...
