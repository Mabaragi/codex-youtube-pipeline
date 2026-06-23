from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_micro_event_extraction_repository,
    get_micro_event_extractor,
    get_operation_event_recorder,
    get_pipeline_job_repository,
    get_settings,
    get_transcript_cue_repository,
    get_video_repository,
    get_video_task_repository,
    get_youtube_transcript_repository,
)
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.micro_events.ports import (
    AsrCorrectionCandidateRecord,
    MicroEventCandidateRecord,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionRepositoryPort,
    MicroEventExtractionRequest,
    MicroEventExtractionResult,
    MicroEventExtractionWindowCreate,
    MicroEventExtractionWindowRecord,
    MicroEventExtractorPort,
)
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
from codex_sdk_cli.settings import CliSettings

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
        return []

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

    async def count_running(self, *, task_name: str) -> int:
        return sum(
            task.task_name == task_name and task.status == "running"
            for task in self.tasks.values()
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
        return list(self.records.values())

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
    ) -> PipelineJobAttemptRecord:
        return self._update_attempt(
            attempt_id,
            status="failed",
            output_json=None,
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
        self.next_asr_id = 1

    async def delete_extraction(self, video_task_id: int) -> None:
        self.windows_by_task.pop(video_task_id, None)

    async def replace_extraction(
        self,
        video_task_id: int,
        windows: list[MicroEventExtractionWindowCreate],
    ) -> MicroEventExtractionDetailRecord | None:
        records: list[MicroEventExtractionWindowRecord] = []
        for window in windows:
            micro_events: list[MicroEventCandidateRecord] = []
            for candidate in window.micro_events:
                micro_events.append(
                    MicroEventCandidateRecord(
                        id=self.next_micro_event_id,
                        window_id=self.next_window_id,
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
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                self.next_micro_event_id += 1
            asr_candidates: list[AsrCorrectionCandidateRecord] = []
            for candidate in window.asr_correction_candidates:
                asr_candidates.append(
                    AsrCorrectionCandidateRecord(
                        id=self.next_asr_id,
                        window_id=self.next_window_id,
                        video_task_id=window.video_task_id,
                        transcript_id=window.transcript_id,
                        candidate_index=candidate.candidate_index,
                        original=candidate.original,
                        suggested=candidate.suggested,
                        correction_type=candidate.correction_type,
                        apply_scope=candidate.apply_scope,
                        evidence_cue_ids=candidate.evidence_cue_ids,
                        confidence=candidate.confidence,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                self.next_asr_id += 1
            records.append(
                MicroEventExtractionWindowRecord(
                    id=self.next_window_id,
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
                    asr_correction_candidates=asr_candidates,
                )
            )
            self.next_window_id += 1
        self.windows_by_task[video_task_id] = records
        first = windows[0] if windows else None
        if first is None:
            return None
        return await self.get_extraction(video_id=first.video_id, video_task_id=video_task_id)

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


class FakeMicroEventExtractor(MicroEventExtractorPort):
    def __init__(self) -> None:
        self.responses: list[str] = []
        self.prompts: list[str] = []

    async def extract_window(
        self,
        request: MicroEventExtractionRequest,
    ) -> MicroEventExtractionResult:
        self.prompts.append(request.prompt)
        response = self.responses.pop(0) if self.responses else _extractor_json()
        return MicroEventExtractionResult(
            thread_id=f"thread-{len(self.prompts)}",
            turn_id=f"turn-{len(self.prompts)}",
            status="completed",
            final_response=response,
        )


class FakeOperationEventRecorder(OperationEventRecorderPort):
    def __init__(self) -> None:
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.events.append(event)


class _Fakes:
    def __init__(self) -> None:
        self.videos = FakeVideoRepository()
        self.video_tasks = FakeVideoTaskRepository(self.videos)
        self.pipeline_jobs = FakePipelineJobRepository()
        self.transcripts = FakeTranscriptRepository()
        self.cues = FakeTranscriptCueRepository()
        self.micro_events = FakeMicroEventExtractionRepository(
            self.videos,
            self.video_tasks,
        )
        self.extractor = FakeMicroEventExtractor()
        self.events = FakeOperationEventRecorder()
        self.settings = CliSettings(
            micro_event_extract_timeout_seconds=60,
            micro_event_extract_concurrency_limit=1,
        )


def test_micro_event_extract_succeeds_and_detail_can_be_read() -> None:
    fakes = _seed_ready_fakes()

    response = asyncio.run(_extract(fakes))
    latest = asyncio.run(_get_latest(fakes))

    assert response["status"] == "succeeded"
    assert response["reason"] == "extracted"
    assert response["windowCount"] == 1
    assert response["microEventCount"] == 1
    assert response["asrCorrectionCandidateCount"] == 1
    assert latest["videoTaskId"] == response["videoTaskId"]
    assert latest["windows"][0]["rawResponseText"]
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert fakes.video_tasks.tasks[2].status == "succeeded"


def test_micro_event_extract_missing_video_returns_not_found() -> None:
    response = asyncio.run(_extract(_Fakes(), expected_status=404))

    assert response == {"detail": "Video not found."}


def test_micro_event_extract_requires_succeeded_cue_task() -> None:
    fakes = _Fakes()
    _seed_video(fakes)
    _seed_transcript(fakes)
    _seed_cues(fakes)

    response = asyncio.run(_extract(fakes, expected_status=409))

    assert response == {"detail": "Succeeded transcript cue generation task is required."}
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


def test_micro_event_extract_uses_thirty_minute_windows_with_five_minute_overlap() -> None:
    fakes = _seed_ready_fakes()
    _seed_cues(fakes, cue_starts_ms=[0, 31 * 60_000])
    fakes.extractor.responses = [
        _extractor_json("tr1-c000001"),
        _extractor_json("tr1-c000002"),
    ]

    response = asyncio.run(_extract(fakes))

    assert response["windowCount"] == 2
    assert len(fakes.extractor.prompts) == 2


def test_micro_event_extract_openapi_paths_are_registered() -> None:
    schema = create_app().openapi()

    assert schema["paths"]["/videos/{video_id}/video-tasks/micro-event-extract"][
        "post"
    ]["tags"] == ["micro-events"]
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


def _app(fakes: _Fakes) -> Any:
    app = create_app()
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
    app.dependency_overrides[get_settings] = lambda: fakes.settings
    return app


def _seed_ready_fakes() -> _Fakes:
    fakes = _Fakes()
    _seed_video(fakes)
    _seed_transcript(fakes)
    _seed_cues(fakes)
    _seed_cue_task(fakes)
    return fakes


def _seed_video(fakes: _Fakes) -> None:
    fakes.videos.videos[1] = VideoRecord(
        id=1,
        channel_id=1,
        youtube_video_id=YOUTUBE_VIDEO_ID,
        title="Live VOD",
        description="Description",
        published_at=NOW,
        duration="PT1H",
        thumbnail_url=None,
        source_listing_api_call_id=None,
        source_details_api_call_id=None,
        source_job_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _seed_transcript(fakes: _Fakes) -> None:
    fakes.transcripts.records[1] = YouTubeTranscriptMetadataRecord(
        id=1,
        video_id=YOUTUBE_VIDEO_ID,
        language="Korean",
        language_code="ko",
        is_generated=True,
        requested_languages=("ko", "en"),
        preserve_formatting=False,
        storage_bucket="raw",
        storage_object_name="youtube/transcripts/abc123DEF45.json",
        storage_uri="s3://raw/youtube/transcripts/abc123DEF45.json",
        response_sha256="a" * 64,
        segment_count=2,
        text_length=10,
        notes=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _seed_cues(fakes: _Fakes, *, cue_starts_ms: list[int] | None = None) -> None:
    starts = cue_starts_ms or [0, 60_000]
    fakes.cues.records[1] = [
        TranscriptCueRecord(
            id=index,
            transcript_id=1,
            cue_id=f"tr1-c{index:06d}",
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


def _seed_cue_task(fakes: _Fakes) -> None:
    fakes.video_tasks.tasks[1] = VideoTaskRecord(
        id=1,
        video_id=1,
        task_name="transcript_cue_generate",
        task_version="v1",
        input_hash="c" * 64,
        status="succeeded",
        worker_id=None,
        timeout_seconds=600,
        job_id=None,
        job_attempt_id=None,
        output_transcript_id=1,
        output_json={"cueCount": 2},
        error_type=None,
        error_message=None,
        started_at=NOW,
        completed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    fakes.video_tasks.next_id = 2


def _extractor_json(cue_id: str = "tr1-c000001") -> str:
    return json.dumps(
        {
            "micro_events": [
                {
                    "activity": "JUST_CHATTING",
                    "event": "스트리머가 방송 주제를 설명한다.",
                    "start_cue_id": cue_id,
                    "end_cue_id": cue_id,
                    "evidence_cue_ids": [cue_id],
                    "boundary_before": True,
                    "boundary_after": False,
                    "confidence": 0.9,
                }
            ],
            "asr_correction_candidates": [
                {
                    "original": "코덱스",
                    "suggested": "Codex",
                    "correction_type": "PROPER_NOUN",
                    "apply_scope": "SEARCH_ONLY",
                    "evidence_cue_ids": [cue_id],
                    "confidence": 0.8,
                }
            ],
            "carry_out": {"unfinished": False},
        },
        ensure_ascii=False,
    )
