from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from codex_sdk_cli.application.operations.results import OperationBatchResult, OperationItem
from codex_sdk_cli.application.operations.selection import VideoSelection, VideoSelectionPort
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import CreateWorkBatch, CreateWorkItem
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.work.models import (
    JsonObject,
    WorkBatchStatus,
    WorkExecutionMode,
    WorkItem,
    WorkItemStatus,
)

from .ports import TranscriptMetadataReaderPort

Now = Callable[[], datetime]
TRANSCRIPT_COLLECT_TASK = "transcript_collect"
TRANSCRIPT_COLLECT_VERSION = "v2"
TRANSCRIPT_CUE_TASK = "transcript_cue_generate"
TRANSCRIPT_CUE_VERSION = "v2"


@dataclass(frozen=True, slots=True)
class CollectTranscriptsCommand:
    selection: VideoSelection
    languages: tuple[str, ...] = ("ko", "en")
    preserve_formatting: bool = False
    retry_failed: bool = False
    recheck_no_transcript: bool = False
    rerun_succeeded: bool = False
    include_non_embeddable: bool = False
    timeout_seconds: int = 600
    actor_type: str = "manual_api"


@dataclass(frozen=True, slots=True)
class GenerateTranscriptCuesCommand:
    selection: VideoSelection
    retry_failed: bool = False
    rerun_succeeded: bool = False
    include_non_embeddable: bool = False
    timeout_seconds: int = 600
    actor_type: str = "manual_api"


class CollectTranscriptsUseCase:
    def __init__(
        self,
        *,
        videos: VideoSelectionPort,
        transcripts: TranscriptMetadataReaderPort,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        now: Now | None = None,
    ) -> None:
        self._videos = videos
        self._transcripts = transcripts
        self._unit_of_work_factory = unit_of_work_factory
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, command: CollectTranscriptsCommand) -> OperationBatchResult:
        videos = await self._videos.select(command.selection)
        now = _aware(self._now())
        items: list[OperationItem] = []
        created_count = 0
        reused_count = 0
        async with self._unit_of_work_factory() as unit_of_work:
            batch = await unit_of_work.work_batches.create(
                CreateWorkBatch(
                    operation_type=TRANSCRIPT_COLLECT_TASK,
                    actor_type=command.actor_type,
                    selection_json=_selection_json(command.selection),
                    options_json={
                        "languages": list(command.languages),
                        "preserveFormatting": command.preserve_formatting,
                        "retryFailed": command.retry_failed,
                        "recheckNoTranscript": command.recheck_no_transcript,
                        "rerunSucceeded": command.rerun_succeeded,
                        "includeNonEmbeddable": command.include_non_embeddable,
                    },
                    requested_count=len(videos),
                )
            )
            for position, video in enumerate(videos, start=1):
                item, created, reused = await self._enqueue_video(
                    unit_of_work,
                    video=video,
                    command=command,
                    now=now,
                )
                items.append(item)
                created_count += int(created)
                reused_count += int(reused)
                await unit_of_work.work_batches.add_item(
                    batch_id=batch.id,
                    position=position,
                    video_id=video.id,
                    work_item_id=item.work_item_id,
                    workflow_run_id=None,
                    selection_status=item.status,
                    reason=item.reason,
                )
            await unit_of_work.work_batches.complete(
                batch_id=batch.id,
                status=WorkBatchStatus.SUCCEEDED.value,
                completed_at=now,
            )
            await unit_of_work.commit()
        return _batch_result(batch.id, items, created_count, reused_count)

    async def _enqueue_video(
        self,
        unit_of_work,
        *,
        video: VideoRecord,
        command: CollectTranscriptsCommand,
        now: datetime,
    ) -> tuple[OperationItem, bool, bool]:
        if video.is_embeddable is False and not command.include_non_embeddable:
            return _skipped(video, "not_embeddable"), False, False
        existing_success = await unit_of_work.work_items.find_latest(
            task_type=TRANSCRIPT_COLLECT_TASK,
            subject_type="video",
            subject_id=video.id,
            status=WorkItemStatus.SUCCEEDED,
        )
        if (
            existing_success is not None
            and existing_success.outcome_code is None
            and existing_success.output_transcript_id is not None
            and not command.rerun_succeeded
        ):
            stored = await self._transcripts.find_for_request(
                youtube_video_id=video.youtube_video_id,
                requested_languages=command.languages,
                preserve_formatting=command.preserve_formatting,
            )
            if (
                stored is not None
                and stored.transcript_id == existing_success.output_transcript_id
            ):
                return _existing_item(video, existing_success), False, True
        input_json: JsonObject = {
            "videoId": video.id,
            "youtubeVideoId": video.youtube_video_id,
            "languages": list(command.languages),
            "preserveFormatting": command.preserve_formatting,
            "timeoutSeconds": command.timeout_seconds,
            "taskVersion": TRANSCRIPT_COLLECT_VERSION,
        }
        input_hash = _hash(input_json)
        work_item, created = await unit_of_work.work_items.get_or_create(
            CreateWorkItem(
                task_type=TRANSCRIPT_COLLECT_TASK,
                subject_type="video",
                subject_id=video.id,
                external_key=video.youtube_video_id,
                task_version=TRANSCRIPT_COLLECT_VERSION,
                input_hash=input_hash,
                idempotency_key=_idempotency_key(
                    TRANSCRIPT_COLLECT_TASK,
                    video.id,
                    TRANSCRIPT_COLLECT_VERSION,
                    input_hash,
                ),
                execution_mode=WorkExecutionMode.WORKER,
                timeout_seconds=command.timeout_seconds,
                input_json=input_json,
                available_at=now,
            )
        )
        if created:
            return _queued(video, work_item, "enqueued"), True, False
        reset = _should_reset_transcript(work_item, command)
        if reset:
            work_item = await unit_of_work.work_items.reset_for_retry(
                work_item_id=work_item.id,
                now=now,
                allow_succeeded=True,
            )
            return _queued(video, work_item, "requeued"), True, False
        return (
            _existing_item(video, work_item),
            False,
            work_item.status
            in {
                WorkItemStatus.PENDING,
                WorkItemStatus.RUNNING,
            },
        )


class GenerateTranscriptCuesUseCase:
    def __init__(
        self,
        *,
        videos: VideoSelectionPort,
        transcripts: TranscriptMetadataReaderPort,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        now: Now | None = None,
    ) -> None:
        self._videos = videos
        self._transcripts = transcripts
        self._unit_of_work_factory = unit_of_work_factory
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, command: GenerateTranscriptCuesCommand) -> OperationBatchResult:
        videos = await self._videos.select(command.selection)
        now = _aware(self._now())
        items: list[OperationItem] = []
        created_count = 0
        reused_count = 0
        async with self._unit_of_work_factory() as unit_of_work:
            batch = await unit_of_work.work_batches.create(
                CreateWorkBatch(
                    operation_type=TRANSCRIPT_CUE_TASK,
                    actor_type=command.actor_type,
                    selection_json=_selection_json(command.selection),
                    options_json={
                        "retryFailed": command.retry_failed,
                        "rerunSucceeded": command.rerun_succeeded,
                        "includeNonEmbeddable": command.include_non_embeddable,
                    },
                    requested_count=len(videos),
                )
            )
            for position, video in enumerate(videos, start=1):
                item, created, reused = await self._enqueue_video(
                    unit_of_work,
                    video=video,
                    command=command,
                    now=now,
                )
                items.append(item)
                created_count += int(created)
                reused_count += int(reused)
                await unit_of_work.work_batches.add_item(
                    batch_id=batch.id,
                    position=position,
                    video_id=video.id,
                    work_item_id=item.work_item_id,
                    workflow_run_id=None,
                    selection_status=item.status,
                    reason=item.reason,
                )
            await unit_of_work.work_batches.complete(
                batch_id=batch.id,
                status=WorkBatchStatus.SUCCEEDED.value,
                completed_at=now,
            )
            await unit_of_work.commit()
        return _batch_result(batch.id, items, created_count, reused_count)

    async def _enqueue_video(
        self,
        unit_of_work,
        *,
        video: VideoRecord,
        command: GenerateTranscriptCuesCommand,
        now: datetime,
    ) -> tuple[OperationItem, bool, bool]:
        if video.is_embeddable is False and not command.include_non_embeddable:
            return _skipped(video, "not_embeddable"), False, False
        transcript_work = await unit_of_work.work_items.find_latest(
            task_type=TRANSCRIPT_COLLECT_TASK,
            subject_type="video",
            subject_id=video.id,
            status=WorkItemStatus.SUCCEEDED,
        )
        if (
            transcript_work is None
            or transcript_work.outcome_code is not None
            or transcript_work.output_transcript_id is None
        ):
            return _skipped(video, "transcript_not_ready"), False, False
        transcript = await self._transcripts.get(transcript_work.output_transcript_id)
        if transcript is None:
            return _skipped(video, "transcript_not_found"), False, False
        input_json: JsonObject = {
            "videoId": video.id,
            "youtubeVideoId": video.youtube_video_id,
            "transcriptId": transcript.transcript_id,
            "responseSha256": transcript.response_sha256,
            "timeoutSeconds": command.timeout_seconds,
            "taskVersion": TRANSCRIPT_CUE_VERSION,
        }
        input_hash = _hash(input_json)
        work_item, created = await unit_of_work.work_items.get_or_create(
            CreateWorkItem(
                task_type=TRANSCRIPT_CUE_TASK,
                subject_type="video",
                subject_id=video.id,
                external_key=video.youtube_video_id,
                task_version=TRANSCRIPT_CUE_VERSION,
                input_hash=input_hash,
                idempotency_key=_idempotency_key(
                    TRANSCRIPT_CUE_TASK,
                    video.id,
                    TRANSCRIPT_CUE_VERSION,
                    input_hash,
                ),
                execution_mode=WorkExecutionMode.WORKER,
                timeout_seconds=command.timeout_seconds,
                input_json=input_json,
                available_at=now,
            )
        )
        await unit_of_work.work_items.add_dependency(
            work_item_id=work_item.id,
            dependency_work_item_id=transcript_work.id,
        )
        if created:
            return _queued(video, work_item, "enqueued"), True, False
        if _should_reset(work_item, command.retry_failed, command.rerun_succeeded):
            work_item = await unit_of_work.work_items.reset_for_retry(
                work_item_id=work_item.id,
                now=now,
                allow_succeeded=command.rerun_succeeded,
            )
            return _queued(video, work_item, "requeued"), True, False
        return (
            _existing_item(video, work_item),
            False,
            work_item.status
            in {
                WorkItemStatus.PENDING,
                WorkItemStatus.RUNNING,
            },
        )


def _should_reset_transcript(
    item: WorkItem,
    command: CollectTranscriptsCommand,
) -> bool:
    if item.status is WorkItemStatus.SUCCEEDED:
        if item.outcome_code == "no_transcript":
            return command.recheck_no_transcript
        return command.rerun_succeeded
    return _should_reset(item, command.retry_failed, command.rerun_succeeded)


def _should_reset(item: WorkItem, retry_failed: bool, rerun_succeeded: bool) -> bool:
    if item.status in {
        WorkItemStatus.FAILED,
        WorkItemStatus.TIMED_OUT,
        WorkItemStatus.BLOCKED,
    }:
        return retry_failed
    return item.status is WorkItemStatus.SUCCEEDED and rerun_succeeded


def _existing_item(video: VideoRecord, item: WorkItem) -> OperationItem:
    if item.status in {WorkItemStatus.PENDING, WorkItemStatus.RUNNING}:
        return OperationItem(
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
            status=item.status.value,
            reason=f"already_{item.status.value}",
            work_item_id=item.id,
        )
    return OperationItem(
        video_id=video.id,
        youtube_video_id=video.youtube_video_id,
        status="skipped",
        reason=(
            "already_succeeded"
            if item.status is WorkItemStatus.SUCCEEDED and item.outcome_code is None
            else item.outcome_code or f"previously_{item.status.value}"
        ),
        work_item_id=item.id,
    )


def _queued(video: VideoRecord, item: WorkItem, reason: str) -> OperationItem:
    return OperationItem(
        video_id=video.id,
        youtube_video_id=video.youtube_video_id,
        status=WorkItemStatus.PENDING.value,
        reason=reason,
        work_item_id=item.id,
    )


def _skipped(video: VideoRecord, reason: str) -> OperationItem:
    return OperationItem(
        video_id=video.id,
        youtube_video_id=video.youtube_video_id,
        status="skipped",
        reason=reason,
        work_item_id=None,
    )


def _batch_result(
    batch_id: int,
    items: list[OperationItem],
    created_count: int,
    reused_count: int,
) -> OperationBatchResult:
    return OperationBatchResult(
        batch_id=batch_id,
        requested_count=len(items),
        created_count=created_count,
        reused_count=reused_count,
        skipped_count=sum(item.status == "skipped" for item in items),
        items=tuple(items),
    )


def _selection_json(selection: VideoSelection) -> dict[str, object]:
    return {
        "kind": type(selection).__name__,
        **asdict(selection),
    }


def _hash(values: dict[str, object]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _idempotency_key(task: str, video_id: int, version: str, input_hash: str) -> str:
    return f"{task}:video:{video_id}:{version}:{input_hash}"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
