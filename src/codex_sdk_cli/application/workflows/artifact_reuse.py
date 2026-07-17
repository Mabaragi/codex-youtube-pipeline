from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from codex_sdk_cli.application.transcripts.commands import (
    TRANSCRIPT_COLLECT_TASK,
    TRANSCRIPT_COLLECT_VERSION,
)
from codex_sdk_cli.application.work.ports import CreateWorkItem, WorkUnitOfWorkPort
from codex_sdk_cli.domains.work.models import (
    JsonObject,
    WorkExecutionMode,
    WorkItem,
    WorkItemStatus,
)

from .ports import TranscriptArtifactReaderPort


async def reuse_transcript_artifact(
    unit_of_work: WorkUnitOfWorkPort,
    *,
    reader: TranscriptArtifactReaderPort | None,
    stage_name: str,
    video_id: int,
    youtube_video_id: str,
    timeout_seconds: int,
    now: datetime,
    existing: WorkItem | None = None,
) -> WorkItem | None:
    if (
        reader is None
        or stage_name != TRANSCRIPT_COLLECT_TASK
        or (existing is not None and existing.status is WorkItemStatus.RUNNING)
    ):
        return None
    artifact = await reader.find_latest(youtube_video_id=youtube_video_id)
    if artifact is None:
        return None
    input_json: JsonObject = {
        "videoId": video_id,
        "youtubeVideoId": youtube_video_id,
        "taskVersion": TRANSCRIPT_COLLECT_VERSION,
        "artifactReuse": True,
        "transcriptId": artifact.transcript_id,
        "responseSha256": artifact.response_sha256,
    }
    input_hash = _hash(input_json)
    item, _ = await unit_of_work.work_items.get_or_create(
        CreateWorkItem(
            task_type=TRANSCRIPT_COLLECT_TASK,
            subject_type="video",
            subject_id=video_id,
            external_key=youtube_video_id,
            task_version=TRANSCRIPT_COLLECT_VERSION,
            input_hash=input_hash,
            idempotency_key=(
                f"{TRANSCRIPT_COLLECT_TASK}:video:{video_id}:"
                f"{TRANSCRIPT_COLLECT_VERSION}:artifact:{input_hash}"
            ),
            execution_mode=WorkExecutionMode.INLINE,
            timeout_seconds=timeout_seconds,
            input_json=input_json,
            available_at=now,
        )
    )
    if item.status is WorkItemStatus.PENDING:
        started = await unit_of_work.work_items.start_inline(
            work_item_id=item.id,
            worker_id="workflow:artifact-reuse",
            now=now,
            lease_expires_at=now + timedelta(seconds=timeout_seconds),
        )
        if started is None:
            return None
        item = started
    if item.status is WorkItemStatus.RUNNING:
        item = await unit_of_work.work_items.mark_succeeded(
            work_item_id=item.id,
            now=now,
            output_json={
                "videoId": video_id,
                "youtubeVideoId": youtube_video_id,
                "transcriptId": artifact.transcript_id,
                "responseSha256": artifact.response_sha256,
                "existingTranscript": True,
                "artifactReuse": True,
            },
            output_transcript_id=artifact.transcript_id,
        )
    if (
        item.status is WorkItemStatus.SUCCEEDED
        and existing is not None
        and existing.id != item.id
        and existing.status is WorkItemStatus.PENDING
    ):
        await unit_of_work.work_items.cancel(
            work_item_id=existing.id,
            now=now,
            reason="Superseded by an existing transcript artifact.",
        )
    return item if item.status is WorkItemStatus.SUCCEEDED else None


def _hash(values: JsonObject) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
