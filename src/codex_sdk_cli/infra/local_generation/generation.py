from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from codex_sdk_cli.application.one_shot.ports import RunOptions
from codex_sdk_cli.domains.codex.ports import CodexRuntimePort
from codex_sdk_cli.domains.micro_events.constants import (
    MICRO_EVENT_EXTRACT_TASK_NAME,
    MICRO_EVENT_EXTRACT_TASK_VERSION,
)
from codex_sdk_cli.domains.micro_events.schemas import MicroEventExtractRequest
from codex_sdk_cli.domains.micro_events.use_cases import ExtractVideoMicroEventsUseCase
from codex_sdk_cli.domains.prompts.constants import (
    MICRO_EVENT_EXTRACT_PROMPT_KEY,
    TIMELINE_COMPOSE_PROMPT_KEY,
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY,
)
from codex_sdk_cli.domains.timelines.schemas import TimelineComposeEnqueueRequest
from codex_sdk_cli.domains.timelines.use_cases import ComposeTimelineUseCase
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord
from codex_sdk_cli.infra.codex.client import CodexRuntimeClient
from codex_sdk_cli.infra.codex.recording import RecordingCodexRuntime
from codex_sdk_cli.infra.micro_events.extractor import CodexMicroEventExtractor
from codex_sdk_cli.infra.timelines.composer import CodexTimelineComposer
from codex_sdk_cli.settings import CliSettings

from .files import (
    FileTraceRecorder,
    FileUsageRecorder,
    FileWindowCheckpoints,
    file_sha256,
    jsonable,
    read_json,
)
from .memory import (
    MemoryMicroEventRepository,
    MemoryPipelineJobRepository,
    MemoryTimelineRepository,
    MemoryVideoTaskRepository,
    NoopEvaluationEventRecorder,
    SnapshotChannelRepository,
    SnapshotCueRepository,
    SnapshotDomainKnowledgeRepository,
    SnapshotPromptResolver,
    SnapshotStreamerRepository,
    SnapshotTranscriptRepository,
    SnapshotVideoRepository,
    micro_detail_from_json,
    resolved_prompt,
    snapshot_records,
    window_create_from_json,
)


class LocalGenerationRunner:
    def __init__(self, settings: CliSettings, runtime: CodexRuntimePort | None = None) -> None:
        self._settings = settings
        self._runtime = runtime or CodexRuntimeClient(settings)

    async def generate_micro(self, *, run_dir: Path, resume: bool) -> dict[str, object]:
        snapshot = _snapshot(run_dir)
        video, channel, streamer, transcript, cues, domain = snapshot_records(snapshot)
        options = RunOptions(**read_json(run_dir / "plan.json")["options"])
        tasks = MemoryVideoTaskRepository(video=video, task_id=1, resume=resume)
        checkpoint_writer = FileWindowCheckpoints(run_dir)
        checkpoints = checkpoint_writer.completed() if resume else []
        if checkpoints:
            tasks.seed_source(_task(video.id, 1, status="failed", transcript_id=None))
        micro_events = MemoryMicroEventRepository(
            video=video, tasks=tasks, checkpoint_writer=checkpoint_writer
        )
        if checkpoints:
            micro_events.seed_windows(1, [window_create_from_json(item) for item in checkpoints])
        prompt = resolved_prompt(snapshot["prompts"][MICRO_EVENT_EXTRACT_PROMPT_KEY])
        runtime = RecordingCodexRuntime(self._runtime, FileUsageRecorder(run_dir))
        # Snapshot adapters implement the methods used by these use cases, not full CRUD ports.
        use_case = ExtractVideoMicroEventsUseCase(
            videos=cast(Any, SnapshotVideoRepository(video)),
            video_tasks=cast(Any, tasks),
            transcripts=cast(Any, SnapshotTranscriptRepository(transcript)),
            transcript_cues=cast(Any, SnapshotCueRepository(cues)),
            channels=cast(Any, SnapshotChannelRepository(channel)),
            streamers=cast(Any, SnapshotStreamerRepository(streamer)),
            domain_knowledge=cast(Any, SnapshotDomainKnowledgeRepository(domain)),
            pipeline_jobs=cast(Any, MemoryPipelineJobRepository()),
            micro_events=cast(Any, micro_events),
            extractor=CodexMicroEventExtractor(
                runtime,
                model=options.micro_model,
                reasoning_effort=options.micro_reasoning_effort,
            ),
            prompt_resolver=SnapshotPromptResolver({MICRO_EVENT_EXTRACT_PROMPT_KEY: prompt}),
            timeout_seconds=self._settings.micro_event_extract_timeout_seconds,
            concurrency_limit=options.micro_window_concurrency,
            model=options.micro_model,
            reasoning_effort=options.micro_reasoning_effort,
            events=NoopEvaluationEventRecorder(),
            llm_traces=FileTraceRecorder(run_dir),
        )
        response = await use_case.execute(
            video.id,
            MicroEventExtractRequest(
                retryFailed=resume,
                regenerateSucceeded=False,
                windowMinutes=options.window_minutes,
                overlapMinutes=options.overlap_minutes,
                model=options.micro_model,
                reasoningEffort=options.micro_reasoning_effort,
            ),
        )
        if response.status != "succeeded":
            raise RuntimeError(
                response.error_message or f"Micro extraction ended as {response.status}."
            )
        detail = await micro_events.get_extraction(video_id=video.id, video_task_id=1)
        if detail is None:
            raise RuntimeError("Micro extraction result is missing.")
        return {
            "schemaVersion": 1,
            "response": response.model_dump(mode="json", by_alias=True),
            "detail": cast(dict[str, object], jsonable(asdict(detail))),
        }

    async def generate_timeline(
        self, *, run_dir: Path, micro: dict[str, object]
    ) -> dict[str, object]:
        snapshot = _snapshot(run_dir)
        video, channel, streamer, _transcript, _cues, domain = snapshot_records(snapshot)
        options = RunOptions(**read_json(run_dir / "plan.json")["options"])
        source_detail = micro_detail_from_json(cast(dict[str, object], micro["detail"]))
        tasks = MemoryVideoTaskRepository(video=video, task_id=2, resume=False)
        tasks.seed_source(_task(video.id, 1, status="succeeded", transcript_id=1))
        micro_events = MemoryMicroEventRepository(video=video, tasks=tasks)
        micro_events.seed_detail(1, source_detail)
        timelines = MemoryTimelineRepository(video=video)
        prompts = snapshot["prompts"]
        runtime = RecordingCodexRuntime(self._runtime, FileUsageRecorder(run_dir))
        use_case = ComposeTimelineUseCase(
            videos=cast(Any, SnapshotVideoRepository(video)),
            video_tasks=cast(Any, tasks),
            channels=cast(Any, SnapshotChannelRepository(channel)),
            streamers=cast(Any, SnapshotStreamerRepository(streamer)),
            domain_knowledge=cast(Any, SnapshotDomainKnowledgeRepository(domain)),
            micro_events=cast(Any, micro_events),
            timelines=timelines,
            pipeline_jobs=cast(Any, MemoryPipelineJobRepository()),
            composer=CodexTimelineComposer(
                runtime,
                model=options.timeline_model,
                reasoning_effort=options.timeline_reasoning_effort,
            ),
            prompt_resolver=SnapshotPromptResolver(
                {
                    TIMELINE_COMPOSE_PROMPT_KEY: resolved_prompt(
                        prompts[TIMELINE_COMPOSE_PROMPT_KEY]
                    ),
                    TIMELINE_EPISODE_REPAIR_PROMPT_KEY: resolved_prompt(
                        prompts[TIMELINE_EPISODE_REPAIR_PROMPT_KEY]
                    ),
                }
            ),
            timeout_seconds=self._settings.timeline_compose_timeout_seconds,
            model=options.timeline_model,
            reasoning_effort=options.timeline_reasoning_effort,
            events=NoopEvaluationEventRecorder(),
            llm_traces=FileTraceRecorder(run_dir),
        )
        enqueued = await use_case.enqueue(
            TimelineComposeEnqueueRequest(
                target="selected_videos",
                videoIds=[video.id],
                limit=1,
                model=options.timeline_model,
                reasoningEffort=options.timeline_reasoning_effort,
                copyStyle="LIGHT_FANDOM_V1",
            )
        )
        if not enqueued.items or enqueued.items[0].video_task_id is None:
            message = enqueued.items[0].error_message if enqueued.items else None
            raise RuntimeError(message or "Timeline could not be enqueued.")
        claimed = await tasks.claim_pending_task(2, worker_id="timeline-once")
        if claimed is None:
            raise RuntimeError("Timeline task could not be claimed.")
        response = await use_case.execute_claimed_task(claimed, worker_id="timeline-once")
        detail = await timelines.get_composition(video_id=video.id, video_task_id=2)
        if detail is None or detail.output_json is None:
            raise RuntimeError("Timeline result is missing.")
        normalized = response.model_dump(mode="json", by_alias=True)
        normalized.pop("outputJson", None)
        referenced_ids = _referenced_candidate_ids(normalized)
        candidates = [
            candidate
            for window in sorted(source_detail.windows, key=lambda item: item.window_index)
            for candidate in sorted(window.micro_events, key=lambda item: item.candidate_index)
        ]
        micro_items = []
        for index, candidate in enumerate(candidates, start=1):
            if candidate.id not in referenced_ids:
                continue
            item = cast(dict[str, object], jsonable(asdict(candidate)))
            for key in ("window_id", "video_task_id", "transcript_id", "created_at", "updated_at"):
                item.pop(key, None)
            item["sourceCandidateId"] = item.pop("id")
            item["id"] = f"me_{index:04d}"
            micro_items.append(item)
        plan = read_json(run_dir / "plan.json")
        return {
            "schemaVersion": 1,
            "video": plan["video"],
            "timeline": normalized,
            "microEvents": micro_items,
            "validationWarnings": detail.validation_warnings,
            "provenance": {
                "transcriptSource": plan["transcriptSource"],
                "microModel": options.micro_model,
                "timelineModel": options.timeline_model,
                "promptVersions": {
                    key: {
                        "versionId": value["versionId"],
                        "sha256": value["bodySha256"],
                    }
                    for key, value in plan["prompts"].items()
                },
            },
        }


def _referenced_candidate_ids(timeline: dict[str, Any]) -> set[int]:
    references: set[int] = set()
    for episode in timeline["episodes"]:
        references.update(
            value
            for value in (
                episode["startMicroEventCandidateId"],
                episode["endMicroEventCandidateId"],
                *episode["highlightMicroEventCandidateIds"],
            )
            if isinstance(value, int)
        )
    for flag in timeline["reviewFlags"]:
        references.update(
            value
            for value in (
                flag["startMicroEventCandidateId"],
                flag["endMicroEventCandidateId"],
            )
            if isinstance(value, int)
        )
    return references


def _snapshot(run_dir: Path) -> dict[str, Any]:
    plan = read_json(run_dir / "plan.json")
    video = plan["video"]
    transcript = read_json(run_dir / "inputs" / "transcript.json")
    cue_rows = json.loads((run_dir / "inputs" / "cues.json").read_text(encoding="utf-8"))
    now = datetime.now(UTC).isoformat()
    storage = transcript["storage"]
    metadata = {
        "id": 1,
        "video_id": video["youtubeVideoId"],
        "language": transcript["language"],
        "language_code": transcript["languageCode"],
        "is_generated": transcript["isGenerated"],
        "requested_languages": list(plan["options"]["languages"]),
        "preserve_formatting": False,
        "storage_bucket": storage["bucket"],
        "storage_object_name": storage["objectName"],
        "storage_uri": storage["uri"],
        "response_sha256": file_sha256(run_dir / "inputs" / "transcript.json"),
        "segment_count": len(transcript["segments"]),
        "text_length": len(transcript["text"]),
        "notes": None,
        "created_at": now,
        "updated_at": now,
    }
    return {
        "video": {
            "id": 1,
            "channel_id": 1,
            "youtube_video_id": video["youtubeVideoId"],
            "title": video["title"],
            "description": video["description"],
            "published_at": video["publishedAt"],
            "duration": video["duration"],
            "thumbnail_url": video["thumbnailUrl"],
            "source_listing_api_call_id": None,
            "source_details_api_call_id": None,
            "source_job_id": None,
            "created_at": now,
            "updated_at": now,
            "is_embeddable": video["isEmbeddable"],
        },
        "channel": {
            "id": 1,
            "streamer_id": 1,
            "handle": "@one-shot",
            "name": video["channelName"],
            "youtube_channel_id": video["channelId"],
            "uploads_playlist_id": None,
            "source_api_call_id": None,
        },
        "streamer": {
            "id": 1,
            "name": plan["options"]["streamer_name"] or video["channelName"],
            "publish_profile_id": 0,
        },
        "transcript": metadata,
        "cues": cue_rows,
        "domainKnowledge": [],
        "prompts": plan["prompts"],
    }


def _task(
    video_id: int, task_id: int, *, status: str, transcript_id: int | None
) -> VideoTaskRecord:
    now = datetime.now(UTC)
    return VideoTaskRecord(
        id=task_id,
        video_id=video_id,
        task_name=MICRO_EVENT_EXTRACT_TASK_NAME,
        task_version=MICRO_EVENT_EXTRACT_TASK_VERSION,
        input_hash="local-generation",
        status=cast(Any, status),
        worker_id=None,
        timeout_seconds=3600,
        job_id=None,
        job_attempt_id=None,
        output_transcript_id=transcript_id,
        output_json={"local": True} if status == "succeeded" else None,
        error_type="InterruptedProcess" if status == "failed" else None,
        error_message="Resuming local windows." if status == "failed" else None,
        started_at=None,
        completed_at=now if status == "succeeded" else None,
        created_at=now,
        updated_at=now,
    )
