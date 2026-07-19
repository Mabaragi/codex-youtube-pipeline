from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any, cast

from codex_sdk_cli.domains.channels.ports import ChannelRecord
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainKnowledgePromptAliasRecord,
    DomainKnowledgePromptEntryRecord,
)
from codex_sdk_cli.domains.evaluation.ports import JsonObject
from codex_sdk_cli.domains.micro_events.ports import (
    AsrCorrectionCandidateRecord,
    MicroEventCandidateRecord,
    MicroEventExcludedRangeRecord,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionWindowCreate,
    MicroEventExtractionWindowRecord,
)
from codex_sdk_cli.domains.operation_events.ports import OperationEventCreate
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobAttemptRecord,
    PipelineJobCreate,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.prompts.constants import PromptKey
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.streamers.ports import StreamerRecord
from codex_sdk_cli.domains.timelines.ports import (
    TimelineBlockRecord,
    TimelineCompositionCreate,
    TimelineCompositionRecord,
    TimelineEpisodeRecord,
    TimelineReviewFlagRecord,
    TimelineTopicClusterRecord,
)
from codex_sdk_cli.domains.transcript_cues.ports import (
    TranscriptCueRecord,
    TranscriptCueSummaryRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskCreate, VideoTaskRecord
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataFilters,
    YouTubeTranscriptMetadataRecord,
)

from .recording import EvaluationCheckpointWriter

NOW = datetime.now(UTC)


class SnapshotVideoRepository:
    def __init__(self, record: VideoRecord) -> None:
        self.record = record

    async def get_video(self, video_id: int) -> VideoRecord | None:
        return self.record if video_id == self.record.id else None


class SnapshotChannelRepository:
    def __init__(self, record: ChannelRecord) -> None:
        self.record = record

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        return self.record if channel_id == self.record.id else None


class SnapshotStreamerRepository:
    def __init__(self, record: StreamerRecord) -> None:
        self.record = record

    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        return self.record if streamer_id == self.record.id else None


class SnapshotTranscriptRepository:
    def __init__(self, record: YouTubeTranscriptMetadataRecord) -> None:
        self.record = record

    async def list_transcript_metadata(
        self, filters: YouTubeTranscriptMetadataFilters
    ) -> list[YouTubeTranscriptMetadataRecord]:
        if filters.video_id is not None and filters.video_id != self.record.video_id:
            return []
        return [self.record]


class SnapshotCueRepository:
    def __init__(self, records: list[TranscriptCueRecord]) -> None:
        self.records = records

    async def list_cues(self, transcript_id: int) -> list[TranscriptCueRecord]:
        return [record for record in self.records if record.transcript_id == transcript_id]

    async def summarize_cues(self, transcript_id: int) -> TranscriptCueSummaryRecord:
        records = await self.list_cues(transcript_id)
        return TranscriptCueSummaryRecord(
            transcript_id=transcript_id,
            cue_count=len(records),
            first_cue_id=records[0].cue_id if records else None,
            last_cue_id=records[-1].cue_id if records else None,
            source_job_id=None,
            source_work_item_id=None,
        )


class SnapshotDomainKnowledgeRepository:
    def __init__(self, records: list[DomainKnowledgePromptEntryRecord]) -> None:
        self.records = records

    async def list_prompt_entries_for_streamer(
        self, streamer_id: int | None
    ) -> list[DomainKnowledgePromptEntryRecord]:
        del streamer_id
        return self.records


class SnapshotPromptResolver:
    def __init__(self, prompts: dict[PromptKey, ResolvedPrompt]) -> None:
        self._prompts = prompts

    async def resolve_prompt(self, prompt_key: PromptKey) -> ResolvedPrompt:
        return self._prompts[prompt_key]

    async def resolve_prompt_for_request(
        self, prompt_key: PromptKey, version_id: int | None
    ) -> ResolvedPrompt:
        del version_id
        return self._prompts[prompt_key]

    async def resolve_prompt_version(
        self, prompt_key: PromptKey, version_id: int | None
    ) -> ResolvedPrompt:
        del version_id
        return self._prompts[prompt_key]


class NoopEvaluationEventRecorder:
    async def record_event(self, event: OperationEventCreate) -> None:
        del event


class MemoryVideoTaskRepository:
    def __init__(self, *, video: VideoRecord, task_id: int, resume: bool) -> None:
        self.video = video
        self.task_id = task_id
        self.tasks: dict[int, VideoTaskRecord] = {}
        self._resume = resume

    def seed_source(self, task: VideoTaskRecord) -> None:
        self.tasks[task.id] = task

    async def get_task(self, task_id: int) -> VideoTaskRecord | None:
        return self.tasks.get(task_id)

    async def get_task_for_input(
        self,
        *,
        video_id: int,
        task_name: str,
        task_version: str,
        input_hash: str,
    ) -> VideoTaskRecord | None:
        return next(
            (
                task
                for task in self.tasks.values()
                if task.video_id == video_id
                and task.task_name == task_name
                and task.task_version == task_version
                and task.input_hash == input_hash
            ),
            None,
        )

    async def get_or_create_task(self, create: VideoTaskCreate) -> VideoTaskRecord:
        existing = await self.get_task_for_input(
            video_id=create.video_id,
            task_name=create.task_name,
            task_version=create.task_version,
            input_hash=create.input_hash,
        )
        if existing is not None:
            return existing
        evaluation_task = next(
            (
                task
                for task in self.tasks.values()
                if task.id == self.task_id and task.task_name == create.task_name
            ),
            None,
        )
        if evaluation_task is not None:
            updated = replace(
                evaluation_task,
                input_hash=create.input_hash,
                input_json=create.input_json,
                status="failed" if self._resume else create.status,
                updated_at=NOW,
            )
            self.tasks[updated.id] = updated
            return updated
        record = VideoTaskRecord(
            id=self.task_id,
            video_id=create.video_id,
            task_name=create.task_name,
            task_version=create.task_version,
            input_hash=create.input_hash,
            status=create.status,
            worker_id=None,
            timeout_seconds=create.timeout_seconds,
            job_id=None,
            job_attempt_id=None,
            output_transcript_id=None,
            output_json=None,
            error_type=None,
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=NOW,
            updated_at=NOW,
            input_json=create.input_json,
        )
        self.tasks[record.id] = record
        return record

    async def get_latest_succeeded_task_for_video(
        self, *, video_id: int, task_name: str
    ) -> VideoTaskRecord | None:
        candidates = [
            task
            for task in self.tasks.values()
            if task.video_id == video_id
            and task.task_name == task_name
            and task.status == "succeeded"
        ]
        return max(candidates, key=lambda task: task.id, default=None)

    async def count_running(self, *, task_name: str) -> int:
        return sum(
            task.task_name == task_name and task.status == "running" for task in self.tasks.values()
        )

    async def claim_pending_task(self, task_id: int, *, worker_id: str) -> VideoTaskRecord | None:
        task = self.tasks.get(task_id)
        if task is None or task.status != "pending":
            return None
        return self._update(
            task_id,
            status="running",
            worker_id=worker_id,
            started_at=NOW,
            completed_at=None,
        )

    async def reset_task_to_pending(
        self, task_id: int, *, timeout_seconds: int, input_json: JsonObject
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="pending",
            timeout_seconds=timeout_seconds,
            input_json=input_json,
            worker_id=None,
            job_id=None,
            job_attempt_id=None,
            error_type=None,
            error_message=None,
        )

    async def attach_task_execution(
        self, task_id: int, *, job_id: int, job_attempt_id: int
    ) -> VideoTaskRecord:
        return self._update(task_id, job_id=job_id, job_attempt_id=job_attempt_id)

    async def mark_task_running(
        self,
        task_id: int,
        *,
        worker_id: str,
        timeout_seconds: int,
        job_id: int,
        job_attempt_id: int,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="running",
            worker_id=worker_id,
            timeout_seconds=timeout_seconds,
            job_id=job_id,
            job_attempt_id=job_attempt_id,
            started_at=NOW,
            completed_at=None,
        )

    async def mark_task_succeeded(
        self,
        task_id: int,
        *,
        output_transcript_id: int | None,
        output_json: JsonObject,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="succeeded",
            output_transcript_id=output_transcript_id,
            output_json=output_json,
            error_type=None,
            error_message=None,
            completed_at=NOW,
        )

    async def mark_task_failed(
        self,
        task_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="failed",
            output_json=output_json,
            error_type=error_type,
            error_message=error_message,
            completed_at=NOW,
        )

    async def mark_task_timed_out(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="timed_out",
            output_json=output_json,
            error_type="TimeoutError",
            error_message=error_message,
            completed_at=NOW,
        )

    def _update(self, task_id: int, **updates: Any) -> VideoTaskRecord:
        updated = replace(self.tasks[task_id], updated_at=NOW, **updates)
        self.tasks[task_id] = updated
        return updated


class MemoryPipelineJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[int, PipelineJobRecord] = {}
        self.attempts: dict[int, PipelineJobAttemptRecord] = {}
        self.next_job_id = 1
        self.next_attempt_id = 1

    async def create_job(self, create: PipelineJobCreate) -> PipelineJobRecord:
        record = PipelineJobRecord(
            id=self.next_job_id,
            step=create.step,
            status=create.status,
            subject_type=create.subject_type,
            subject_id=create.subject_id,
            external_key=create.external_key,
            input_json=create.input_json,
            input_hash=create.input_hash,
            parent_job_id=create.parent_job_id,
            created_at=NOW,
            updated_at=NOW,
            completed_at=None,
        )
        self.jobs[record.id] = record
        self.next_job_id += 1
        return record

    async def create_attempt(
        self, *, job_id: int, worker_id: str | None = None
    ) -> PipelineJobAttemptRecord:
        record = PipelineJobAttemptRecord(
            id=self.next_attempt_id,
            job_id=job_id,
            attempt_no=1,
            status="running",
            started_at=NOW,
            finished_at=None,
            worker_id=worker_id,
            error_type=None,
            error_message=None,
            output_json=None,
        )
        self.attempts[record.id] = record
        self.next_attempt_id += 1
        return record

    async def mark_attempt_succeeded(
        self, attempt_id: int, *, output_json: JsonObject
    ) -> PipelineJobAttemptRecord:
        return self._update_attempt(attempt_id, "succeeded", output_json, None, None)

    async def mark_attempt_failed(
        self,
        attempt_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> PipelineJobAttemptRecord:
        return self._update_attempt(attempt_id, "failed", output_json, error_type, error_message)

    async def mark_job_succeeded(self, job_id: int) -> PipelineJobRecord:
        return self._update_job(job_id, "succeeded")

    async def mark_job_failed(self, job_id: int) -> PipelineJobRecord:
        return self._update_job(job_id, "failed")

    def _update_attempt(
        self,
        attempt_id: int,
        status: str,
        output_json: JsonObject | None,
        error_type: str | None,
        error_message: str | None,
    ) -> PipelineJobAttemptRecord:
        record = replace(
            self.attempts[attempt_id],
            status=cast(Any, status),
            finished_at=NOW,
            output_json=output_json,
            error_type=error_type,
            error_message=error_message,
        )
        self.attempts[attempt_id] = record
        return record

    def _update_job(self, job_id: int, status: str) -> PipelineJobRecord:
        record = replace(
            self.jobs[job_id],
            status=cast(Any, status),
            updated_at=NOW,
            completed_at=NOW,
        )
        self.jobs[job_id] = record
        return record


class MemoryMicroEventRepository:
    def __init__(
        self,
        *,
        video: VideoRecord,
        tasks: MemoryVideoTaskRepository,
        checkpoint_writer: EvaluationCheckpointWriter | None = None,
    ) -> None:
        self.video = video
        self.tasks = tasks
        self.checkpoint_writer = checkpoint_writer
        self.windows_by_task: dict[int, list[MicroEventExtractionWindowRecord]] = {}

    async def delete_extraction(self, video_task_id: int) -> None:
        self.windows_by_task.pop(video_task_id, None)

    async def replace_extraction(
        self, video_task_id: int, windows: list[MicroEventExtractionWindowCreate]
    ) -> MicroEventExtractionDetailRecord | None:
        self.windows_by_task[video_task_id] = [_micro_window_record(window) for window in windows]
        return await self.get_extraction(video_id=self.video.id, video_task_id=video_task_id)

    async def upsert_window(
        self, video_task_id: int, window: MicroEventExtractionWindowCreate
    ) -> MicroEventExtractionWindowRecord:
        record = _micro_window_record(window)
        records = [
            item
            for item in self.windows_by_task.get(video_task_id, [])
            if item.window_index != window.window_index
        ]
        records.append(record)
        self.windows_by_task[video_task_id] = sorted(records, key=lambda item: item.window_index)
        if self.checkpoint_writer is not None:
            await self.checkpoint_writer.write(
                window_index=window.window_index,
                status=window.status,
                payload=cast(JsonObject, _jsonable(asdict(window))),
            )
        return record

    async def get_extraction(
        self, *, video_id: int, video_task_id: int
    ) -> MicroEventExtractionDetailRecord | None:
        task = self.tasks.tasks.get(video_task_id)
        if task is None or video_id != self.video.id:
            return None
        return MicroEventExtractionDetailRecord(
            video_task_id=task.id,
            video_id=self.video.id,
            youtube_video_id=self.video.youtube_video_id,
            transcript_id=task.output_transcript_id,
            status=task.status,
            job_id=task.job_id,
            job_attempt_id=task.job_attempt_id,
            output_json=task.output_json,
            error_type=task.error_type,
            error_message=task.error_message,
            started_at=task.started_at,
            completed_at=task.completed_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
            windows=self.windows_by_task.get(video_task_id, []),
        )

    async def get_latest_succeeded_extraction(
        self, *, video_id: int
    ) -> MicroEventExtractionDetailRecord | None:
        task = await self.tasks.get_latest_succeeded_task_for_video(
            video_id=video_id, task_name="micro_event_extract"
        )
        if task is None:
            return None
        return await self.get_extraction(video_id=video_id, video_task_id=task.id)

    def seed_windows(
        self, video_task_id: int, windows: list[MicroEventExtractionWindowCreate]
    ) -> None:
        self.windows_by_task[video_task_id] = [_micro_window_record(window) for window in windows]

    def seed_detail(self, video_task_id: int, detail: MicroEventExtractionDetailRecord) -> None:
        self.windows_by_task[video_task_id] = [
            replace(
                window,
                video_task_id=video_task_id,
                micro_events=[
                    replace(candidate, video_task_id=video_task_id)
                    for candidate in window.micro_events
                ],
                excluded_ranges=[
                    replace(item, video_task_id=video_task_id) for item in window.excluded_ranges
                ],
                asr_correction_candidates=[
                    replace(item, video_task_id=video_task_id)
                    for item in window.asr_correction_candidates
                ],
            )
            for window in detail.windows
        ]


class MemoryTimelineRepository:
    def __init__(self, *, video: VideoRecord) -> None:
        self.video = video
        self.records: dict[int, TimelineCompositionRecord] = {}

    async def delete_composition(self, video_task_id: int) -> None:
        self.records.pop(video_task_id, None)

    async def replace_composition(
        self, create: TimelineCompositionCreate
    ) -> TimelineCompositionRecord:
        record = TimelineCompositionRecord(
            id=create.video_task_id,
            video_task_id=create.video_task_id,
            video_id=create.video_id,
            youtube_video_id=self.video.youtube_video_id,
            source_micro_event_task_id=create.source_micro_event_task_id,
            source_micro_event_fingerprint=create.source_micro_event_fingerprint,
            copy_style=create.copy_style,
            status="succeeded",
            model=create.model,
            reasoning_effort=create.reasoning_effort,
            title=create.title,
            summary=create.summary,
            display_title=create.display_title,
            display_summary=create.display_summary,
            main_topics=create.main_topics,
            output_json=create.output_json,
            validation_warnings=create.validation_warnings,
            source_job_id=create.source_job_id,
            source_job_attempt_id=create.source_job_attempt_id,
            codex_thread_id=create.codex_thread_id,
            codex_turn_id=create.codex_turn_id,
            raw_response_text=create.raw_response_text,
            created_at=NOW,
            updated_at=NOW,
            blocks=[
                TimelineBlockRecord(
                    **asdict(item),
                    id=index,
                    composition_id=create.video_task_id,
                    created_at=NOW,
                    updated_at=NOW,
                )
                for index, item in enumerate(create.blocks, start=1)
            ],
            episodes=[
                TimelineEpisodeRecord(
                    **asdict(item),
                    id=index,
                    composition_id=create.video_task_id,
                    created_at=NOW,
                    updated_at=NOW,
                )
                for index, item in enumerate(create.episodes, start=1)
            ],
            topic_clusters=[
                TimelineTopicClusterRecord(
                    **asdict(item),
                    id=index,
                    composition_id=create.video_task_id,
                    created_at=NOW,
                    updated_at=NOW,
                )
                for index, item in enumerate(create.topic_clusters, start=1)
            ],
            review_flags=[
                TimelineReviewFlagRecord(
                    **asdict(item),
                    id=index,
                    composition_id=create.video_task_id,
                    created_at=NOW,
                    updated_at=NOW,
                )
                for index, item in enumerate(create.review_flags, start=1)
            ],
        )
        self.records[create.video_task_id] = record
        return record

    async def get_composition(
        self, *, video_id: int, video_task_id: int
    ) -> TimelineCompositionRecord | None:
        if video_id != self.video.id:
            return None
        return self.records.get(video_task_id)

    async def get_latest_succeeded_composition(
        self, *, video_id: int
    ) -> TimelineCompositionRecord | None:
        candidates = [record for record in self.records.values() if record.video_id == video_id]
        return max(candidates, key=lambda item: item.video_task_id, default=None)


def snapshot_records(
    snapshot: JsonObject,
) -> tuple[
    VideoRecord,
    ChannelRecord,
    StreamerRecord,
    YouTubeTranscriptMetadataRecord,
    list[TranscriptCueRecord],
    list[DomainKnowledgePromptEntryRecord],
]:
    video = cast(dict[str, object], snapshot["video"])
    channel = cast(dict[str, object], snapshot["channel"])
    streamer = cast(dict[str, object], snapshot["streamer"])
    transcript = cast(dict[str, object], snapshot["transcript"])
    cues = cast(list[dict[str, object]], snapshot["cues"])
    domain = cast(list[dict[str, object]], snapshot.get("domainKnowledge") or [])
    return (
        VideoRecord(
            id=_int(video, "id"),
            channel_id=_int(video, "channel_id"),
            youtube_video_id=_str(video, "youtube_video_id"),
            title=_str(video, "title"),
            description=str(video.get("description") or ""),
            published_at=_datetime(video.get("published_at")),
            duration=_optional_str(video.get("duration")),
            thumbnail_url=_optional_str(video.get("thumbnail_url")),
            source_listing_api_call_id=_optional_int(video.get("source_listing_api_call_id")),
            source_details_api_call_id=_optional_int(video.get("source_details_api_call_id")),
            source_job_id=_optional_int(video.get("source_job_id")),
            created_at=_datetime(video.get("created_at")),
            updated_at=_datetime(video.get("updated_at")),
            is_embeddable=cast(bool | None, video.get("is_embeddable")),
            embed_status_checked_at=_optional_datetime(video.get("embed_status_checked_at")),
            source_embed_status_api_call_id=_optional_int(
                video.get("source_embed_status_api_call_id")
            ),
        ),
        ChannelRecord(
            id=_int(channel, "id"),
            streamer_id=_int(channel, "streamer_id"),
            handle=_str(channel, "handle"),
            name=_str(channel, "name"),
            youtube_channel_id=_optional_str(channel.get("youtube_channel_id")),
            uploads_playlist_id=_optional_str(channel.get("uploads_playlist_id")),
            source_api_call_id=_optional_int(channel.get("source_api_call_id")),
            source_job_id=_optional_int(channel.get("source_job_id")),
        ),
        StreamerRecord(
            id=_int(streamer, "id"),
            name=_str(streamer, "name"),
            publish_profile_id=_int(streamer, "publish_profile_id"),
        ),
        YouTubeTranscriptMetadataRecord(
            id=_int(transcript, "id"),
            video_id=_str(transcript, "video_id"),
            language=_str(transcript, "language"),
            language_code=_str(transcript, "language_code"),
            is_generated=bool(transcript.get("is_generated")),
            requested_languages=tuple(
                str(item)
                for item in cast(list[object], transcript.get("requested_languages") or [])
            ),
            preserve_formatting=bool(transcript.get("preserve_formatting")),
            storage_bucket=_str(transcript, "storage_bucket"),
            storage_object_name=_str(transcript, "storage_object_name"),
            storage_uri=_str(transcript, "storage_uri"),
            response_sha256=_str(transcript, "response_sha256"),
            segment_count=_int(transcript, "segment_count"),
            text_length=_int(transcript, "text_length"),
            notes=_optional_str(transcript.get("notes")),
            created_at=_datetime(transcript.get("created_at")),
            updated_at=_datetime(transcript.get("updated_at")),
        ),
        [_cue_record(item) for item in cues],
        [_domain_record(item) for item in domain],
    )


def resolved_prompt(payload: JsonObject) -> ResolvedPrompt:
    return ResolvedPrompt(
        key=cast(PromptKey, _str(payload, "key")),
        version_id=_optional_int(payload.get("versionId")),
        version_label=_str(payload, "versionLabel"),
        body=_str(payload, "body"),
        body_sha256=_str(payload, "bodySha256"),
        source=cast(Any, _str(payload, "source")),
    )


def window_create_from_json(payload: JsonObject) -> MicroEventExtractionWindowCreate:
    from codex_sdk_cli.domains.micro_events.ports import (
        AsrCorrectionCandidateCreate,
        MicroEventCandidateCreate,
        MicroEventExcludedRangeCreate,
    )

    return MicroEventExtractionWindowCreate(
        video_task_id=_int(payload, "video_task_id"),
        video_id=_int(payload, "video_id"),
        transcript_id=_int(payload, "transcript_id"),
        window_index=_int(payload, "window_index"),
        start_cue_id=_str(payload, "start_cue_id"),
        end_cue_id=_str(payload, "end_cue_id"),
        cue_count=_int(payload, "cue_count"),
        status=cast(Any, _str(payload, "status")),
        carry_out_unfinished=bool(payload.get("carry_out_unfinished")),
        codex_thread_id=_optional_str(payload.get("codex_thread_id")),
        codex_turn_id=_optional_str(payload.get("codex_turn_id")),
        raw_response_text=_optional_str(payload.get("raw_response_text")),
        parsed_response_json=cast(JsonObject | None, payload.get("parsed_response_json")),
        validation_error=_optional_str(payload.get("validation_error")),
        source_job_id=_int(payload, "source_job_id"),
        source_job_attempt_id=_int(payload, "source_job_attempt_id"),
        micro_events=[
            MicroEventCandidateCreate(**cast(dict[str, Any], item))
            for item in cast(list[object], payload.get("micro_events") or [])
        ],
        excluded_ranges=[
            MicroEventExcludedRangeCreate(**cast(dict[str, Any], item))
            for item in cast(list[object], payload.get("excluded_ranges") or [])
        ],
        asr_correction_candidates=[
            AsrCorrectionCandidateCreate(**cast(dict[str, Any], item))
            for item in cast(list[object], payload.get("asr_correction_candidates") or [])
        ],
    )


def micro_detail_from_json(payload: JsonObject) -> MicroEventExtractionDetailRecord:
    windows = [
        _window_record_from_json(cast(JsonObject, item))
        for item in cast(list[object], payload.get("windows") or [])
    ]
    return MicroEventExtractionDetailRecord(
        video_task_id=_int(payload, "video_task_id"),
        video_id=_int(payload, "video_id"),
        youtube_video_id=_str(payload, "youtube_video_id"),
        transcript_id=_optional_int(payload.get("transcript_id")),
        status=cast(Any, _str(payload, "status")),
        job_id=_optional_int(payload.get("job_id")),
        job_attempt_id=_optional_int(payload.get("job_attempt_id")),
        output_json=cast(JsonObject | None, payload.get("output_json")),
        error_type=_optional_str(payload.get("error_type")),
        error_message=_optional_str(payload.get("error_message")),
        started_at=_optional_datetime(payload.get("started_at")),
        completed_at=_optional_datetime(payload.get("completed_at")),
        created_at=_datetime(payload.get("created_at")),
        updated_at=_datetime(payload.get("updated_at")),
        windows=windows,
    )


def _micro_window_record(
    window: MicroEventExtractionWindowCreate,
) -> MicroEventExtractionWindowRecord:
    window_id = window.window_index + 1
    return MicroEventExtractionWindowRecord(
        id=window_id,
        video_task_id=window.video_task_id,
        video_id=window.video_id,
        transcript_id=window.transcript_id,
        window_index=window.window_index,
        start_cue_id=window.start_cue_id,
        end_cue_id=window.end_cue_id,
        cue_count=window.cue_count,
        status=window.status,
        carry_out_unfinished=window.carry_out_unfinished,
        codex_thread_id=window.codex_thread_id,
        codex_turn_id=window.codex_turn_id,
        raw_response_text=window.raw_response_text,
        parsed_response_json=window.parsed_response_json,
        validation_error=window.validation_error,
        source_job_id=window.source_job_id,
        source_job_attempt_id=window.source_job_attempt_id,
        created_at=NOW,
        updated_at=NOW,
        micro_events=[
            MicroEventCandidateRecord(
                id=window.window_index * 10_000 + item.candidate_index,
                window_id=window_id,
                video_task_id=window.video_task_id,
                transcript_id=window.transcript_id,
                created_at=NOW,
                updated_at=NOW,
                **asdict(item),
            )
            for item in window.micro_events
        ],
        excluded_ranges=[
            MicroEventExcludedRangeRecord(
                id=window.window_index * 10_000 + item.range_index,
                window_id=window_id,
                video_task_id=window.video_task_id,
                transcript_id=window.transcript_id,
                created_at=NOW,
                updated_at=NOW,
                **asdict(item),
            )
            for item in window.excluded_ranges
        ],
        asr_correction_candidates=[
            AsrCorrectionCandidateRecord(
                id=window.window_index * 10_000 + item.candidate_index,
                window_id=window_id,
                video_task_id=window.video_task_id,
                transcript_id=window.transcript_id,
                created_at=NOW,
                updated_at=NOW,
                **asdict(item),
            )
            for item in window.asr_correction_candidates
        ],
    )


def _window_record_from_json(payload: JsonObject) -> MicroEventExtractionWindowRecord:
    def record_list(key: str, cls: type[Any]) -> list[Any]:
        return [
            cls(**_with_datetimes(cast(dict[str, Any], item)))
            for item in cast(list[object], payload.get(key) or [])
        ]

    return MicroEventExtractionWindowRecord(
        **_with_datetimes(
            {
                **cast(dict[str, Any], payload),
                "micro_events": record_list("micro_events", MicroEventCandidateRecord),
                "excluded_ranges": record_list("excluded_ranges", MicroEventExcludedRangeRecord),
                "asr_correction_candidates": record_list(
                    "asr_correction_candidates", AsrCorrectionCandidateRecord
                ),
            }
        )
    )


def _cue_record(payload: dict[str, object]) -> TranscriptCueRecord:
    return TranscriptCueRecord(
        id=_int(payload, "id"),
        transcript_id=_int(payload, "transcript_id"),
        cue_id=_str(payload, "cue_id"),
        cue_index=_int(payload, "cue_index"),
        text=_str(payload, "text"),
        start_ms=_int(payload, "start_ms"),
        end_ms=_int(payload, "end_ms"),
        duration_ms=_int(payload, "duration_ms"),
        source_segment_index=_int(payload, "source_segment_index"),
        source_job_id=_optional_int(payload.get("source_job_id")),
        source_job_attempt_id=_optional_int(payload.get("source_job_attempt_id")),
        source_work_item_id=_optional_int(payload.get("source_work_item_id")),
        source_work_attempt_id=_optional_int(payload.get("source_work_attempt_id")),
        created_at=_datetime(payload.get("created_at")),
        updated_at=_datetime(payload.get("updated_at")),
    )


def _domain_record(payload: dict[str, object]) -> DomainKnowledgePromptEntryRecord:
    aliases = [
        DomainKnowledgePromptAliasRecord(**cast(dict[str, Any], item))
        for item in cast(list[object], payload.get("aliases") or [])
    ]
    return DomainKnowledgePromptEntryRecord(
        entry_id=_int(payload, "entry_id"),
        type_key=_str(payload, "type_key"),
        type_label=_str(payload, "type_label"),
        canonical_name=_str(payload, "canonical_name"),
        display_name=_optional_str(payload.get("display_name")),
        disambiguation=_optional_str(payload.get("disambiguation")),
        detail=_optional_str(payload.get("detail")),
        prompt_policy=cast(Any, _str(payload, "prompt_policy")),
        priority=_int(payload, "priority"),
        aliases=aliases,
    )


def _with_datetimes(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    for key in ("created_at", "updated_at", "started_at", "completed_at"):
        if key in result:
            result[key] = _optional_datetime(result[key])
    return result


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Missing snapshot string: {key}")
    return value


def _int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Missing snapshot integer: {key}")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _datetime(value: object) -> datetime:
    result = _optional_datetime(value)
    if result is None:
        return NOW
    return result


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None
