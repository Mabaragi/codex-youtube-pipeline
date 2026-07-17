from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_channel_repository,
    get_domain_knowledge_repository,
    get_llm_trace_recorder,
    get_micro_event_extraction_repository,
    get_micro_event_extractor,
    get_operation_event_recorder,
    get_pipeline_job_repository,
    get_settings,
    get_streamer_repository,
    get_transcript_cue_repository,
    get_video_repository,
    get_video_task_repository,
    get_youtube_transcript_repository,
)
from codex_sdk_cli.api.use_case_dependencies.prompts import get_prompt_resolver
from codex_sdk_cli.domains.channels.ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelRepositoryPort,
    ChannelUpdate,
)
from codex_sdk_cli.domains.domain_knowledge.ports import (
    DomainEntryAliasCreate,
    DomainEntryAliasRecord,
    DomainEntryAliasUpdate,
    DomainEntryCreate,
    DomainEntryListQuery,
    DomainEntryRecord,
    DomainEntryStreamerLinkCreate,
    DomainEntryTypeCreate,
    DomainEntryTypeRecord,
    DomainEntryUpdate,
    DomainKnowledgePromptAliasRecord,
    DomainKnowledgePromptEntryRecord,
    DomainKnowledgeRepositoryPort,
)
from codex_sdk_cli.domains.llm_traces.ports import (
    LlmTraceRecorderPort,
    NoopLlmTraceRecorder,
)
from codex_sdk_cli.domains.micro_events.ports import (
    AsrCorrectionCandidateRecord,
    MicroEventCandidateRecord,
    MicroEventExcludedRangeRecord,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionRepositoryPort,
    MicroEventExtractionRequest,
    MicroEventExtractionResult,
    MicroEventExtractionWindowCreate,
    MicroEventExtractionWindowRecord,
    MicroEventExtractorPort,
    MicroEventRepairRequest,
)
from codex_sdk_cli.domains.micro_events.use_cases import ExtractVideoMicroEventsUseCase
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobAttemptStatus,
    PipelineJobCreate,
    PipelineJobDetailRecord,
    PipelineJobListQuery,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
    PipelineJobStatus,
    PipelineJobSummaryRecord,
)
from codex_sdk_cli.domains.prompts.constants import (
    MICRO_EVENT_EXTRACT_PROMPT_KEY,
    PromptKey,
)
from codex_sdk_cli.domains.prompts.exceptions import PromptConflict, PromptNotFound
from codex_sdk_cli.domains.prompts.fallbacks import fallback_prompt
from codex_sdk_cli.domains.prompts.ports import ResolvedPrompt
from codex_sdk_cli.domains.streamers.ports import StreamerRecord, StreamerRepositoryPort
from codex_sdk_cli.domains.transcript_cues.ports import (
    TranscriptCueCreate,
    TranscriptCueRecord,
    TranscriptCueRepositoryPort,
    TranscriptCueSummaryRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import (
    VideoTaskCreate,
    VideoTaskListQuery,
    VideoTaskListRecord,
    VideoTaskRecord,
    VideoTaskRepositoryPort,
    VideoTaskWithVideoRecord,
)
from codex_sdk_cli.domains.videos.ports import VideoCreate, VideoRecord, VideoRepositoryPort
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    YouTubeTranscriptMetadataFilters,
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptRecord,
    YouTubeTranscriptRepositoryPort,
)
from codex_sdk_cli.infra.llm_traces.writer import FileLlmTraceRecorder
from codex_sdk_cli.settings import CliSettings
from tests.support.legacy_api import create_legacy_app as create_app

NOW = datetime(2026, 6, 23, 1, 2, tzinfo=UTC)
YOUTUBE_VIDEO_ID = "abc123DEF45"


class FakeVideoRepository(VideoRepositoryPort):
    def __init__(self) -> None:
        self.videos: dict[int, VideoRecord] = {}

    async def get_video(self, video_id: int) -> VideoRecord | None:
        return self.videos.get(video_id)

    async def get_video_by_youtube_video_id(
        self,
        youtube_video_id: str,
    ) -> VideoRecord | None:
        return next(
            (
                video
                for video in self.videos.values()
                if video.youtube_video_id == youtube_video_id
            ),
            None,
        )

    async def list_all_videos(self) -> list[VideoRecord]:
        return list(self.videos.values())

    async def list_videos(self, *, channel_id: int) -> list[VideoRecord]:
        return [video for video in self.videos.values() if video.channel_id == channel_id]

    async def find_existing_youtube_video_id(
        self,
        *,
        channel_id: int,
        youtube_video_ids: tuple[str, ...],
    ) -> str | None:
        return None

    async def create_videos(self, videos: list[VideoCreate]) -> list[VideoRecord]:
        return []

    async def list_videos_for_embed_status_refresh(
        self,
        *,
        video_ids: tuple[int, ...] | None,
        limit: int,
    ) -> list[VideoRecord]:
        records = list(self.videos.values())
        if video_ids is not None:
            requested = set(video_ids)
            records = [record for record in records if record.id in requested]
        return records[:limit]

    async def update_embed_status(
        self,
        video_id: int,
        *,
        is_embeddable: bool | None,
        checked_at: datetime,
        source_api_call_id: int | None,
    ) -> VideoRecord:
        record = self.videos[video_id]
        updated = replace(
            record,
            is_embeddable=is_embeddable,
            embed_status_checked_at=checked_at,
            source_embed_status_api_call_id=source_api_call_id,
            updated_at=checked_at,
        )
        self.videos[video_id] = updated
        return updated


class FakeVideoTaskRepository(VideoTaskRepositoryPort):
    def __init__(self, videos: FakeVideoRepository) -> None:
        self.videos = videos
        self.tasks: dict[int, VideoTaskRecord] = {}
        self.next_id = 1

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
        return self._find(video_id, task_name, task_version, input_hash)

    async def get_or_create_task(self, task: VideoTaskCreate) -> VideoTaskRecord:
        existing = self._find(
            task.video_id,
            task.task_name,
            task.task_version,
            task.input_hash,
        )
        if existing is not None:
            return existing
        record = VideoTaskRecord(
            id=self.next_id,
            video_id=task.video_id,
            task_name=task.task_name,
            task_version=task.task_version,
            input_hash=task.input_hash,
            status=task.status,
            worker_id=None,
            timeout_seconds=task.timeout_seconds,
            input_json=task.input_json,
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
        )
        self.tasks[record.id] = record
        self.next_id += 1
        return record

    async def list_tasks(self, query: VideoTaskListQuery) -> list[VideoTaskListRecord]:
        records: list[VideoTaskListRecord] = []
        for task in self.tasks.values():
            video = self.videos.videos[task.video_id]
            if video.channel_id != query.channel_id:
                continue
            if query.task_name is not None and task.task_name != query.task_name:
                continue
            if query.status is not None and task.status != query.status:
                continue
            records.append(VideoTaskListRecord(task=task, youtube_video_id=video.youtube_video_id))
        return records

    async def list_latest_succeeded_tasks(
        self,
        *,
        task_name: str,
        channel_id: int | None,
        limit: int,
    ) -> list[VideoTaskWithVideoRecord]:
        latest_by_video: dict[int, VideoTaskRecord] = {}
        for task in self.tasks.values():
            if (
                task.task_name != task_name
                or task.status != "succeeded"
                or task.output_transcript_id is None
            ):
                continue
            video = self.videos.videos.get(task.video_id)
            if video is None:
                continue
            if channel_id is not None and video.channel_id != channel_id:
                continue
            current = latest_by_video.get(task.video_id)
            if current is None or task.id > current.id:
                latest_by_video[task.video_id] = task
        records = [
            VideoTaskWithVideoRecord(
                task=task,
                video=self.videos.videos[task.video_id],
            )
            for task in latest_by_video.values()
        ]
        records.sort(
            key=lambda record: (record.video.published_at, record.video.id),
            reverse=True,
        )
        return records[:limit]

    async def list_no_transcript_tasks_due_for_recheck(
        self,
        *,
        task_name: str,
        completed_before: datetime,
        limit: int,
    ) -> list[VideoTaskWithVideoRecord]:
        records = [
            VideoTaskWithVideoRecord(task=task, video=video)
            for task in self.tasks.values()
            if task.task_name == task_name
            and task.status == "no_transcript"
            and task.completed_at is not None
            and task.completed_at <= completed_before
            for video in [self.videos.videos.get(task.video_id)]
            if video is not None
        ]
        return sorted(
            records,
            key=lambda record: (
                record.task.completed_at or datetime.max.replace(tzinfo=UTC),
                record.task.updated_at,
                record.task.id,
            ),
        )[:limit]

    async def get_latest_succeeded_task_for_video(
        self,
        *,
        video_id: int,
        task_name: str,
    ) -> VideoTaskRecord | None:
        candidates = [
            task
            for task in self.tasks.values()
            if task.video_id == video_id
            and task.task_name == task_name
            and task.status == "succeeded"
            and task.output_transcript_id is not None
        ]
        return max(candidates, key=lambda task: task.id, default=None)

    async def get_latest_task_for_video(self, video_id: int) -> VideoTaskRecord | None:
        candidates = [task for task in self.tasks.values() if task.video_id == video_id]
        return max(candidates, key=lambda task: task.id, default=None)

    async def count_running(self, *, task_name: str) -> int:
        return sum(
            task.task_name == task_name and task.status == "running"
            for task in self.tasks.values()
        )

    async def claim_next_pending_task(
        self,
        *,
        task_name: str,
        worker_id: str,
    ) -> VideoTaskRecord | None:
        candidates = sorted(
            (
                task
                for task in self.tasks.values()
                if task.task_name == task_name and task.status == "pending"
            ),
            key=lambda task: task.id,
        )
        if not candidates:
            return None
        return self._update(
            candidates[0].id,
            status="running",
            worker_id=worker_id,
            error_type=None,
            error_message=None,
            started_at=NOW,
            completed_at=None,
        )

    async def claim_pending_task(
        self,
        task_id: int,
        *,
        worker_id: str,
    ) -> VideoTaskRecord | None:
        task = self.tasks.get(task_id)
        if task is None or task.status != "pending":
            return None
        return self._update(
            task_id,
            status="running",
            worker_id=worker_id,
            error_type=None,
            error_message=None,
            started_at=NOW,
            completed_at=None,
        )

    async def claim_next_pending_task_excluding_running_video(
        self,
        *,
        task_name: str,
        worker_id: str,
    ) -> VideoTaskRecord | None:
        running_video_ids = {
            task.video_id
            for task in self.tasks.values()
            if task.task_name == task_name and task.status == "running"
        }
        candidates = sorted(
            (
                task
                for task in self.tasks.values()
                if task.task_name == task_name
                and task.status == "pending"
                and task.video_id not in running_video_ids
            ),
            key=lambda task: task.id,
        )
        if not candidates:
            return None
        return self._update(
            candidates[0].id,
            status="running",
            worker_id=worker_id,
            error_type=None,
            error_message=None,
            started_at=NOW,
            completed_at=None,
        )

    async def reset_task_to_pending(
        self,
        task_id: int,
        *,
        timeout_seconds: int,
        input_json: JsonObject,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="pending",
            worker_id=None,
            timeout_seconds=timeout_seconds,
            input_json=input_json,
            job_id=None,
            job_attempt_id=None,
            output_transcript_id=None,
            output_json=None,
            error_type=None,
            error_message=None,
            started_at=None,
            completed_at=None,
        )

    async def attach_task_execution(
        self,
        task_id: int,
        *,
        job_id: int,
        job_attempt_id: int,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            job_id=job_id,
            job_attempt_id=job_attempt_id,
        )

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
            error_type=None,
            error_message=None,
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

    async def mark_task_no_transcript(
        self,
        task_id: int,
        *,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> VideoTaskRecord:
        return self._update(
            task_id,
            status="no_transcript",
            output_json=output_json,
            error_type="YouTubeTranscriptNotFound",
            error_message=error_message,
            completed_at=NOW,
        )

    async def cancel_pending_tasks(
        self,
        task_ids: list[int],
        *,
        error_type: str,
        error_message: str,
    ) -> list[VideoTaskRecord]:
        tasks = [self.tasks[task_id] for task_id in task_ids]
        if any(task.status != "pending" for task in tasks):
            return []
        return [
            self._update(
                task.id,
                status="canceled",
                error_type=error_type,
                error_message=error_message,
                completed_at=NOW,
            )
            for task in tasks
        ]

    async def cancel_pending_tasks_for_video(
        self,
        *,
        video_id: int,
        task_names: tuple[str, ...],
        error_type: str,
        error_message: str,
    ) -> list[VideoTaskRecord]:
        tasks = [
            task
            for task in self.tasks.values()
            if task.video_id == video_id
            and task.task_name in task_names
            and task.status == "pending"
        ]
        return [
            self._update(
                task.id,
                status="canceled",
                error_type=error_type,
                error_message=error_message,
                completed_at=NOW,
            )
            for task in tasks
        ]

    def _find(
        self,
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

    def _update(self, task_id: int, **updates: Any) -> VideoTaskRecord:
        updated = replace(self.tasks[task_id], updated_at=NOW, **updates)
        self.tasks[task_id] = updated
        return updated


class FakeTranscriptRepository(YouTubeTranscriptRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[int, YouTubeTranscriptMetadataRecord] = {}

    async def save_transcript_record(
        self,
        record: YouTubeTranscriptRecord,
    ) -> YouTubeTranscriptMetadataRecord:
        raise NotImplementedError

    async def find_transcript_metadata_for_request(
        self,
        *,
        video_id: str,
        requested_languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return None

    async def list_transcript_metadata(
        self,
        filters: YouTubeTranscriptMetadataFilters,
    ) -> list[YouTubeTranscriptMetadataRecord]:
        records = list(self.records.values())
        if filters.video_id is not None:
            records = [
                record for record in records if record.video_id == filters.video_id
            ]
        if filters.language_code is not None:
            records = [
                record
                for record in records
                if record.language_code == filters.language_code
            ]
        records.sort(key=lambda record: (record.created_at, record.id), reverse=True)
        return records[filters.offset : filters.offset + filters.limit]

    async def get_transcript_metadata(
        self,
        transcript_id: int,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return self.records.get(transcript_id)

    async def update_transcript_notes(
        self,
        transcript_id: int,
        notes: str | None,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return None

    async def delete_transcript_metadata(self, transcript_id: int) -> bool:
        return False


class FakeTranscriptCueRepository(TranscriptCueRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[int, list[TranscriptCueRecord]] = {}

    async def replace_cues(
        self,
        transcript_id: int,
        cues: list[TranscriptCueCreate],
    ) -> list[TranscriptCueRecord]:
        return []

    async def list_cues(self, transcript_id: int) -> list[TranscriptCueRecord]:
        return self.records.get(transcript_id, [])

    async def summarize_cues(self, transcript_id: int) -> TranscriptCueSummaryRecord:
        records = self.records.get(transcript_id, [])
        return TranscriptCueSummaryRecord(
            transcript_id=transcript_id,
            cue_count=len(records),
            first_cue_id=records[0].cue_id if records else None,
            last_cue_id=records[-1].cue_id if records else None,
            source_job_id=None,
        )


class FakePipelineJobRepository(PipelineJobRepositoryPort):
    def __init__(self) -> None:
        self.jobs: dict[int, PipelineJobRecord] = {}
        self.attempts: dict[int, PipelineJobAttemptRecord] = {}
        self.next_job_id = 1
        self.next_attempt_id = 1

    async def create_job(self, job: PipelineJobCreate) -> PipelineJobRecord:
        record = PipelineJobRecord(
            id=self.next_job_id,
            step=job.step,
            status=job.status,
            subject_type=job.subject_type,
            subject_id=job.subject_id,
            external_key=job.external_key,
            input_json=job.input_json,
            input_hash=job.input_hash,
            parent_job_id=job.parent_job_id,
            created_at=NOW,
            updated_at=NOW,
            completed_at=None,
        )
        self.jobs[record.id] = record
        self.next_job_id += 1
        return record

    async def get_job(self, job_id: int) -> PipelineJobRecord | None:
        return self.jobs.get(job_id)

    async def list_job_summaries(
        self,
        query: PipelineJobListQuery,
    ) -> list[PipelineJobSummaryRecord]:
        return []

    async def get_job_detail(self, job_id: int) -> PipelineJobDetailRecord | None:
        return None

    async def create_attempt(
        self,
        *,
        job_id: int,
        worker_id: str | None = None,
    ) -> PipelineJobAttemptRecord:
        attempt = PipelineJobAttemptRecord(
            id=self.next_attempt_id,
            job_id=job_id,
            attempt_no=sum(item.job_id == job_id for item in self.attempts.values()) + 1,
            status="running",
            started_at=NOW,
            finished_at=None,
            worker_id=worker_id,
            error_type=None,
            error_message=None,
            output_json=None,
        )
        self.attempts[attempt.id] = attempt
        self.next_attempt_id += 1
        return attempt

    async def mark_attempt_succeeded(
        self,
        attempt_id: int,
        *,
        output_json: JsonObject,
    ) -> PipelineJobAttemptRecord:
        return self._update_attempt(
            attempt_id,
            status="succeeded",
            output_json=output_json,
            error_type=None,
            error_message=None,
        )

    async def mark_attempt_failed(
        self,
        attempt_id: int,
        *,
        error_type: str,
        error_message: str,
        output_json: JsonObject | None = None,
    ) -> PipelineJobAttemptRecord:
        return self._update_attempt(
            attempt_id,
            status="failed",
            output_json=output_json,
            error_type=error_type,
            error_message=error_message,
        )

    async def mark_job_succeeded(self, job_id: int) -> PipelineJobRecord:
        return self._update_job(job_id, status="succeeded")

    async def mark_job_failed(self, job_id: int) -> PipelineJobRecord:
        return self._update_job(job_id, status="failed")

    async def mark_job_running(self, job_id: int) -> PipelineJobRecord:
        return self._update_job(job_id, status="running")

    def _update_attempt(
        self,
        attempt_id: int,
        *,
        status: PipelineJobAttemptStatus,
        output_json: JsonObject | None,
        error_type: str | None,
        error_message: str | None,
    ) -> PipelineJobAttemptRecord:
        updated = replace(
            self.attempts[attempt_id],
            status=status,
            finished_at=NOW,
            output_json=output_json,
            error_type=error_type,
            error_message=error_message,
        )
        self.attempts[attempt_id] = updated
        return updated

    def _update_job(self, job_id: int, *, status: PipelineJobStatus) -> PipelineJobRecord:
        updated = replace(
            self.jobs[job_id],
            status=status,
            updated_at=NOW,
            completed_at=None if status == "running" else NOW,
        )
        self.jobs[job_id] = updated
        return updated


class FakeChannelRepository(ChannelRepositoryPort):
    def __init__(self) -> None:
        self.channels: dict[int, ChannelRecord] = {
            1: ChannelRecord(
                id=1,
                streamer_id=1,
                handle="@streamer",
                name="Streamer Channel",
                youtube_channel_id="channel-1",
                uploads_playlist_id="uploads-1",
                source_api_call_id=None,
            )
        }

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        raise NotImplementedError

    async def list_channels(
        self,
        *,
        streamer_id: int | None = None,
    ) -> list[ChannelRecord]:
        if streamer_id is None:
            return list(self.channels.values())
        return [
            channel
            for channel in self.channels.values()
            if channel.streamer_id == streamer_id
        ]

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        return self.channels.get(channel_id)

    async def get_channel_by_youtube_channel_id(
        self,
        youtube_channel_id: str,
    ) -> ChannelRecord | None:
        return next(
            (
                channel
                for channel in self.channels.values()
                if channel.youtube_channel_id == youtube_channel_id
            ),
            None,
        )

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        raise NotImplementedError

    async def update_uploads_playlist_id(
        self,
        channel_id: int,
        uploads_playlist_id: str,
    ) -> ChannelRecord | None:
        raise NotImplementedError

    async def delete_channel(self, channel_id: int) -> bool:
        raise NotImplementedError


class FakeStreamerRepository(StreamerRepositoryPort):
    def __init__(self) -> None:
        self.streamers: dict[int, StreamerRecord] = {
            1: StreamerRecord(id=1, name="Choseungdal")
        }

    async def create_streamer(self, *, name: str) -> StreamerRecord:
        raise NotImplementedError

    async def list_streamers(self) -> list[StreamerRecord]:
        return list(self.streamers.values())

    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        return self.streamers.get(streamer_id)

    async def update_streamer(
        self,
        streamer_id: int,
        *,
        name: str,
    ) -> StreamerRecord | None:
        raise NotImplementedError

    async def delete_streamer(self, streamer_id: int) -> bool:
        raise NotImplementedError


class FakeDomainKnowledgeRepository(DomainKnowledgeRepositoryPort):
    def __init__(self) -> None:
        self.prompt_entries: list[DomainKnowledgePromptEntryRecord] = []

    async def list_types(self) -> list[DomainEntryTypeRecord]:
        raise NotImplementedError

    async def create_type(self, create: DomainEntryTypeCreate) -> DomainEntryTypeRecord:
        raise NotImplementedError

    async def get_or_create_type(
        self,
        create: DomainEntryTypeCreate,
    ) -> DomainEntryTypeRecord:
        raise NotImplementedError

    async def get_type(self, type_id: int) -> DomainEntryTypeRecord | None:
        raise NotImplementedError

    async def list_entries(
        self,
        query: DomainEntryListQuery,
    ) -> list[DomainEntryRecord]:
        raise NotImplementedError

    async def get_entry(self, entry_id: int) -> DomainEntryRecord | None:
        raise NotImplementedError

    async def create_entry(self, create: DomainEntryCreate) -> DomainEntryRecord:
        raise NotImplementedError

    async def update_entry(
        self,
        entry_id: int,
        update: DomainEntryUpdate,
    ) -> DomainEntryRecord | None:
        raise NotImplementedError

    async def archive_entry(self, entry_id: int) -> DomainEntryRecord | None:
        raise NotImplementedError

    async def add_streamer_link(
        self,
        entry_id: int,
        link: DomainEntryStreamerLinkCreate,
    ) -> DomainEntryRecord | None:
        raise NotImplementedError

    async def remove_streamer_link(self, entry_id: int, streamer_id: int) -> bool:
        raise NotImplementedError

    async def add_alias(
        self,
        entry_id: int,
        alias: DomainEntryAliasCreate,
    ) -> DomainEntryRecord | None:
        raise NotImplementedError

    async def update_alias(
        self,
        alias_id: int,
        update: DomainEntryAliasUpdate,
    ) -> DomainEntryAliasRecord | None:
        raise NotImplementedError

    async def delete_alias(self, alias_id: int) -> bool:
        raise NotImplementedError

    async def list_prompt_entries_for_streamer(
        self,
        streamer_id: int | None,
    ) -> list[DomainKnowledgePromptEntryRecord]:
        return self.prompt_entries


class FakeMicroEventExtractionRepository(MicroEventExtractionRepositoryPort):
    def __init__(
        self,
        videos: FakeVideoRepository,
        video_tasks: FakeVideoTaskRepository,
    ) -> None:
        self.videos = videos
        self.video_tasks = video_tasks
        self.windows_by_task: dict[int, list[MicroEventExtractionWindowRecord]] = {}
        self.next_window_id = 1
        self.next_micro_event_id = 1
        self.next_excluded_range_id = 1
        self.next_asr_id = 1
        self.upserted_window_indices: list[int] = []

    async def delete_extraction(self, video_task_id: int) -> None:
        self.windows_by_task.pop(video_task_id, None)

    async def replace_extraction(
        self,
        video_task_id: int,
        windows: list[MicroEventExtractionWindowCreate],
    ) -> MicroEventExtractionDetailRecord | None:
        records = [self._record_from_window(window) for window in windows]
        self.windows_by_task[video_task_id] = records
        first = windows[0] if windows else None
        if first is None:
            return None
        return await self.get_extraction(video_id=first.video_id, video_task_id=video_task_id)

    async def upsert_window(
        self,
        video_task_id: int,
        window: MicroEventExtractionWindowCreate,
    ) -> MicroEventExtractionWindowRecord:
        self.upserted_window_indices.append(window.window_index)
        record = self._record_from_window(window)
        records = [
            existing
            for existing in self.windows_by_task.get(video_task_id, [])
            if existing.window_index != window.window_index
        ]
        records.append(record)
        records.sort(key=lambda item: item.window_index)
        self.windows_by_task[video_task_id] = records
        return record

    async def get_extraction(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> MicroEventExtractionDetailRecord | None:
        task = self.video_tasks.tasks.get(video_task_id)
        video = self.videos.videos.get(video_id)
        if task is None or video is None or task.video_id != video_id:
            return None
        return MicroEventExtractionDetailRecord(
            video_task_id=task.id,
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
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
        self,
        *,
        video_id: int,
    ) -> MicroEventExtractionDetailRecord | None:
        succeeded = [
            task
            for task in self.video_tasks.tasks.values()
            if task.video_id == video_id
            and task.task_name == "micro_event_extract"
            and task.status == "succeeded"
        ]
        task = max(succeeded, key=lambda item: item.id, default=None)
        if task is None:
            return None
        return await self.get_extraction(video_id=video_id, video_task_id=task.id)

    async def update_candidate_event(
        self,
        *,
        video_task_id: int,
        candidate_id: int,
        event: str,
    ) -> MicroEventCandidateRecord | None:
        windows = self.windows_by_task.get(video_task_id, [])
        for window_index, window in enumerate(windows):
            for candidate_index, candidate in enumerate(window.micro_events):
                if candidate.id != candidate_id:
                    continue
                updated_candidate = replace(candidate, event=event, updated_at=NOW)
                updated_micro_events = list(window.micro_events)
                updated_micro_events[candidate_index] = updated_candidate
                windows[window_index] = replace(
                    window,
                    micro_events=updated_micro_events,
                    updated_at=NOW,
                )
                return updated_candidate
        return None

    def _record_from_window(
        self,
        window: MicroEventExtractionWindowCreate,
    ) -> MicroEventExtractionWindowRecord:
        window_id = self.next_window_id
        micro_events: list[MicroEventCandidateRecord] = []
        for candidate in window.micro_events:
            micro_events.append(
                MicroEventCandidateRecord(
                    id=self.next_micro_event_id,
                    window_id=window_id,
                    video_task_id=window.video_task_id,
                    transcript_id=window.transcript_id,
                    candidate_index=candidate.candidate_index,
                    activity=candidate.activity,
                    event=candidate.event,
                    start_cue_id=candidate.start_cue_id,
                    end_cue_id=candidate.end_cue_id,
                    evidence_cue_ids=candidate.evidence_cue_ids,
                    boundary_before=candidate.boundary_before,
                    boundary_after=candidate.boundary_after,
                    confidence=candidate.confidence,
                    program_mode=candidate.program_mode,
                    content_kind=candidate.content_kind,
                    topics=candidate.topics,
                    relation_to_previous=candidate.relation_to_previous,
                    continues_to_next=candidate.continues_to_next,
                    support_level=candidate.support_level,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            self.next_micro_event_id += 1
        excluded_ranges: list[MicroEventExcludedRangeRecord] = []
        for excluded_range in window.excluded_ranges:
            excluded_ranges.append(
                MicroEventExcludedRangeRecord(
                    id=self.next_excluded_range_id,
                    window_id=window_id,
                    video_task_id=window.video_task_id,
                    transcript_id=window.transcript_id,
                    range_index=excluded_range.range_index,
                    start_cue_id=excluded_range.start_cue_id,
                    end_cue_id=excluded_range.end_cue_id,
                    reason=excluded_range.reason,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            self.next_excluded_range_id += 1
        asr_candidates: list[AsrCorrectionCandidateRecord] = []
        for candidate in window.asr_correction_candidates:
            asr_candidates.append(
                AsrCorrectionCandidateRecord(
                    id=self.next_asr_id,
                    window_id=window_id,
                    video_task_id=window.video_task_id,
                    transcript_id=window.transcript_id,
                    candidate_index=candidate.candidate_index,
                    original=candidate.original,
                    suggested=candidate.suggested,
                    correction_type=candidate.correction_type,
                    apply_scope=candidate.apply_scope,
                    confidence=candidate.confidence,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            self.next_asr_id += 1
        record = MicroEventExtractionWindowRecord(
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
            micro_events=micro_events,
            excluded_ranges=excluded_ranges,
            asr_correction_candidates=asr_candidates,
        )
        self.next_window_id += 1
        return record


class FakeMicroEventExtractor(MicroEventExtractorPort):
    def __init__(self) -> None:
        self.responses: list[str] = []
        self.responses_by_window: dict[int, str] = {}
        self.repair_responses: list[str] = []
        self.repair_failures_by_window: dict[int, Exception] = {}
        self.delays_by_window: dict[int, float] = {}
        self.failures_by_window: dict[int, Exception | list[Exception]] = {}
        self.prompts: list[str] = []
        self.repair_prompts: list[str] = []
        self.requests: list[MicroEventExtractionRequest] = []
        self.repair_requests: list[MicroEventRepairRequest] = []
        self.active_count = 0
        self.max_active_count = 0
        self.started_window_indices: list[int | None] = []
        self.completed_window_indices: list[int | None] = []

    async def extract_window(
        self,
        request: MicroEventExtractionRequest,
    ) -> MicroEventExtractionResult:
        self.requests.append(request)
        self.prompts.append(request.prompt)
        self.started_window_indices.append(request.window_index)
        self.active_count += 1
        self.max_active_count = max(self.max_active_count, self.active_count)
        try:
            if request.window_index in self.delays_by_window:
                await asyncio.sleep(self.delays_by_window[request.window_index])
            window_index = request.window_index
            failure = (
                self.failures_by_window.get(window_index)
                if window_index is not None
                else None
            )
            if isinstance(failure, list):
                if failure:
                    raise failure.pop(0)
            elif failure is not None:
                raise failure
            response = (
                self.responses_by_window[request.window_index]
                if request.window_index in self.responses_by_window
                else self.responses.pop(0)
                if self.responses
                else _extractor_json()
            )
            self.completed_window_indices.append(request.window_index)
            return MicroEventExtractionResult(
                thread_id=f"thread-{request.window_index}",
                turn_id=f"turn-{request.window_index}",
                status="completed",
                final_response=response,
            )
        finally:
            self.active_count -= 1

    async def repair_window(
        self,
        request: MicroEventRepairRequest,
    ) -> MicroEventExtractionResult:
        self.repair_requests.append(request)
        self.repair_prompts.append(request.prompt)
        if request.window_index in self.repair_failures_by_window:
            raise self.repair_failures_by_window[request.window_index]
        response = self.repair_responses.pop(0) if self.repair_responses else _extractor_json()
        return MicroEventExtractionResult(
            thread_id=f"repair-thread-{request.window_index}",
            turn_id=f"repair-turn-{request.window_index}",
            status="completed",
            final_response=response,
        )


class FakeOperationEventRecorder(OperationEventRecorderPort):
    def __init__(self) -> None:
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.events.append(event)


class FakePromptResolver:
    def __init__(self) -> None:
        self.prompts: dict[PromptKey, ResolvedPrompt] = {
            MICRO_EVENT_EXTRACT_PROMPT_KEY: fallback_prompt(
                MICRO_EVENT_EXTRACT_PROMPT_KEY
            )
        }
        self.version_prompts: dict[tuple[PromptKey, int], ResolvedPrompt] = {}
        self.request_failures: dict[tuple[PromptKey, int], Exception] = {}

    async def resolve_prompt(self, prompt_key: PromptKey) -> ResolvedPrompt:
        return self.prompts[prompt_key]

    async def resolve_prompt_for_request(
        self,
        prompt_key: PromptKey,
        version_id: int | None,
    ) -> ResolvedPrompt:
        if version_id is None:
            return await self.resolve_prompt(prompt_key)
        failure = self.request_failures.get((prompt_key, version_id))
        if failure is not None:
            raise failure
        return self.version_prompts[(prompt_key, version_id)]

    async def resolve_prompt_version(
        self,
        prompt_key: PromptKey,
        version_id: int | None,
    ) -> ResolvedPrompt:
        if version_id is None:
            return fallback_prompt(prompt_key)
        return self.version_prompts[(prompt_key, version_id)]


class _Fakes:
    def __init__(self) -> None:
        self.videos = FakeVideoRepository()
        self.video_tasks = FakeVideoTaskRepository(self.videos)
        self.pipeline_jobs = FakePipelineJobRepository()
        self.transcripts = FakeTranscriptRepository()
        self.cues = FakeTranscriptCueRepository()
        self.channels = FakeChannelRepository()
        self.streamers = FakeStreamerRepository()
        self.domain_knowledge = FakeDomainKnowledgeRepository()
        self.micro_events = FakeMicroEventExtractionRepository(
            self.videos,
            self.video_tasks,
        )
        self.extractor = FakeMicroEventExtractor()
        self.events = FakeOperationEventRecorder()
        self.llm_traces: LlmTraceRecorderPort = NoopLlmTraceRecorder()
        self.prompt_resolver = FakePromptResolver()
        self.settings = CliSettings(
            micro_event_extract_timeout_seconds=60,
            micro_event_window_concurrency_limit=1,
            model="gpt-5.4",
            reasoning_effort="high",
        )


def test_micro_event_extract_succeeds_and_detail_can_be_read() -> None:
    fakes = _seed_ready_fakes()

    response = asyncio.run(_extract(fakes))
    latest = asyncio.run(_get_latest(fakes))

    assert response["status"] == "succeeded"
    assert response["reason"] == "extracted"
    assert response["model"] == "gpt-5.4"
    assert response["reasoningEffort"] == "high"
    assert response["windowCount"] == 1
    assert response["microEventCount"] == 1
    assert response["asrCorrectionCandidateCount"] == 1
    assert latest["videoTaskId"] == response["videoTaskId"]
    assert latest["model"] == "gpt-5.4"
    assert latest["reasoningEffort"] == "high"
    assert latest["windows"][0]["rawResponseText"]
    assert latest["windows"][0]["microEvents"][0]["programMode"] == "JUST_CHATTING"
    assert latest["windows"][0]["microEvents"][0]["contentKind"] == "META_CHAT"
    assert latest["windows"][0]["excludedRanges"] == []
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert fakes.video_tasks.tasks[2].status == "succeeded"


def test_micro_event_extract_passes_codex_usage_context_per_window() -> None:
    fakes = _seed_ready_fakes()

    response = asyncio.run(_extract(fakes))

    request = fakes.extractor.requests[0]
    assert request.video_id == 1
    assert request.video_task_id == response["videoTaskId"]
    assert request.job_id == response["jobId"]
    assert request.job_attempt_id == response["jobAttemptId"]
    assert request.transcript_id == response["transcriptId"]
    assert request.window_index == 1
    assert request.model == "gpt-5.4"
    assert request.reasoning_effort == "high"


def test_micro_event_extract_accepts_requested_model_and_reasoning_effort() -> None:
    fakes = _seed_ready_fakes()

    response = asyncio.run(
        _extract(
            fakes,
            json={
                "model": "gpt-5.4-mini",
                "reasoningEffort": "xhigh",
            },
        )
    )
    latest = asyncio.run(_get_latest(fakes))

    assert response["status"] == "succeeded"
    assert response["model"] == "gpt-5.4-mini"
    assert response["reasoningEffort"] == "xhigh"
    assert latest["model"] == "gpt-5.4-mini"
    assert latest["reasoningEffort"] == "xhigh"
    assert fakes.pipeline_jobs.jobs[1].input_json["model"] == "gpt-5.4-mini"
    assert fakes.pipeline_jobs.jobs[1].input_json["reasoningEffort"] == "xhigh"
    assert fakes.pipeline_jobs.attempts[1].output_json is not None
    assert fakes.pipeline_jobs.attempts[1].output_json["model"] == "gpt-5.4-mini"
    assert fakes.pipeline_jobs.attempts[1].output_json["reasoningEffort"] == "xhigh"
    assert fakes.video_tasks.tasks[2].output_json is not None
    assert fakes.video_tasks.tasks[2].output_json["model"] == "gpt-5.4-mini"
    assert fakes.video_tasks.tasks[2].output_json["reasoningEffort"] == "xhigh"
    assert fakes.extractor.requests[0].model == "gpt-5.4-mini"
    assert fakes.extractor.requests[0].reasoning_effort == "xhigh"


def test_micro_event_extract_prompt_uses_public_fallback_and_records_version() -> None:
    fakes = _seed_ready_fakes()

    asyncio.run(_extract(fakes))

    prompt = fakes.extractor.prompts[0]
    assert "공개 저장소용 샘플 fallback" in prompt
    assert "반드시 JSON object만 출력한다" in prompt
    assert "CONTEXT_BEFORE" in prompt
    assert "OWNED_START_CUE_ID: tr1-c000001" in prompt
    resolved_prompt = fallback_prompt(MICRO_EVENT_EXTRACT_PROMPT_KEY)
    assert fakes.pipeline_jobs.jobs[1].input_json["promptVersionId"] is None
    assert fakes.pipeline_jobs.jobs[1].input_json["promptVersion"] == (
        resolved_prompt.version_label
    )
    assert fakes.pipeline_jobs.jobs[1].input_json["promptSha256"] == (
        resolved_prompt.body_sha256
    )
    assert fakes.pipeline_jobs.jobs[1].input_json["promptSource"] == "fallback"
    assert len(str(fakes.pipeline_jobs.jobs[1].input_json["promptSha256"])) == 64


def test_micro_event_extract_uses_requested_prompt_version() -> None:
    fakes = _seed_ready_fakes()
    prompt = _db_prompt(
        version_id=101,
        version_label="db-v1",
        body="REQUESTED MICRO PROMPT\n",
        sha="a" * 64,
    )
    fakes.prompt_resolver.version_prompts[(MICRO_EVENT_EXTRACT_PROMPT_KEY, 101)] = (
        prompt
    )

    asyncio.run(_extract(fakes, json={"promptVersionId": 101}))

    input_json = fakes.pipeline_jobs.jobs[1].input_json
    assert fakes.extractor.prompts[0].startswith("REQUESTED MICRO PROMPT\n")
    assert input_json["promptVersionId"] == 101
    assert input_json["promptVersion"] == "db-v1"
    assert input_json["promptSha256"] == "a" * 64
    assert input_json["promptSource"] == "database"


def test_micro_event_prompt_version_changes_input_hash() -> None:
    first_hash = _extract_input_hash_for_prompt_version(version_id=101, sha="a" * 64)
    second_hash = _extract_input_hash_for_prompt_version(version_id=102, sha="b" * 64)

    assert first_hash != second_hash


def test_micro_event_extract_rejects_unknown_prompt_version() -> None:
    fakes = _seed_ready_fakes()
    fakes.prompt_resolver.request_failures[(MICRO_EVENT_EXTRACT_PROMPT_KEY, 404)] = (
        PromptNotFound("Prompt version not found.")
    )

    response = asyncio.run(
        _extract(fakes, json={"promptVersionId": 404}, expected_status=404)
    )

    assert response["detail"] == "Prompt version not found."


def test_micro_event_extract_rejects_unpublished_prompt_version() -> None:
    fakes = _seed_ready_fakes()
    fakes.prompt_resolver.request_failures[(MICRO_EVENT_EXTRACT_PROMPT_KEY, 105)] = (
        PromptConflict("Only published prompt versions can be selected.")
    )

    response = asyncio.run(
        _extract(fakes, json={"promptVersionId": 105}, expected_status=409)
    )

    assert response["detail"] == "Only published prompt versions can be selected."


def test_micro_event_extract_prompt_includes_semantic_video_context() -> None:
    fakes = _seed_ready_fakes()

    asyncio.run(_extract(fakes))

    prompt = fakes.extractor.prompts[0]
    metadata = _prompt_metadata(prompt)

    assert metadata == {
        "videoTitle": "Live VOD 1",
        "videoDescription": "Description",
        "publishedAt": NOW.isoformat(),
        "streamerName": "Choseungdal",
        "transcriptLanguage": "Korean",
        "transcriptLanguageCode": "ko",
        "transcriptSource": "generated",
        "windowIndex": 1,
    }
    assert "videoId" not in metadata
    assert "youtubeVideoId" not in metadata
    assert "transcriptId" not in metadata
    assert "promptVersion" not in metadata


def test_micro_event_extract_prompt_includes_cue_timing_gaps() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[0, 15_000, 24_000])
    fakes.extractor.responses_by_window = {
        1: _extractor_json("tr1-c000001", "tr1-c000003")
    }

    asyncio.run(_extract(fakes))

    prompt = fakes.extractor.prompts[0]
    cue_rows = _prompt_cue_rows(prompt)

    assert cue_rows == [
        {
            "cue_id": "tr1-c000001",
            "text": "cue 1",
            "start_ms": 0,
            "end_ms": 10_000,
            "duration_ms": 10_000,
            "gap_from_previous_ms": None,
            "gap_to_next_ms": 5_000,
        },
        {
            "cue_id": "tr1-c000002",
            "text": "cue 2",
            "start_ms": 15_000,
            "end_ms": 25_000,
            "duration_ms": 10_000,
            "gap_from_previous_ms": 5_000,
            "gap_to_next_ms": 0,
        },
        {
            "cue_id": "tr1-c000003",
            "text": "cue 3",
            "start_ms": 24_000,
            "end_ms": 34_000,
            "duration_ms": 10_000,
            "gap_from_previous_ms": 0,
            "gap_to_next_ms": None,
        },
    ]


def test_micro_event_extract_injects_matching_domain_knowledge_terms() -> None:
    fakes = _seed_ready_fakes()
    fakes.domain_knowledge.prompt_entries = [
        DomainKnowledgePromptEntryRecord(
            entry_id=1,
            type_key="person",
            type_label="Person",
            canonical_name="Known Person",
            display_name=None,
            disambiguation=None,
            detail="Known person detail",
            prompt_policy="AUTO_ON_MATCH",
            priority=50,
            aliases=[
                DomainKnowledgePromptAliasRecord(
                    surface_form="cue 1",
                    alias_kind="ASR_ERROR",
                    certainty="HIGH",
                    apply_scope="SEARCH_AND_SUMMARY",
                    language_code=None,
                    note=None,
                )
            ],
        ),
        DomainKnowledgePromptEntryRecord(
            entry_id=2,
            type_key="term",
            type_label="Term",
            canonical_name="Always Term",
            display_name=None,
            disambiguation=None,
            detail="Always scoped detail",
            prompt_policy="ALWAYS_FOR_SCOPED_STREAMER",
            priority=80,
            aliases=[],
        ),
        DomainKnowledgePromptEntryRecord(
            entry_id=3,
            type_key="term",
            type_label="Term",
            canonical_name="Missing Term",
            display_name=None,
            disambiguation=None,
            detail="This should not be injected",
            prompt_policy="AUTO_ON_MATCH",
            priority=90,
            aliases=[],
        ),
    ]

    asyncio.run(_extract(fakes))

    prompt = fakes.extractor.prompts[0]
    assert '"canonicalForm": "Known Person"' in prompt
    assert '"detail": "Known person detail"' in prompt
    assert '"relation": "ASR_ERROR"' in prompt
    assert '"canonicalForm": "Always Term"' in prompt
    assert "Missing Term" not in prompt
    assert fakes.pipeline_jobs.jobs[1].input_json["domainKnowledgeEntryCount"] == 3
    assert "domainKnowledgeFingerprint" in fakes.pipeline_jobs.jobs[1].input_json


def test_micro_event_extract_missing_video_returns_not_found() -> None:
    response = asyncio.run(_extract(_Fakes(), expected_status=404))

    assert response == {"detail": "Video not found."}


def test_micro_event_extract_uses_stored_cues_without_cue_task() -> None:
    fakes = _Fakes()
    _seed_video(fakes)
    _seed_transcript(fakes)
    _seed_cues(fakes)

    response = asyncio.run(_extract(fakes))

    assert response["status"] == "succeeded"
    assert response["transcriptId"] == 1
    assert fakes.pipeline_jobs.jobs[1].input_json["videoId"] == 1


def test_micro_event_extract_requires_stored_cues() -> None:
    fakes = _Fakes()
    _seed_video(fakes)
    _seed_transcript(fakes)

    response = asyncio.run(_extract(fakes, expected_status=409))

    assert response == {"detail": "Transcript cues are required."}
    assert not fakes.pipeline_jobs.jobs


def test_micro_event_extract_skips_succeeded_until_regenerate_requested() -> None:
    fakes = _seed_ready_fakes()

    first = asyncio.run(_extract(fakes))
    skipped = asyncio.run(_extract(fakes))
    regenerated = asyncio.run(_extract(fakes, json={"regenerateSucceeded": True}))

    assert first["status"] == "succeeded"
    assert skipped["reason"] == "already_succeeded"
    assert regenerated["reason"] == "extracted"
    assert len(fakes.extractor.prompts) == 2


def test_micro_event_batch_extract_processes_next_eligible_video_after_succeeded() -> None:
    fakes = _seed_ready_fakes()
    first = asyncio.run(_extract(fakes))
    _seed_ready_video(
        fakes,
        video_id=2,
        transcript_id=2,
        cue_task_id=3,
        youtube_video_id="video2DEF456",
        published_at=NOW - timedelta(minutes=1),
    )
    fakes.extractor.responses = [_extractor_json("tr2-c000001", "tr2-c000002")]

    response = asyncio.run(_extract_all(fakes, json={"limit": 1}))

    assert first["status"] == "succeeded"
    assert response["requestedCount"] == 1
    assert response["processedCount"] == 1
    assert response["succeededCount"] == 1
    assert response["scannedCount"] == 2
    assert response["alreadySatisfiedCount"] == 1
    assert response["items"][0]["videoId"] == 2
    assert response["items"][0]["reason"] == "extracted"
    assert len(fakes.extractor.prompts) == 2


def test_micro_event_batch_extract_retries_failed_only_when_requested() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = ["not json"]
    failed = asyncio.run(_extract(fakes))

    skipped = asyncio.run(_extract_all(fakes, json={"limit": 1}))
    fakes.extractor.responses = [_extractor_json()]
    retried = asyncio.run(_extract_all(fakes, json={"limit": 1, "retryFailed": True}))

    assert failed["status"] == "failed"
    assert skipped["processedCount"] == 0
    assert skipped["ineligibleCount"] == 1
    assert retried["processedCount"] == 1
    assert retried["succeededCount"] == 1
    assert retried["items"][0]["reason"] == "extracted"


def test_micro_event_batch_extract_regenerates_succeeded_when_requested() -> None:
    fakes = _seed_ready_fakes()
    asyncio.run(_extract(fakes))

    skipped = asyncio.run(_extract_all(fakes, json={"limit": 1}))
    regenerated = asyncio.run(
        _extract_all(fakes, json={"limit": 1, "regenerateSucceeded": True})
    )

    assert skipped["processedCount"] == 0
    assert skipped["alreadySatisfiedCount"] == 1
    assert regenerated["processedCount"] == 1
    assert regenerated["items"][0]["reason"] == "extracted"
    assert len(fakes.extractor.prompts) == 2


def test_micro_event_enqueue_selected_video_creates_pending_task() -> None:
    fakes = _seed_ready_fakes()

    response = asyncio.run(
        _enqueue(
            fakes,
            json={
                "target": "selected_videos",
                "videoIds": [1],
                "model": "gpt-5.4-mini",
                "reasoningEffort": "xhigh",
            },
        )
    )

    task = fakes.video_tasks.tasks[2]
    assert response["requestedCount"] == 1
    assert response["enqueuedCount"] == 1
    assert response["items"][0]["status"] == "pending"
    assert response["items"][0]["reason"] == "enqueued"
    assert task.status == "pending"
    assert task.input_json is not None
    assert task.input_json["model"] == "gpt-5.4-mini"
    assert task.input_json["reasoningEffort"] == "xhigh"
    assert fakes.extractor.prompts == []


def test_micro_event_enqueue_retries_canceled_only_when_requested() -> None:
    fakes = _seed_ready_fakes()
    first = asyncio.run(
        _enqueue(fakes, json={"target": "selected_videos", "videoIds": [1]})
    )
    task_id = first["items"][0]["videoTaskId"]
    asyncio.run(
        fakes.video_tasks.cancel_pending_tasks(
            [task_id],
            error_type="ManualQueueCancel",
            error_message="Canceled by operator.",
        )
    )

    skipped = asyncio.run(
        _enqueue(fakes, json={"target": "selected_videos", "videoIds": [1]})
    )
    retried = asyncio.run(
        _enqueue(
            fakes,
            json={
                "target": "selected_videos",
                "videoIds": [1],
                "retryFailed": True,
            },
        )
    )

    task = fakes.video_tasks.tasks[task_id]
    assert skipped["ineligibleCount"] == 1
    assert skipped["items"][0]["reason"] == "not_retryable"
    assert retried["enqueuedCount"] == 1
    assert retried["items"][0]["status"] == "pending"
    assert retried["items"][0]["reason"] == "requeued"
    assert task.status == "pending"
    assert task.error_type is None
    assert task.error_message is None
    assert task.completed_at is None


def test_micro_event_enqueue_current_filters_skips_succeeded_and_finds_next() -> None:
    fakes = _seed_ready_fakes()
    asyncio.run(_extract(fakes))
    _seed_ready_video(
        fakes,
        video_id=2,
        transcript_id=2,
        cue_task_id=3,
        youtube_video_id="video2DEF456",
        published_at=NOW - timedelta(minutes=1),
    )

    response = asyncio.run(
        _enqueue(
            fakes,
            json={
                "target": "current_filters",
                "search": "Live VOD",
                "limit": 1,
            },
        )
    )

    assert response["scannedCount"] == 2
    assert response["alreadySucceededCount"] == 1
    assert response["enqueuedCount"] == 1
    assert response["items"][0]["reason"] == "already_succeeded"
    assert response["items"][1]["videoId"] == 2
    assert response["items"][1]["reason"] == "enqueued"


def test_claimed_micro_event_task_executes_through_worker_path() -> None:
    fakes = _seed_ready_fakes()
    asyncio.run(
        _enqueue(fakes, json={"target": "selected_videos", "videoIds": [1]})
    )

    claimed = asyncio.run(
        fakes.video_tasks.claim_next_pending_task(
            task_name="micro_event_extract",
            worker_id="micro-event-worker:test",
        )
    )
    assert claimed is not None
    result = asyncio.run(
        _use_case(fakes).execute_claimed_task(
            claimed,
            worker_id="micro-event-worker:test",
        )
    )

    assert result.status == "succeeded"
    assert fakes.video_tasks.tasks[2].status == "succeeded"
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert fakes.pipeline_jobs.attempts[1].worker_id == "micro-event-worker:test"


def test_claimed_micro_event_task_uses_queued_prompt_version() -> None:
    fakes = _seed_ready_fakes()
    queued_prompt = ResolvedPrompt(
        key=MICRO_EVENT_EXTRACT_PROMPT_KEY,
        version_id=101,
        version_label="db-v1",
        body="QUEUED PROMPT HEADER\n",
        body_sha256="a" * 64,
        source="database",
    )
    active_prompt = ResolvedPrompt(
        key=MICRO_EVENT_EXTRACT_PROMPT_KEY,
        version_id=102,
        version_label="db-v2",
        body="ACTIVE PROMPT HEADER\n",
        body_sha256="b" * 64,
        source="database",
    )
    fakes.prompt_resolver.prompts[MICRO_EVENT_EXTRACT_PROMPT_KEY] = queued_prompt
    fakes.prompt_resolver.version_prompts[
        (MICRO_EVENT_EXTRACT_PROMPT_KEY, 101)
    ] = queued_prompt
    asyncio.run(
        _enqueue(fakes, json={"target": "selected_videos", "videoIds": [1]})
    )
    fakes.prompt_resolver.prompts[MICRO_EVENT_EXTRACT_PROMPT_KEY] = active_prompt

    claimed = asyncio.run(
        fakes.video_tasks.claim_next_pending_task(
            task_name="micro_event_extract",
            worker_id="micro-event-worker:test",
        )
    )
    assert claimed is not None
    result = asyncio.run(
        _use_case(fakes).execute_claimed_task(
            claimed,
            worker_id="micro-event-worker:test",
        )
    )

    assert result.status == "succeeded"
    assert fakes.extractor.prompts[0].startswith("QUEUED PROMPT HEADER\n")
    assert not fakes.extractor.prompts[0].startswith("ACTIVE PROMPT HEADER\n")
    assert fakes.pipeline_jobs.jobs[1].input_json["promptVersionId"] == 101
    assert fakes.pipeline_jobs.jobs[1].input_json["promptVersion"] == "db-v1"
    assert fakes.pipeline_jobs.jobs[1].input_json["promptSource"] == "database"


def test_micro_event_extract_records_invalid_json_as_failed_task() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = ["not json"]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "failed"
    assert response["errorType"] == "MicroEventExtractionOutputInvalid"
    assert fakes.pipeline_jobs.jobs[1].status == "failed"
    assert fakes.video_tasks.tasks[2].status == "failed"
    assert detail["windows"][0]["status"] == "failed"
    assert detail["windows"][0]["validationError"] == "Extractor returned invalid JSON."
    assert fakes.extractor.repair_requests == []


def test_micro_event_trace_records_invalid_json_response(tmp_path: Path) -> None:
    fakes = _seed_ready_fakes()
    fakes.llm_traces = FileLlmTraceRecorder(
        base_dir=tmp_path,
        clock=lambda: datetime(2026, 6, 29, 12, tzinfo=UTC),
    )
    fakes.extractor.responses = ["not json"]

    response = asyncio.run(_extract(fakes))
    events = _llm_trace_events(tmp_path, "micro_event_extract")

    assert response["status"] == "failed"
    phases = [event["phase"] for event in events]
    assert "window_started" in phases
    assert "llm_response_received" in phases
    assert "parse_failed" in phases
    response_event = next(
        event for event in events if event["phase"] == "llm_response_received"
    )
    assert response_event["windowIndex"] == 1
    assert response_event["windowCount"] == 1
    assert response_event["rawResponseLength"] == len(b"not json")
    assert Path(str(response_event["rawResponsePath"])).read_text(
        encoding="utf-8"
    ) == "not json"
    assert "rawResponseText" not in response_event
    assert "promptText" not in response_event


def test_micro_event_extract_repairs_out_of_range_cue_with_llm_repair() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[0, 1_000, 2_000])
    fakes.extractor.responses = [
        _extractor_json("tr1-c000001", "tr1-c000010")
    ]
    fakes.extractor.repair_responses = [
        _extractor_json("tr1-c000001", "tr1-c000003")
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert len(fakes.extractor.repair_requests) == 1
    repair_request = fakes.extractor.repair_requests[0]
    assert repair_request.validation_error == (
        "Extractor referenced cue_id outside OWNED_RANGE: tr1-c000010"
    )
    assert repair_request.owned_start_cue_id == "tr1-c000001"
    assert repair_request.owned_end_cue_id == "tr1-c000003"
    assert detail["windows"][0]["status"] == "succeeded"
    assert detail["windows"][0]["microEvents"][0]["endCueId"] == "tr1-c000003"
    assert "llm_repaired_window" in _warning_types(
        detail["windows"][0]["validationError"]
    )
    event_types = {event.event_type for event in fakes.events.events}
    assert "micro_event_extract.window_repair_requested" in event_types
    assert "micro_event_extract.window_repaired" in event_types


def test_micro_event_trace_records_window_repair_success(tmp_path: Path) -> None:
    fakes = _seed_ready_fakes()
    fakes.llm_traces = FileLlmTraceRecorder(
        base_dir=tmp_path,
        clock=lambda: datetime(2026, 6, 29, 12, tzinfo=UTC),
    )
    _seed_cues(fakes, cue_starts_ms=[0, 1_000, 2_000])
    fakes.extractor.responses = [
        _extractor_json("tr1-c000001", "tr1-c000010")
    ]
    fakes.extractor.repair_responses = [
        _extractor_json("tr1-c000001", "tr1-c000003")
    ]

    response = asyncio.run(_extract(fakes))
    events = _llm_trace_events(tmp_path, "micro_event_extract")

    assert response["status"] == "succeeded"
    phases = [event["phase"] for event in events]
    assert "repair_requested" in phases
    assert "repair_response_received" in phases
    assert "repair_succeeded" in phases
    repair_response = next(
        event for event in events if event["phase"] == "repair_response_received"
    )
    assert repair_response["operation"] == "repair_window"
    assert repair_response["repairIndex"] == 1
    assert Path(str(repair_response["rawResponsePath"])).exists()


def test_micro_event_extract_fails_when_llm_repair_output_is_invalid() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [_extractor_json("tr1-c000001", "tr1-c000001")]
    fakes.extractor.repair_responses = [
        _extractor_json("tr1-c000001", "tr1-c000001")
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "failed"
    assert len(fakes.extractor.repair_requests) == 1
    assert detail["windows"][0]["status"] == "failed"
    assert "cover every owned cue" in detail["windows"][0]["validationError"]
    event_types = {event.event_type for event in fakes.events.events}
    assert "micro_event_extract.window_repair_requested" in event_types
    assert "micro_event_extract.window_repair_failed" in event_types


def test_micro_event_extract_fails_when_llm_repair_raises() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [_extractor_json("tr1-c000001", "tr1-c000001")]
    fakes.extractor.repair_failures_by_window = {1: RuntimeError("repair unavailable")}

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "failed"
    assert len(fakes.extractor.repair_requests) == 1
    assert detail["windows"][0]["status"] == "failed"
    assert "cover every owned cue" in detail["windows"][0]["validationError"]
    repair_failed_events = [
        event
        for event in fakes.events.events
        if event.event_type == "micro_event_extract.window_repair_failed"
    ]
    assert len(repair_failed_events) == 1
    assert repair_failed_events[0].error_type == "RuntimeError"
    assert repair_failed_events[0].metadata_json["repairError"] == "repair unavailable"


def test_micro_event_extract_accepts_excluded_ranges_for_owned_coverage() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000001",
                        "event": "스트리머가 방송 주제를 설명한다.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["방송 주제"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000001"],
                        "support_level": "DIRECT",
                    }
                ],
                "excluded_ranges": [
                    {
                        "start_cue_id": "tr1-c000002",
                        "end_cue_id": "tr1-c000002",
                        "reason": "LOW_INFORMATION",
                    }
                ],
                "asr_correction_candidates": [],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    latest = asyncio.run(_get_latest(fakes))

    assert response["status"] == "succeeded"
    assert latest["windows"][0]["excludedRanges"][0]["reason"] == "LOW_INFORMATION"


def test_micro_event_extract_moves_excluded_range_shape_from_events() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000001",
                        "event": "스트리머가 방송 주제를 설명한다.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["방송 주제"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000001"],
                        "support_level": "DIRECT",
                    },
                    {
                        "start_cue_id": "tr1-c000002",
                        "end_cue_id": "tr1-c000002",
                        "reason": "MUSIC_ONLY",
                    },
                ],
                "excluded_ranges": [],
                "asr_correction_candidates": [],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert len(detail["windows"][0]["microEvents"]) == 1
    assert detail["windows"][0]["excludedRanges"][0]["startCueId"] == "tr1-c000002"
    assert detail["windows"][0]["excludedRanges"][0]["reason"] == "MUSIC_ONLY"
    assert "moved_event_to_excluded_range" in _warning_types(
        detail["windows"][0]["validationError"]
    )


def test_micro_event_extract_removes_stray_reason_from_valid_event() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000001",
                        "event": "스트리머가 방송 주제를 설명한다.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["방송 주제"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000001"],
                        "support_level": "DIRECT",
                        "reason": "MUSIC_ONLY",
                    }
                ],
                "excluded_ranges": [
                    {
                        "start_cue_id": "tr1-c000002",
                        "end_cue_id": "tr1-c000002",
                        "reason": "LOW_INFORMATION",
                    }
                ],
                "asr_correction_candidates": [],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert "removed_event_reason_field" in _warning_types(
        detail["windows"][0]["validationError"]
    )


def test_micro_event_extract_misplaced_excluded_range_still_fails_on_coverage_gap() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[0, 1_000, 2_000])
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000001",
                        "event": "스트리머가 방송 주제를 설명한다.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["방송 주제"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000001"],
                        "support_level": "DIRECT",
                    },
                    {
                        "start_cue_id": "tr1-c000003",
                        "end_cue_id": "tr1-c000003",
                        "reason": "MUSIC_ONLY",
                    },
                ],
                "excluded_ranges": [],
                "asr_correction_candidates": [],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "failed"
    assert detail["windows"][0]["status"] == "failed"
    assert "gap in OWNED_RANGE coverage" in detail["windows"][0]["validationError"]


def test_micro_event_extract_filters_event_evidence_outside_event_range() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000001",
                        "event": "스트리머가 방송 주제를 설명한다.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["방송 주제"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000001", "tr1-c000002"],
                        "support_level": "DIRECT",
                    }
                ],
                "excluded_ranges": [
                    {
                        "start_cue_id": "tr1-c000002",
                        "end_cue_id": "tr1-c000002",
                        "reason": "LOW_INFORMATION",
                    }
                ],
                "asr_correction_candidates": [],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert detail["windows"][0]["microEvents"][0]["evidenceCueIds"] == [
        "tr1-c000001"
    ]
    assert "removed_out_of_event_range_evidence_cue_ids" in _warning_types(
        detail["windows"][0]["validationError"]
    )


def test_micro_event_extract_normalizes_loose_enum_values() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000001",
                        "event": "스트리머가 방송 주제를 설명한다.",
                        "program_mode": "talk",
                        "content_kind": "clip_review",
                        "topics": ["방송 주제"],
                        "relation_to_previous": "follow_up",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000001"],
                        "support_level": "uncertain",
                    }
                ],
                "excluded_ranges": [
                    {
                        "start_cue_id": "tr1-c000002",
                        "end_cue_id": "tr1-c000002",
                        "reason": "no_speech",
                    }
                ],
                "asr_correction_candidates": [
                    {
                        "original": "대장님",
                        "suggested": "초승달",
                        "correction_type": "PERSON_NAME",
                        "apply_scope": "search",
                        "confidence": 0.8,
                    }
                ],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert detail["windows"][0]["microEvents"][0]["programMode"] == "JUST_CHATTING"
    assert detail["windows"][0]["microEvents"][0]["contentKind"] == "OTHER"
    assert detail["windows"][0]["microEvents"][0]["relationToPrevious"] == (
        "CONTINUATION"
    )
    assert detail["windows"][0]["microEvents"][0]["supportLevel"] == "AMBIGUOUS"
    assert detail["windows"][0]["excludedRanges"][0]["reason"] == "SILENCE_OR_GAP"
    assert detail["windows"][0]["asrCorrectionCandidates"][0]["correctionType"] == (
        "PROPER_NOUN"
    )
    assert detail["windows"][0]["asrCorrectionCandidates"][0]["applyScope"] == (
        "SEARCH_ONLY"
    )
    warning_types = _warning_types(detail["windows"][0]["validationError"])
    assert "normalized_enum" in warning_types


def test_micro_event_extract_moves_events_continued_to_events() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000001",
                        "event": "방송 주제를 설명한다.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["방송 주제"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": True,
                        "evidence_cue_ids": ["tr1-c000001"],
                        "support_level": "DIRECT",
                    }
                ],
                "events_continued": [
                    {
                        "start_cue_id": "tr1-c000002",
                        "end_cue_id": "tr1-c000002",
                        "event": "다음 단서로 설명을 이어간다.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["방송 주제"],
                        "relation_to_previous": "CONTINUATION",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000002"],
                        "support_level": "DIRECT",
                    }
                ],
                "excluded_ranges": [],
                "asr_correction_candidates": [],
                "notes": "unexpected top-level field",
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    window = detail["windows"][0]
    assert [event["event"] for event in window["microEvents"]] == [
        "방송 주제를 설명한다.",
        "다음 단서로 설명을 이어간다.",
    ]
    warning_types = _warning_types(window["validationError"])
    assert "moved_events_continued_to_events" in warning_types
    assert "ignored_unknown_top_level_field" in warning_types


def test_micro_event_extract_moves_term_annotations_to_asr_candidates() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000002",
                        "event": "Streamer explains a misunderstood term.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["term correction"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000001"],
                        "support_level": "DIRECT",
                    }
                ],
                "excluded_ranges": [],
                "asr_correction_candidates": [],
                "term_annotations": [
                    {
                        "term": "misheard word",
                        "canonical": "correct word",
                        "type": "ASR_ERROR",
                        "notes": "Model emitted the legacy annotation shape.",
                    },
                    {
                        "surface": "nickname",
                        "canonical": "canonical nickname",
                        "annotation_type": "WORDPLAY_OR_NICKNAME",
                    },
                ],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))
    window = detail["windows"][0]

    assert response["status"] == "succeeded"
    assert [
        {
            key: candidate[key]
            for key in (
                "candidateIndex",
                "original",
                "suggested",
                "correctionType",
                "applyScope",
                "confidence",
            )
        }
        for candidate in window["asrCorrectionCandidates"]
    ] == [
        {
            "candidateIndex": 1,
            "original": "misheard word",
            "suggested": "correct word",
            "correctionType": "UNCERTAIN",
            "applyScope": "SEARCH_ONLY",
            "confidence": 0.6,
        },
        {
            "candidateIndex": 2,
            "original": "nickname",
            "suggested": "canonical nickname",
            "correctionType": "STREAM_TERM",
            "applyScope": "SEARCH_AND_SUMMARY",
            "confidence": 0.6,
        },
    ]
    assert "moved_term_annotations_to_asr_correction_candidates" in _warning_types(
        window["validationError"]
    )


def test_micro_event_extract_truncates_too_many_topics() -> None:
    fakes = _seed_ready_fakes()
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000001",
                        "event": "?ㅽ듃由щ㉧媛 諛⑹넚 二쇱젣瑜??ㅻ챸?쒕떎.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": [
                            "topic-1",
                            "topic-2",
                            "topic-3",
                            "topic-4",
                            "topic-5",
                            "topic-6",
                            "topic-7",
                        ],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000001"],
                        "support_level": "DIRECT",
                    }
                ],
                "excluded_ranges": [
                    {
                        "start_cue_id": "tr1-c000002",
                        "end_cue_id": "tr1-c000002",
                        "reason": "LOW_INFORMATION",
                    }
                ],
                "asr_correction_candidates": [],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert detail["windows"][0]["microEvents"][0]["topics"] == [
        "topic-1",
        "topic-2",
        "topic-3",
        "topic-4",
        "topic-5",
        "topic-6",
    ]
    assert "truncated_topics" in _warning_types(
        detail["windows"][0]["validationError"]
    )


def test_micro_event_extract_truncates_too_many_event_evidence_ids() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[0, 1_000, 2_000, 3_000, 4_000, 5_000, 6_000])
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c000006",
                        "event": "스트리머가 게임 선택지를 차례로 확인한다.",
                        "program_mode": "GAMEPLAY",
                        "content_kind": "GAME_PROGRESS",
                        "topics": ["게임 선택지"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": [
                            "tr1-c000001",
                            "tr1-c000002",
                            "tr1-c000003",
                            "tr1-c000004",
                            "tr1-c000005",
                            "tr1-c000006",
                            "tr1-c000007",
                        ],
                        "support_level": "DIRECT",
                    },
                    {
                        "start_cue_id": "tr1-c000007",
                        "end_cue_id": "tr1-c000007",
                        "event": "스트리머가 다음 구간으로 넘어간다.",
                        "program_mode": "GAMEPLAY",
                        "content_kind": "GAME_PROGRESS",
                        "topics": ["다음 구간"],
                        "relation_to_previous": "CONTINUATION",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000007"],
                        "support_level": "DIRECT",
                    },
                ],
                "excluded_ranges": [],
                "asr_correction_candidates": [],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert detail["windows"][0]["status"] == "succeeded"
    assert detail["windows"][0]["microEvents"][0]["evidenceCueIds"] == [
        "tr1-c000001",
        "tr1-c000002",
        "tr1-c000003",
        "tr1-c000004",
        "tr1-c000005",
        "tr1-c000006",
    ]
    assert "truncated_evidence_cue_ids" in _warning_types(
        detail["windows"][0]["validationError"]
    )


def test_micro_event_extract_repairs_unique_nearby_cue_id_typo() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[0, 1_000, 2_000])
    fakes.extractor.responses = [
        json.dumps(
            {
                "events": [
                    {
                        "start_cue_id": "tr1-c000001",
                        "end_cue_id": "tr1-c00003",
                        "event": "스트리머가 방송 주제를 설명한다.",
                        "program_mode": "JUST_CHATTING",
                        "content_kind": "META_CHAT",
                        "topics": ["방송 주제"],
                        "relation_to_previous": "NEW_TOPIC",
                        "continues_to_next": False,
                        "evidence_cue_ids": ["tr1-c000001", "tr1-c00003"],
                        "support_level": "DIRECT",
                    }
                ],
                "excluded_ranges": [],
                "asr_correction_candidates": [
                    {
                        "original": "코덱쓰",
                        "suggested": "Codex",
                        "correction_type": "PROPER_NOUN",
                        "apply_scope": "SEARCH_ONLY",
                        "confidence": 0.8,
                    }
                ],
            },
            ensure_ascii=False,
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert detail["windows"][0]["microEvents"][0]["endCueId"] == "tr1-c000003"
    assert detail["windows"][0]["microEvents"][0]["evidenceCueIds"] == [
        "tr1-c000001",
        "tr1-c000003",
    ]
    assert "repaired_cue_id" in _warning_types(
        detail["windows"][0]["validationError"]
    )
    assert "evidenceCueIds" not in detail["windows"][0]["asrCorrectionCandidates"][0]


def test_micro_event_extract_repairs_evidence_cue_typo_within_event_range() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[index * 1_000 for index in range(200)])
    fakes.extractor.responses = [
        _extractor_json_for_ranges(
            event_ranges=[
                ("tr1-c000001", "tr1-c000046", ["tr1-c000001"]),
                ("tr1-c000047", "tr1-c000096", ["tr1-c00065"]),
                ("tr1-c000097", "tr1-c000200", ["tr1-c000097"]),
            ],
        )
    ]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert fakes.extractor.repair_requests == []
    assert detail["windows"][0]["microEvents"][1]["evidenceCueIds"] == [
        "tr1-c000065"
    ]
    assert "repaired_cue_id" in _warning_types(
        detail["windows"][0]["validationError"]
    )


def test_micro_event_extract_retries_when_repair_pads_large_low_information_range() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[index * 1_000 for index in range(400)])
    original_response = _extractor_json_for_ranges(
        event_ranges=[
            ("tr1-c000001", "tr1-c000280", ["tr1-c000001"]),
        ],
    )
    padded_repair_response = _extractor_json_for_ranges(
        event_ranges=[
            ("tr1-c000001", "tr1-c000280", ["tr1-c000001"]),
        ],
        excluded_ranges=[
            ("tr1-c000281", "tr1-c000400", "LOW_INFORMATION"),
        ],
    )
    valid_retry_response = _extractor_json_for_ranges(
        event_ranges=[
            ("tr1-c000001", "tr1-c000400", ["tr1-c000001"]),
        ],
    )
    fakes.extractor.responses = [original_response, valid_retry_response]
    fakes.extractor.repair_responses = [padded_repair_response]

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert len(fakes.extractor.requests) == 2
    assert len(fakes.extractor.repair_requests) == 1
    assert detail["windows"][0]["microEvents"][0]["endCueId"] == "tr1-c000400"
    repair_failed_events = [
        event
        for event in fakes.events.events
        if event.event_type == "micro_event_extract.window_repair_failed"
    ]
    assert len(repair_failed_events) == 1
    assert repair_failed_events[0].error_message == (
        "Repair added implausibly large LOW_INFORMATION coverage (120/400 owned cues)."
    )


def test_micro_event_extract_retries_implausibly_large_low_information_output() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[index * 1_000 for index in range(400)])
    anomalous_response = _extractor_json_for_ranges(
        event_ranges=[
            ("tr1-c000001", "tr1-c000150", ["tr1-c000001"]),
        ],
        excluded_ranges=[
            ("tr1-c000151", "tr1-c000400", "LOW_INFORMATION"),
        ],
    )
    valid_retry_response = _extractor_json_for_ranges(
        event_ranges=[
            ("tr1-c000001", "tr1-c000400", ["tr1-c000001"]),
        ],
    )
    fakes.extractor.responses = [anomalous_response, valid_retry_response]
    fakes.extractor.repair_responses = [anomalous_response]

    response = asyncio.run(_extract(fakes))

    assert response["status"] == "succeeded"
    assert len(fakes.extractor.requests) == 2
    assert len(fakes.extractor.repair_requests) == 1


def test_micro_event_extract_uses_thirty_minute_windows_with_five_minute_overlap() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[0, 31 * 60_000])
    fakes.extractor.responses = [
        _extractor_json("tr1-c000001", "tr1-c000001"),
        _extractor_json("tr1-c000002", "tr1-c000002"),
    ]

    response = asyncio.run(_extract(fakes))

    assert response["windowCount"] == 2
    assert len(fakes.extractor.prompts) == 2


def test_micro_event_extract_runs_windows_with_bounded_worker_pool() -> None:
    fakes = _seed_ready_fakes()
    fakes.settings = fakes.settings.model_copy(
        update={"micro_event_window_concurrency_limit": 3}
    )
    _seed_cues(
        fakes,
        cue_starts_ms=[0, 31 * 60_000, 62 * 60_000, 93 * 60_000],
    )
    fakes.extractor.delays_by_window = {
        1: 0.05,
        2: 0.01,
        3: 0.03,
        4: 0.01,
    }
    fakes.extractor.responses_by_window = {
        index: _extractor_json(f"tr1-c{index:06d}", f"tr1-c{index:06d}")
        for index in range(1, 5)
    }

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert response["windowCount"] == 4
    assert fakes.extractor.max_active_count == 3
    assert fakes.extractor.completed_window_indices != [1, 2, 3, 4]
    assert [window["windowIndex"] for window in detail["windows"]] == [1, 2, 3, 4]


def test_micro_event_extract_validation_failure_keeps_completed_parallel_windows() -> None:
    fakes = _seed_ready_fakes()
    fakes.settings = fakes.settings.model_copy(
        update={"micro_event_window_concurrency_limit": 3}
    )
    _seed_cues(
        fakes,
        cue_starts_ms=[0, 31 * 60_000, 62 * 60_000, 93 * 60_000],
    )
    fakes.extractor.delays_by_window = {1: 0.05, 3: 0.05, 4: 0.05}
    fakes.extractor.responses_by_window = {
        1: _extractor_json("tr1-c000001", "tr1-c000001"),
        2: "not json",
        3: _extractor_json("tr1-c000003", "tr1-c000003"),
        4: _extractor_json("tr1-c000004", "tr1-c000004"),
    }

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "failed"
    assert response["errorType"] == "MicroEventExtractionOutputInvalid"
    assert fakes.pipeline_jobs.jobs[1].status == "failed"
    assert fakes.video_tasks.tasks[2].status == "failed"
    assert [window["windowIndex"] for window in detail["windows"]] == [1, 2, 3, 4]
    failed_window = detail["windows"][1]
    assert failed_window["status"] == "failed"
    assert failed_window["validationError"] == "Extractor returned invalid JSON."


def test_micro_event_extract_runtime_failure_retries_failed_window_and_succeeds(
    tmp_path: Path,
) -> None:
    fakes = _seed_ready_fakes()
    fakes.llm_traces = FileLlmTraceRecorder(
        base_dir=tmp_path,
        clock=lambda: datetime(2026, 6, 29, 12, tzinfo=UTC),
    )
    fakes.settings = fakes.settings.model_copy(
        update={"micro_event_window_concurrency_limit": 3}
    )
    _seed_cues(fakes, cue_starts_ms=[0, 31 * 60_000, 62 * 60_000])
    fakes.extractor.delays_by_window = {1: 0.05, 3: 0.05}
    fakes.extractor.failures_by_window = {2: [RuntimeError("codex failed")]}
    fakes.extractor.responses_by_window = {
        1: _extractor_json("tr1-c000001", "tr1-c000001"),
        2: _extractor_json("tr1-c000002", "tr1-c000002"),
        3: _extractor_json("tr1-c000003", "tr1-c000003"),
    }

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "succeeded"
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert fakes.video_tasks.tasks[2].status == "succeeded"
    assert [window["windowIndex"] for window in detail["windows"]] == [1, 2, 3]
    assert fakes.extractor.started_window_indices.count(2) == 2
    assert 3 in fakes.extractor.completed_window_indices
    event_types = [event.event_type for event in fakes.events.events]
    assert "micro_event_extract.window_retry_requested" in event_types
    assert "micro_event_extract.window_retry_succeeded" in event_types
    phases = [event["phase"] for event in _llm_trace_events(tmp_path, "micro_event_extract")]
    assert "window_retry_scheduled" in phases
    assert "window_retry_started" in phases
    assert "window_retry_succeeded" in phases


def test_micro_event_extract_runtime_retry_exhaustion_stores_partial_windows() -> None:
    fakes = _seed_ready_fakes()
    fakes.settings = fakes.settings.model_copy(
        update={"micro_event_window_concurrency_limit": 3}
    )
    _seed_cues(fakes, cue_starts_ms=[0, 31 * 60_000, 62 * 60_000])
    fakes.extractor.failures_by_window = {
        2: [
            RuntimeError("codex failed 1"),
            RuntimeError("codex failed 2"),
            RuntimeError("codex failed 3"),
        ]
    }
    fakes.extractor.responses_by_window = {
        1: _extractor_json("tr1-c000001", "tr1-c000001"),
        3: _extractor_json("tr1-c000003", "tr1-c000003"),
    }

    response = asyncio.run(_extract(fakes))
    detail = asyncio.run(_get_detail(fakes, video_task_id=response["videoTaskId"]))

    assert response["status"] == "failed"
    assert response["errorType"] == "RuntimeError"
    assert response["errorMessage"] == "codex failed 3"
    assert fakes.pipeline_jobs.jobs[1].status == "failed"
    assert fakes.video_tasks.tasks[2].status == "failed"
    assert [window["windowIndex"] for window in detail["windows"]] == [1, 2, 3]
    failed_window = detail["windows"][1]
    assert failed_window["status"] == "failed"
    assert failed_window["validationError"] == "RuntimeError: codex failed 3"
    assert fakes.extractor.started_window_indices.count(2) == 3
    event_types = [event.event_type for event in fakes.events.events]
    assert event_types.count("micro_event_extract.window_retry_requested") == 2
    assert "micro_event_extract.window_retry_failed" in event_types
    assert set(fakes.micro_events.upserted_window_indices) >= {1, 2, 3}


def test_micro_event_retry_failed_task_resumes_successful_windows() -> None:
    fakes = _seed_ready_fakes()
    fakes.settings = fakes.settings.model_copy(
        update={"micro_event_window_concurrency_limit": 3}
    )
    _seed_cues(fakes, cue_starts_ms=[0, 31 * 60_000, 62 * 60_000])
    fakes.extractor.failures_by_window = {
        2: [
            RuntimeError("codex failed 1"),
            RuntimeError("codex failed 2"),
            RuntimeError("codex failed 3"),
        ]
    }
    fakes.extractor.responses_by_window = {
        1: _extractor_json("tr1-c000001", "tr1-c000001"),
        2: _extractor_json("tr1-c000002", "tr1-c000002"),
        3: _extractor_json("tr1-c000003", "tr1-c000003"),
    }

    failed = asyncio.run(_extract(fakes))
    retried = asyncio.run(_extract(fakes, json={"retryFailed": True}))
    detail = asyncio.run(_get_detail(fakes, video_task_id=failed["videoTaskId"]))

    assert retried["status"] == "succeeded"
    assert [window["status"] for window in detail["windows"]] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert fakes.extractor.started_window_indices.count(1) == 1
    assert fakes.extractor.started_window_indices.count(2) == 4
    assert fakes.extractor.started_window_indices.count(3) == 1
    assert detail["outputJson"]["resumedWindowCount"] == 2
    assert detail["outputJson"]["executedWindowCount"] == 1
    assert detail["outputJson"]["failedWindowCount"] == 0
    event_types = [event.event_type for event in fakes.events.events]
    assert "micro_event_extract.partial_resume_used" in event_types


def test_micro_event_retry_failed_task_runs_missing_windows_only() -> None:
    fakes = _seed_ready_fakes()
    fakes.settings = fakes.settings.model_copy(
        update={"micro_event_window_concurrency_limit": 3}
    )
    _seed_cues(fakes, cue_starts_ms=[0, 31 * 60_000, 62 * 60_000])
    fakes.extractor.responses_by_window = {
        1: _extractor_json("tr1-c000001", "tr1-c000001"),
        2: "not json",
        3: _extractor_json("tr1-c000003", "tr1-c000003"),
    }

    failed = asyncio.run(_extract(fakes))
    fakes.micro_events.windows_by_task[failed["videoTaskId"]] = [
        window
        for window in fakes.micro_events.windows_by_task[failed["videoTaskId"]]
        if window.window_index == 1
    ]
    fakes.extractor.responses_by_window[2] = _extractor_json(
        "tr1-c000002",
        "tr1-c000002",
    )

    retried = asyncio.run(_extract(fakes, json={"retryFailed": True}))
    detail = asyncio.run(_get_detail(fakes, video_task_id=failed["videoTaskId"]))

    assert retried["status"] == "succeeded"
    assert [window["windowIndex"] for window in detail["windows"]] == [1, 2, 3]
    assert fakes.extractor.started_window_indices.count(1) == 1
    assert fakes.extractor.started_window_indices.count(2) == 2
    assert fakes.extractor.started_window_indices.count(3) == 2
    assert detail["outputJson"]["resumedWindowCount"] == 1
    assert detail["outputJson"]["executedWindowCount"] == 2


def test_micro_event_retry_stale_partial_reexecutes_all_windows() -> None:
    fakes = _seed_ready_fakes()
    fakes.settings = fakes.settings.model_copy(
        update={"micro_event_window_concurrency_limit": 3}
    )
    _seed_cues(fakes, cue_starts_ms=[0, 31 * 60_000, 62 * 60_000])
    fakes.extractor.responses_by_window = {
        1: _extractor_json("tr1-c000001", "tr1-c000001"),
        2: "not json",
        3: _extractor_json("tr1-c000003", "tr1-c000003"),
    }

    failed = asyncio.run(_extract(fakes))
    windows = fakes.micro_events.windows_by_task[failed["videoTaskId"]]
    windows[0] = replace(windows[0], cue_count=999)
    fakes.extractor.responses_by_window[2] = _extractor_json(
        "tr1-c000002",
        "tr1-c000002",
    )

    retried = asyncio.run(_extract(fakes, json={"retryFailed": True}))
    detail = asyncio.run(_get_detail(fakes, video_task_id=failed["videoTaskId"]))

    assert retried["status"] == "succeeded"
    assert [window["windowIndex"] for window in detail["windows"]] == [1, 2, 3]
    assert fakes.extractor.started_window_indices.count(1) == 2
    assert fakes.extractor.started_window_indices.count(2) == 2
    assert fakes.extractor.started_window_indices.count(3) == 2
    assert detail["outputJson"]["resumedWindowCount"] == 0
    assert detail["outputJson"]["executedWindowCount"] == 3
    event_types = [event.event_type for event in fakes.events.events]
    assert "micro_event_extract.partial_resume_skipped" in event_types


def test_micro_event_extract_openapi_paths_are_registered() -> None:
    schema = create_app().openapi()

    assert schema["paths"]["/videos/{video_id}/video-tasks/micro-event-extract"][
        "post"
    ]["tags"] == ["micro-events"]
    assert schema["paths"]["/video-tasks/micro-event-extract"]["post"]["tags"] == [
        "micro-events"
    ]
    assert schema["paths"]["/video-tasks/micro-event-extract/enqueue"]["post"]["tags"] == [
        "micro-events"
    ]
    assert schema["paths"]["/videos/{video_id}/micro-event-extractions/latest"]["get"][
        "tags"
    ] == ["micro-events"]


async def _extract(
    fakes: _Fakes,
    *,
    json: dict[str, Any] | None = None,
    expected_status: int = 201,
) -> Any:
    app = _app(fakes)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/videos/1/video-tasks/micro-event-extract",
            json=json,
        )

    assert response.status_code == expected_status, response.text
    return response.json()


async def _extract_all(
    fakes: _Fakes,
    *,
    json: dict[str, Any] | None = None,
    expected_status: int = 201,
) -> Any:
    app = _app(fakes)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/video-tasks/micro-event-extract",
            json=json,
        )

    assert response.status_code == expected_status, response.text
    return response.json()


async def _enqueue(
    fakes: _Fakes,
    *,
    json: dict[str, Any] | None = None,
    expected_status: int = 201,
) -> Any:
    app = _app(fakes)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/video-tasks/micro-event-extract/enqueue",
            json=json,
        )

    assert response.status_code == expected_status, response.text
    return response.json()


async def _get_latest(fakes: _Fakes, *, expected_status: int = 200) -> Any:
    app = _app(fakes)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/videos/1/micro-event-extractions/latest")

    assert response.status_code == expected_status, response.text
    return response.json()


async def _get_detail(
    fakes: _Fakes,
    *,
    video_task_id: int,
    expected_status: int = 200,
) -> Any:
    app = _app(fakes)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(f"/videos/1/micro-event-extractions/{video_task_id}")

    assert response.status_code == expected_status, response.text
    return response.json()


def _warning_types(validation_error: str | None) -> set[str]:
    if validation_error is None:
        return set()
    warnings = json.loads(validation_error)
    assert isinstance(warnings, list)
    return {
        str(warning.get("type"))
        for warning in warnings
        if isinstance(warning, dict)
    }


def _app(fakes: _Fakes) -> Any:
    app = create_app()
    app.dependency_overrides[get_channel_repository] = lambda: fakes.channels
    app.dependency_overrides[get_streamer_repository] = lambda: fakes.streamers
    app.dependency_overrides[get_domain_knowledge_repository] = (
        lambda: fakes.domain_knowledge
    )
    app.dependency_overrides[get_video_repository] = lambda: fakes.videos
    app.dependency_overrides[get_video_task_repository] = lambda: fakes.video_tasks
    app.dependency_overrides[get_pipeline_job_repository] = lambda: fakes.pipeline_jobs
    app.dependency_overrides[get_youtube_transcript_repository] = lambda: fakes.transcripts
    app.dependency_overrides[get_transcript_cue_repository] = lambda: fakes.cues
    app.dependency_overrides[get_micro_event_extraction_repository] = (
        lambda: fakes.micro_events
    )
    app.dependency_overrides[get_micro_event_extractor] = lambda: fakes.extractor
    app.dependency_overrides[get_operation_event_recorder] = lambda: fakes.events
    app.dependency_overrides[get_llm_trace_recorder] = lambda: fakes.llm_traces
    app.dependency_overrides[get_prompt_resolver] = lambda: fakes.prompt_resolver
    app.dependency_overrides[get_settings] = lambda: fakes.settings
    return app


def _use_case(fakes: _Fakes) -> ExtractVideoMicroEventsUseCase:
    return ExtractVideoMicroEventsUseCase(
        videos=fakes.videos,
        video_tasks=fakes.video_tasks,
        transcripts=fakes.transcripts,
        transcript_cues=fakes.cues,
        channels=fakes.channels,
        streamers=fakes.streamers,
        domain_knowledge=fakes.domain_knowledge,
        pipeline_jobs=fakes.pipeline_jobs,
        micro_events=fakes.micro_events,
        extractor=fakes.extractor,
        prompt_resolver=fakes.prompt_resolver,
        timeout_seconds=fakes.settings.micro_event_extract_timeout_seconds,
        concurrency_limit=fakes.settings.micro_event_window_concurrency_limit,
        model=fakes.settings.model,
        reasoning_effort=fakes.settings.reasoning_effort,
        events=fakes.events,
        llm_traces=fakes.llm_traces,
    )


def _llm_trace_events(base_dir: Path, source: str) -> list[dict[str, object]]:
    paths = list(base_dir.glob(f"*/{source}.jsonl"))
    assert len(paths) == 1
    return [
        json.loads(line)
        for line in paths[0].read_text(encoding="utf-8").splitlines()
        if line
    ]


def _seed_ready_fakes() -> _Fakes:
    fakes = _Fakes()
    _seed_ready_video(fakes)
    return fakes


def _db_prompt(
    *,
    version_id: int,
    version_label: str,
    body: str,
    sha: str,
) -> ResolvedPrompt:
    return ResolvedPrompt(
        key=MICRO_EVENT_EXTRACT_PROMPT_KEY,
        version_id=version_id,
        version_label=version_label,
        body=body,
        body_sha256=sha,
        source="database",
    )


def _extract_input_hash_for_prompt_version(*, version_id: int, sha: str) -> str:
    fakes = _seed_ready_fakes()
    fakes.prompt_resolver.version_prompts[
        (MICRO_EVENT_EXTRACT_PROMPT_KEY, version_id)
    ] = _db_prompt(
        version_id=version_id,
        version_label=f"db-v{version_id}",
        body=f"PROMPT {version_id}\n",
        sha=sha,
    )
    asyncio.run(_extract(fakes, json={"promptVersionId": version_id}))
    return fakes.video_tasks.tasks[2].input_hash


def _seed_ready_video(
    fakes: _Fakes,
    *,
    video_id: int = 1,
    transcript_id: int = 1,
    cue_task_id: int = 1,
    youtube_video_id: str = YOUTUBE_VIDEO_ID,
    published_at: datetime = NOW,
) -> None:
    _seed_video(
        fakes,
        video_id=video_id,
        youtube_video_id=youtube_video_id,
        published_at=published_at,
    )
    _seed_transcript(
        fakes,
        transcript_id=transcript_id,
        youtube_video_id=youtube_video_id,
    )
    _seed_cues(fakes, transcript_id=transcript_id)
    _seed_cue_task(
        fakes,
        task_id=cue_task_id,
        video_id=video_id,
        transcript_id=transcript_id,
    )


def _seed_video(
    fakes: _Fakes,
    *,
    video_id: int = 1,
    youtube_video_id: str = YOUTUBE_VIDEO_ID,
    published_at: datetime = NOW,
) -> None:
    fakes.videos.videos[video_id] = VideoRecord(
        id=video_id,
        channel_id=1,
        youtube_video_id=youtube_video_id,
        title=f"Live VOD {video_id}",
        description="Description",
        published_at=published_at,
        duration="PT1H",
        thumbnail_url=None,
        source_listing_api_call_id=None,
        source_details_api_call_id=None,
        source_job_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _seed_transcript(
    fakes: _Fakes,
    *,
    transcript_id: int = 1,
    youtube_video_id: str = YOUTUBE_VIDEO_ID,
) -> None:
    fakes.transcripts.records[transcript_id] = YouTubeTranscriptMetadataRecord(
        id=transcript_id,
        video_id=youtube_video_id,
        language="Korean",
        language_code="ko",
        is_generated=True,
        requested_languages=("ko", "en"),
        preserve_formatting=False,
        storage_bucket="raw",
        storage_object_name=f"youtube/transcripts/{youtube_video_id}.json",
        storage_uri=f"s3://raw/youtube/transcripts/{youtube_video_id}.json",
        response_sha256="a" * 64,
        segment_count=2,
        text_length=10,
        notes=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _seed_cues(
    fakes: _Fakes,
    *,
    transcript_id: int = 1,
    cue_starts_ms: list[int] | None = None,
) -> None:
    starts = cue_starts_ms or [0, 60_000]
    fakes.cues.records[transcript_id] = [
        TranscriptCueRecord(
            id=index,
            transcript_id=transcript_id,
            cue_id=f"tr{transcript_id}-c{index:06d}",
            cue_index=index,
            text=f"cue {index}",
            start_ms=start_ms,
            end_ms=start_ms + 10_000,
            duration_ms=10_000,
            source_segment_index=index - 1,
            source_job_id=None,
            source_job_attempt_id=None,
            created_at=NOW,
            updated_at=NOW,
        )
        for index, start_ms in enumerate(starts, start=1)
    ]


def _seed_cue_task(
    fakes: _Fakes,
    *,
    task_id: int = 1,
    video_id: int = 1,
    transcript_id: int = 1,
) -> None:
    fakes.video_tasks.tasks[task_id] = VideoTaskRecord(
        id=task_id,
        video_id=video_id,
        task_name="transcript_cue_generate",
        task_version="v1",
        input_hash="c" * 64,
        status="succeeded",
        worker_id=None,
        timeout_seconds=600,
        job_id=None,
        job_attempt_id=None,
        output_transcript_id=transcript_id,
        output_json={"cueCount": 2},
        error_type=None,
        error_message=None,
        started_at=NOW,
        completed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    fakes.video_tasks.next_id = max(fakes.video_tasks.next_id, task_id + 1)


def _extractor_json(
    start_cue_id: str = "tr1-c000001",
    end_cue_id: str | None = "tr1-c000002",
) -> str:
    end_cue_id = end_cue_id or start_cue_id
    return json.dumps(
        {
            "events": [
                {
                    "start_cue_id": start_cue_id,
                    "end_cue_id": end_cue_id,
                    "event": "스트리머가 방송 주제를 설명한다.",
                    "program_mode": "JUST_CHATTING",
                    "content_kind": "META_CHAT",
                    "topics": ["방송 주제"],
                    "relation_to_previous": "NEW_TOPIC",
                    "continues_to_next": False,
                    "evidence_cue_ids": [start_cue_id],
                    "support_level": "DIRECT",
                }
            ],
            "excluded_ranges": [],
            "asr_correction_candidates": [
                {
                    "original": "코덱쓰",
                    "suggested": "Codex",
                    "correction_type": "PROPER_NOUN",
                    "apply_scope": "SEARCH_ONLY",
                    "confidence": 0.8,
                }
            ],
        },
        ensure_ascii=False,
    )


def _extractor_json_for_ranges(
    *,
    event_ranges: list[tuple[str, str, list[str]]],
    excluded_ranges: list[tuple[str, str, str]] | None = None,
) -> str:
    return json.dumps(
        {
            "events": [
                {
                    "start_cue_id": start_cue_id,
                    "end_cue_id": end_cue_id,
                    "event": "The streamer discusses a distinct topic.",
                    "program_mode": "JUST_CHATTING",
                    "content_kind": "META_CHAT",
                    "topics": ["topic"],
                    "relation_to_previous": "NEW_TOPIC",
                    "continues_to_next": False,
                    "evidence_cue_ids": evidence_cue_ids,
                    "support_level": "DIRECT",
                }
                for start_cue_id, end_cue_id, evidence_cue_ids in event_ranges
            ],
            "excluded_ranges": [
                {
                    "start_cue_id": start_cue_id,
                    "end_cue_id": end_cue_id,
                    "reason": reason,
                }
                for start_cue_id, end_cue_id, reason in (excluded_ranges or [])
            ],
            "asr_correction_candidates": [],
        }
    )


def _prompt_metadata(prompt: str) -> dict[str, Any]:
    for line in prompt.splitlines():
        payload = _json_line(line)
        if payload is not None and "videoTitle" in payload:
            return payload
    raise AssertionError("Missing prompt metadata.")


def _prompt_cue_rows(prompt: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in prompt.splitlines():
        payload = _json_line(line)
        if payload is not None and "cue_id" in payload:
            rows.append(payload)
    return rows


def _json_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
