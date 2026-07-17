from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from codex_sdk_cli.application.operations.selection import VideoSelection, VideoSelectionPort
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.ports import CreateWorkBatch, CreateWorkflowRun
from codex_sdk_cli.domains.codex.choices import CodexModelChoice, ReasoningEffortChoice
from codex_sdk_cli.domains.timelines.ports import CopyStyle
from codex_sdk_cli.domains.work.models import WorkBatchStatus

from .models import WorkflowBatchResult, WorkflowSelectionItem

PROCESS_TO_PUBLISH_WORKFLOW = "process_to_publish"
PROCESS_TO_PUBLISH_VERSION = "v2"
Now = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ProcessToPublishCommand:
    selection: VideoSelection
    languages: tuple[str, ...] = ("ko", "en")
    preserve_formatting: bool = False
    micro_window_minutes: int = 30
    micro_overlap_minutes: int = 5
    micro_model: CodexModelChoice = "gpt-5.6-sol"
    micro_reasoning_effort: ReasoningEffortChoice = "medium"
    micro_prompt_version_id: int | None = None
    timeline_model: CodexModelChoice = "gpt-5.6-sol"
    timeline_reasoning_effort: ReasoningEffortChoice = "medium"
    timeline_copy_style: CopyStyle = "LIGHT_FANDOM_V1"
    timeline_prompt_version_id: int | None = None
    publish_mode: str = "prod"
    environment: str = "prod"
    variant: str = "control"
    schema_version: int = 1
    retry_failed: bool = False
    include_non_embeddable: bool = False
    reuse_successful_stages: bool = True
    transcript_fallback_mode: str = "asr_after_grace"
    transcript_fallback_grace_seconds: int = 21600
    transcript_recheck_interval_seconds: int = 1800
    asr_model: str = "turbo"
    asr_language: str = "ko"
    asr_device: str = "cuda"
    asr_compute_type: str = "auto"
    asr_chunk_minutes: int = 15
    asr_overlap_seconds: int = 3
    asr_beam_size: int = 5
    asr_vad_filter: bool = True
    transcript_timeout_seconds: int = 600
    cue_timeout_seconds: int = 600
    asr_timeout_seconds: int = 64800
    micro_timeout_seconds: int = 14400
    timeline_timeout_seconds: int = 7200
    archive_timeout_seconds: int = 600
    actor_type: str = "manual_api"
    automation_mode: str = "manual"


class StartProcessToPublishUseCase:
    def __init__(
        self,
        *,
        videos: VideoSelectionPort,
        unit_of_work_factory: WorkUnitOfWorkFactory,
        now: Now | None = None,
    ) -> None:
        self._videos = videos
        self._unit_of_work_factory = unit_of_work_factory
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, command: ProcessToPublishCommand) -> WorkflowBatchResult:
        videos = await self._videos.select(command.selection)
        now = _aware(self._now())
        results: list[WorkflowSelectionItem] = []
        created_count = 0
        reused_count = 0
        async with self._unit_of_work_factory() as unit_of_work:
            batch = await unit_of_work.work_batches.create(
                CreateWorkBatch(
                    operation_type=PROCESS_TO_PUBLISH_WORKFLOW,
                    actor_type=command.actor_type,
                    selection_json={
                        "kind": type(command.selection).__name__,
                        **asdict(command.selection),
                    },
                    options_json=_command_options(command),
                    requested_count=len(videos),
                )
            )
            for position, video in enumerate(videos, start=1):
                if video.is_embeddable is False and not command.include_non_embeddable:
                    result = WorkflowSelectionItem(
                        video_id=video.id,
                        youtube_video_id=video.youtube_video_id,
                        status="skipped",
                        reason="not_embeddable",
                        workflow_run_id=None,
                    )
                else:
                    options = {
                        **_command_options(command),
                        "videoId": video.id,
                        "youtubeVideoId": video.youtube_video_id,
                        "publishedAt": _aware(video.published_at).isoformat(),
                        "discoveredAt": _aware(video.created_at).isoformat(),
                        "captionSlaDeadline": (
                            _aware(video.created_at) + timedelta(hours=6)
                        ).isoformat(),
                        "asrSlaDeadline": (
                            _aware(video.created_at) + timedelta(hours=24)
                        ).isoformat(),
                    }
                    input_hash = _hash(options)
                    workflow, created = await unit_of_work.workflows.create_or_get(
                        CreateWorkflowRun(
                            workflow_type=PROCESS_TO_PUBLISH_WORKFLOW,
                            workflow_version=PROCESS_TO_PUBLISH_VERSION,
                            video_id=video.id,
                            input_hash=input_hash,
                            options_json=options,
                            available_at=now,
                        )
                    )
                    if (
                        not created
                        and command.retry_failed
                        and workflow.status.value in {"failed", "blocked"}
                    ):
                        workflow = await unit_of_work.workflows.reset_for_retry(
                            workflow_run_id=workflow.id,
                            now=now,
                        )
                    created_count += int(created)
                    reused_count += int(not created)
                    result = WorkflowSelectionItem(
                        video_id=video.id,
                        youtube_video_id=video.youtube_video_id,
                        status=workflow.status.value,
                        reason="created" if created else "reused",
                        workflow_run_id=workflow.id,
                    )
                results.append(result)
                await unit_of_work.work_batches.add_item(
                    batch_id=batch.id,
                    position=position,
                    video_id=video.id,
                    work_item_id=None,
                    workflow_run_id=result.workflow_run_id,
                    selection_status=result.status,
                    reason=result.reason,
                )
            await unit_of_work.work_batches.complete(
                batch_id=batch.id,
                status=WorkBatchStatus.SUCCEEDED.value,
                completed_at=now,
            )
            await unit_of_work.commit()
        return WorkflowBatchResult(
            batch_id=batch.id,
            requested_count=len(results),
            created_count=created_count,
            reused_count=reused_count,
            skipped_count=sum(item.status == "skipped" for item in results),
            items=tuple(results),
        )


def _command_options(command: ProcessToPublishCommand) -> dict[str, object]:
    values = asdict(command)
    values.pop("selection")
    values.pop("actor_type")
    return {**values, "languages": list(command.languages)}


def _hash(values: dict[str, object]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
