from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

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
from codex_sdk_cli.domains.transcript_cues.use_cases import GenerateTranscriptCuesUseCase
from codex_sdk_cli.domains.youtube_transcripts.exceptions import YouTubeTranscriptStorageError
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    TranscriptStorageLocation,
    YouTubeTranscriptMetadataFilters,
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptRecord,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageReadRequest,
    YouTubeTranscriptStorageSaveRequest,
)

NOW = datetime(2026, 6, 22, 1, 2, tzinfo=UTC)


class FakeTranscriptRepository(YouTubeTranscriptRepositoryPort):
    def __init__(self) -> None:
        self.metadata = _metadata_record()

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
        return [self.metadata]

    async def get_transcript_metadata(
        self,
        transcript_id: int,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return self.metadata if transcript_id == self.metadata.id else None

    async def update_transcript_notes(
        self,
        transcript_id: int,
        notes: str | None,
    ) -> YouTubeTranscriptMetadataRecord | None:
        return None

    async def delete_transcript_metadata(self, transcript_id: int) -> bool:
        return False


class FakeTranscriptStorage(YouTubeTranscriptStoragePort):
    def __init__(self, payload: bytes | None = None) -> None:
        self.payload = payload or (
            b'{"videoId":"abc123DEF45","language":"Korean","languageCode":"ko",'
            b'"isGenerated":true,"text":"hello\\nworld",'
            b'"segments":[{"text":"hello","start":0.0,"duration":1.25},'
            b'{"text":"world","start":1.25,"duration":2.5}],'
            b'"storage":{"bucket":"raw","objectName":"youtube/transcripts/abc-hash.json",'
            b'"uri":"s3://raw/youtube/transcripts/abc-hash.json"}}'
        )
        self.reads: list[YouTubeTranscriptStorageReadRequest] = []

    def location_for(self, object_name: str) -> TranscriptStorageLocation:
        return TranscriptStorageLocation(
            bucket="raw",
            object_name=object_name,
            uri=f"s3://raw/{object_name}",
        )

    async def save_transcript(
        self,
        request: YouTubeTranscriptStorageSaveRequest,
    ) -> TranscriptStorageLocation:
        raise NotImplementedError

    async def read_transcript(
        self,
        request: YouTubeTranscriptStorageReadRequest,
    ) -> bytes:
        self.reads.append(request)
        return self.payload


class FakeTranscriptCueRepository(TranscriptCueRepositoryPort):
    def __init__(self) -> None:
        self.records: list[TranscriptCueRecord] = []

    async def replace_cues(
        self,
        transcript_id: int,
        cues: list[TranscriptCueCreate],
    ) -> list[TranscriptCueRecord]:
        self.records = [
            TranscriptCueRecord(
                id=index,
                transcript_id=cue.transcript_id,
                cue_id=cue.cue_id,
                cue_index=cue.cue_index,
                text=cue.text,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                duration_ms=cue.duration_ms,
                source_segment_index=cue.source_segment_index,
                source_job_id=cue.source_job_id,
                source_job_attempt_id=cue.source_job_attempt_id,
                created_at=NOW,
                updated_at=NOW,
            )
            for index, cue in enumerate(cues, start=1)
        ]
        return self.records

    async def list_cues(self, transcript_id: int) -> list[TranscriptCueRecord]:
        return [record for record in self.records if record.transcript_id == transcript_id]

    async def summarize_cues(self, transcript_id: int) -> TranscriptCueSummaryRecord:
        records = await self.list_cues(transcript_id)
        return TranscriptCueSummaryRecord(
            transcript_id=transcript_id,
            cue_count=len(records),
            first_cue_id=records[0].cue_id if records else None,
            last_cue_id=records[-1].cue_id if records else None,
            source_job_id=records[0].source_job_id if records else None,
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
            attempt_no=1,
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
        return self._update_attempt(attempt_id, status="succeeded", output_json=output_json)

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
        error_type: str | None = None,
        error_message: str | None = None,
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
        updated = replace(self.jobs[job_id], status=status, completed_at=NOW)
        self.jobs[job_id] = updated
        return updated


class FakeEventRecorder(OperationEventRecorderPort):
    def __init__(self) -> None:
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.events.append(event)


def test_generate_transcript_cues_creates_child_job_and_cue_rows() -> None:
    fakes = _fakes()

    response = asyncio.run(fakes.use_case.execute(1, parent_job_id=99))

    assert response.transcript_id == 1
    assert response.youtube_video_id == "abc123DEF45"
    assert response.cue_count == 2
    assert response.first_cue_id == "tr1-c000001"
    assert response.last_cue_id == "tr1-c000002"
    assert fakes.pipeline_jobs.jobs[1].step == "transcript_cue_generate"
    assert fakes.pipeline_jobs.jobs[1].parent_job_id == 99
    assert fakes.pipeline_jobs.jobs[1].status == "succeeded"
    assert fakes.pipeline_jobs.attempts[1].status == "succeeded"
    assert [(cue.text, cue.start_ms, cue.end_ms) for cue in fakes.cues.records] == [
        ("hello", 0, 1250),
        ("world", 1250, 3750),
    ]
    assert [event.event_type for event in fakes.events.events] == [
        "transcript_cue_generate.started",
        "transcript_cue_generate.succeeded",
    ]


def test_generate_transcript_cues_marks_job_failed_on_invalid_stored_payload() -> None:
    fakes = _fakes(storage=FakeTranscriptStorage(payload=b"not-json"))

    with pytest.raises(YouTubeTranscriptStorageError):
        asyncio.run(fakes.use_case.execute(1))

    assert fakes.pipeline_jobs.jobs[1].status == "failed"
    assert fakes.pipeline_jobs.attempts[1].status == "failed"
    assert fakes.pipeline_jobs.attempts[1].error_type == "YouTubeTranscriptStorageError"
    assert fakes.cues.records == []
    assert fakes.events.events[-1].event_type == "transcript_cue_generate.failed"


def test_generate_transcript_cues_retry_uses_existing_job_attempt() -> None:
    fakes = _fakes()
    job = asyncio.run(
        fakes.pipeline_jobs.create_job(
            PipelineJobCreate(
                step="transcript_cue_generate",
                status="running",
                subject_type="transcript",
                subject_id=1,
                external_key="abc123DEF45",
                input_json={"transcriptId": 1},
                input_hash="a" * 64,
            )
        )
    )
    attempt = asyncio.run(fakes.pipeline_jobs.create_attempt(job_id=job.id))

    result = asyncio.run(fakes.use_case.execute_retry_job_attempt(job, attempt))

    assert result["transcriptId"] == 1
    assert result["cueCount"] == 2
    assert fakes.pipeline_jobs.jobs[job.id].status == "succeeded"
    assert fakes.pipeline_jobs.attempts[attempt.id].status == "succeeded"


class _Fakes:
    def __init__(self, *, storage: FakeTranscriptStorage | None = None) -> None:
        self.transcripts = FakeTranscriptRepository()
        self.storage = storage or FakeTranscriptStorage()
        self.cues = FakeTranscriptCueRepository()
        self.pipeline_jobs = FakePipelineJobRepository()
        self.events = FakeEventRecorder()
        self.use_case = GenerateTranscriptCuesUseCase(
            transcripts=self.transcripts,
            storage=self.storage,
            cues=self.cues,
            pipeline_jobs=self.pipeline_jobs,
            events=self.events,
        )


def _fakes(*, storage: FakeTranscriptStorage | None = None) -> _Fakes:
    return _Fakes(storage=storage)


def _metadata_record() -> YouTubeTranscriptMetadataRecord:
    return YouTubeTranscriptMetadataRecord(
        id=1,
        video_id="abc123DEF45",
        language="Korean",
        language_code="ko",
        is_generated=True,
        requested_languages=("ko", "en"),
        preserve_formatting=False,
        storage_bucket="raw",
        storage_object_name="youtube/transcripts/abc-hash.json",
        storage_uri="s3://raw/youtube/transcripts/abc-hash.json",
        response_sha256="a" * 64,
        segment_count=2,
        text_length=11,
        notes=None,
        created_at=NOW,
        updated_at=NOW,
    )
